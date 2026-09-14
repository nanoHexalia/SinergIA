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

    def test_u2_warnings_remain_review_required_until_semantics_wired(self):
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
