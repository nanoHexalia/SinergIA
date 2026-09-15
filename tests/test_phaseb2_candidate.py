from pathlib import Path
import hashlib
import importlib
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROV = ROOT / "provenance" / "sinergia_cobranzas_20260211_01_checking.py"
OLD = "1q0yWNo35lPeNXmdOgMRKvYx1TcHgxJhPPDo4zXq9p_0"
NEW = "12LoMTA8MirP9GIiG3VOInVejGNlvBMYZp9_mmSJbUhM"

class CandidateContractTests(unittest.TestCase):
    def test_provenance_hash_and_size(self):
        data = PROV.read_bytes()
        self.assertEqual(len(data), 642479)
        self.assertEqual(hashlib.sha256(data).hexdigest(), "60e45001b91a1d41faf095fccd56a03462dffe42b1b0ea5f5ed19fe5709a89db")

    def test_candidate_import_is_safe_and_current_config_bound(self):
        mod = importlib.import_module("candidate.entrypoint")
        info = mod.describe_candidate()
        self.assertEqual(info["config_spreadsheet_id"], NEW)
        self.assertFalse(info["runtime_activation"])
        self.assertFalse(info["production_data_access"])

    def test_cleanengine_dict_contract_is_not_tuple_unpacked(self):
        from candidate.runtime_contract import normalize_cleanengine_config
        marker_a, marker_b = object(), object()
        frames = normalize_cleanengine_config({"presets": marker_a, "spec": marker_b})
        self.assertIs(frames.presets, marker_a)
        self.assertIs(frames.spec, marker_b)

    def test_u2_evidence_requires_actual_rule_execution(self):
        from candidate.runtime_contract import validate_u2_evidence
        self.assertFalse(validate_u2_evidence({"applied": [], "warn": []})["promotion_ok"])
        self.assertTrue(validate_u2_evidence({"applied": [{"rule_id": "TEXT_TRIM"}], "warn": []})["promotion_ok"])

    def test_u2_warnings_remain_review_required_at_candidate_promotion_boundary(self):
        from candidate.runtime_contract import validate_u2_evidence
        ev = validate_u2_evidence({"applied": [{"rule_id": "TEXT_TRIM"}], "warn": ["example"]})
        self.assertFalse(ev["promotion_ok"])
        self.assertEqual(ev["status"], "REVIEW_REQUIRED_WARNINGS")

    def test_u2_bridge_uses_mapping_contract_and_emits_promotion_evidence(self):
        from candidate.u2_bridge import execute_u2_cleanengine
        calls = {}
        def loader():
            return {"presets": "PRESETS", "spec": "SPEC"}
        def engine(df, alias, **kwargs):
            calls.update({"df": df, "alias": alias, **kwargs})
            return "OUT", {"applied": [{"rule_id": "TEXT_TRIM"}], "warn": []}
        out, qa, evidence = execute_u2_cleanengine("IN", load_config=loader, apply_engine=engine)
        self.assertEqual(out, "OUT")
        self.assertEqual(calls["df_spec"], "SPEC")
        self.assertEqual(calls["df_presets"], "PRESETS")
        self.assertEqual(calls["alias"], "df_final_sorted")
        self.assertTrue(evidence["promotion_ok"])

    def test_candidate_runtime_files_have_no_legacy_config_or_colab_launch_side_effects(self):
        text = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "candidate").glob("*.py"))
        self.assertNotIn(OLD, text)
        self.assertIn(NEW, text)
        for token in ["google.colab", "authenticate_user()", "app.launch(", "share=True", "/content/sinergia_runs"]:
            self.assertNotIn(token, text)

if __name__ == "__main__":
    unittest.main()

class CandidateIntegrationTests(unittest.TestCase):
    def test_setting_id_resolution_is_exact_and_fails_closed(self):
        from candidate.config_contract import resolve_setting_id
        rows = [
            {"SettingID": "OUT", "Parameters": "folder-A"},
            {"SettingID": "OUT_LOG", "Parameters": "folder-B"},
        ]
        self.assertEqual(resolve_setting_id(rows, "OUT", value_columns=("Parameters",)), "folder-A")
        with self.assertRaises(ValueError):
            resolve_setting_id(rows, "MISSING", value_columns=("Parameters",))
        with self.assertRaises(ValueError):
            resolve_setting_id(rows + [{"SettingID": "OUT", "Parameters": "folder-C"}], "OUT", value_columns=("Parameters",))

    def test_clean_policy_uses_spec_then_preset_and_ignores_eff_columns(self):
        from candidate.config_contract import resolve_clean_rule_policy
        preset = [{
            "preset_id": "DOC_DI_NORMALIZE", "rule_id": "DOC_NORMALIZE",
            "params_json": '{"trim":true,"to_upper":true}',
            "default_severity": "block", "default_action_on_fail": "block_run",
        }]
        spec = {
            "preset_id_calc": "DOC_DI_NORMALIZE", "rule_id_calc": "DOC_NORMALIZE",
            "severity": "info", "action_on_fail": "set_null",
            "severity_eff": "block", "action_eff": "block_run",
        }
        policy = resolve_clean_rule_policy(spec, preset)
        self.assertEqual(policy.severity, "info")
        self.assertEqual(policy.action_on_fail, "set_null")
        self.assertEqual(policy.params, {"trim": True, "to_upper": True})

    def test_clean_policy_falls_back_to_preset_defaults_only_when_spec_is_blank(self):
        from candidate.config_contract import resolve_clean_rule_policy
        preset = [{
            "preset_id": "DATE_RANGE_REASONABLE", "rule_id": "DATE_RANGE",
            "params_json": '{"min":"1900-01-01","max":"today"}',
            "default_severity": "warn", "default_action_on_fail": "warn_only",
        }]
        policy = resolve_clean_rule_policy({"preset_id_calc": "DATE_RANGE_REASONABLE", "severity": "", "action_on_fail": ""}, preset)
        self.assertEqual(policy.rule_id, "DATE_RANGE")
        self.assertEqual(policy.severity, "warn")
        self.assertEqual(policy.action_on_fail, "warn_only")

    def test_candidate_run_context_keeps_one_run_id(self):
        from candidate.run_context import CandidateRunContext
        ctx = CandidateRunContext("TEST", run_id="run-fixed")
        ctx.add_event("A", stage="U2")
        ctx.add_event("B", stage="U2")
        ctx.finalize("PASS")
        snap = ctx.snapshot()
        self.assertEqual(snap["manifest"]["run_id"], "run-fixed")
        self.assertTrue(all(event["run_id"] == "run-fixed" for event in snap["events"]))

    def test_integrated_u2_quality_gate_blocks_before_engine(self):
        from candidate.u2_bridge import execute_u2_candidate
        calls = {"engine": 0}
        def loader(): return {"presets": "PRESETS", "spec": "SPEC"}
        def gate(df, ctx): return False, {"reason": "QUALITY_IN_FAIL"}
        def engine(*args, **kwargs):
            calls["engine"] += 1
            raise AssertionError("engine must not run after a failed QualityGate")
        result = execute_u2_candidate("IN", load_config=loader, quality_gate=gate, apply_engine=engine, run_id="run-gate")
        self.assertEqual(calls["engine"], 0)
        self.assertEqual(result.evidence["status"], "FAIL_QUALITY_GATE")
        self.assertEqual(result.run["manifest"]["status"], "FAIL")
        self.assertEqual(result.run["manifest"]["gates"]["quality_in"]["detail"]["reason"], "QUALITY_IN_FAIL")

    def test_integrated_u2_exception_leaves_fail_evidence_with_same_run_id(self):
        from candidate.u2_bridge import execute_u2_candidate
        def loader(): return {"presets": "PRESETS", "spec": "SPEC"}
        def gate(df, ctx): return True
        def engine(*args, **kwargs): raise RuntimeError("synthetic engine failure")
        result = execute_u2_candidate("IN", load_config=loader, quality_gate=gate, apply_engine=engine, run_id="run-exception")
        self.assertEqual(result.evidence["status"], "FAIL_EXCEPTION")
        self.assertEqual(result.evidence["run_id"], "run-exception")
        self.assertEqual(result.run["manifest"]["status"], "FAIL")
        self.assertTrue(any(event["code"] == "U2_EXCEPTION" for event in result.run["events"]))

    def test_integrated_u2_success_and_warning_paths_are_distinct(self):
        from candidate.u2_bridge import execute_u2_candidate
        def loader(): return {"presets": "PRESETS", "spec": "SPEC"}
        def gate(df, ctx): return True, {"status": "OK"}
        def engine_ok(df, alias, **kwargs): return "OUT", {"applied": [{"rule_id": "TEXT_TRIM"}], "warn": []}
        ok = execute_u2_candidate("IN", load_config=loader, quality_gate=gate, apply_engine=engine_ok, run_id="run-pass")
        self.assertTrue(ok.evidence["promotion_ok"])
        self.assertEqual(ok.run["manifest"]["status"], "PASS")
        self.assertEqual(ok.evidence["run_id"], "run-pass")
        def engine_warn(df, alias, **kwargs): return "OUT", {"applied": [{"rule_id": "TEXT_TRIM"}], "warn": ["synthetic warning"]}
        warn = execute_u2_candidate("IN", load_config=loader, quality_gate=gate, apply_engine=engine_warn, run_id="run-review")
        self.assertFalse(warn.evidence["promotion_ok"])
        self.assertEqual(warn.evidence["status"], "REVIEW_REQUIRED_WARNINGS")
        self.assertEqual(warn.run["manifest"]["status"], "REVIEW_REQUIRED")
