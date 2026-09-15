import unittest

import pandas as pd

from candidate.clean_engine import (
    BindingFailure,
    CanonicalTargetBinding,
    apply_cleanengine_candidate,
    bind_target_exact,
)
from candidate.runtime_contract import validate_u2_evidence
from candidate.u2_bridge import execute_u2_candidate, execute_u2_cleanengine


STRUCTURES = pd.DataFrame([
    {"ArchivoLogico": "IN_SISTECREDITO", "NombreColumna": "Documento de identidad", "AliasCanonico": "DocumentoDeIdentidad"},
    {"ArchivoLogico": "IN_SISTECREDITO", "NombreColumna": "Nombre Completo", "AliasCanonico": "NombreCompleto"},
    {"ArchivoLogico": "IN_SISTECREDITO", "NombreColumna": "Dirección Del Cliente", "AliasCanonico": "DireccionCliente"},
    {"ArchivoLogico": "IN_SISTECREDITO", "NombreColumna": "Reportado a Centrales", "AliasCanonico": "EstadoCentrales"},
    {"ArchivoLogico": "IN_SISTECREDITO", "NombreColumna": "Crédito", "AliasCanonico": "Credito"},
    {"ArchivoLogico": "IN_SISTECREDITO", "NombreColumna": "Almacén", "AliasCanonico": "Almacen"},
    {"ArchivoLogico": "IN_SISTECREDITO", "NombreColumna": "Dirección Almacén", "AliasCanonico": "DireccionAlmacen"},
    {"ArchivoLogico": "IN_SISTECREDITO", "NombreColumna": "Telefono 1", "AliasCanonico": "Telefono1"},
    {"ArchivoLogico": "IN_SISTECREDITO", "NombreColumna": "Telefono 2", "AliasCanonico": "Telefono2"},
    {"ArchivoLogico": "IN_SISTECREDITO", "NombreColumna": "Telefono 3", "AliasCanonico": "Telefono3"},
    {"ArchivoLogico": "IN_SISTECREDITO", "NombreColumna": "Telefono 4", "AliasCanonico": "Telefono4"},
    {"ArchivoLogico": "IN_SISTECREDITO", "NombreColumna": "Teléfono Almacén", "AliasCanonico": "TelefonoAlmacen"},
    {"ArchivoLogico": "OTHER", "NombreColumna": "Documento de identidad", "AliasCanonico": "DocumentoDelIdentidad"},
])

PRESETS = pd.DataFrame([
    {"preset_id": "TXT_TRIM_SPACES", "rule_id": "TEXT_TRIM", "params_json": '{"trim":true,"collapse_internal_spaces":true}', "default_severity": "info", "default_action_on_fail": "set_null"},
    {"preset_id": "TXT_STRIP_ACCENTS", "rule_id": "TEXT_UNICODE", "params_json": '{"trim":true,"strip_accents":true}', "default_severity": "info", "default_action_on_fail": "set_null"},
    {"preset_id": "DOC_DI_NORMALIZE", "rule_id": "DOC_NORMALIZE", "params_json": '{"trim":true,"keep_alnum_only":true,"to_upper":true,"strip_accents":true}', "default_severity": "block", "default_action_on_fail": "block_run"},
    {"preset_id": "PHONE_DIGITS", "rule_id": "PHONE_DIGITS", "params_json": '{"keep_digits_only":true,"min_len":7,"max_len":15}', "default_severity": "warn", "default_action_on_fail": "set_null"},
])


def _spec(targets, preset, rule, order=10, severity="info", action="set_null", alias="df_final_sorted"):
    return {
        "dataset_alias": alias,
        "stage": "normalize",
        "rule_order": order,
        "enabled": "TRUE",
        "target_columns": targets,
        "preset_id_calc": preset,
        "rule_id_calc": rule,
        "severity": severity,
        "action_on_fail": action,
        "severity_eff": "WRONG_DERIVED_VALUE",
        "action_eff": "WRONG_DERIVED_VALUE",
    }


class CanonicalBindingTests(unittest.TestCase):
    def test_alias_binds_exactly_to_present_canonical_name(self):
        result = bind_target_exact(
            "NombreCompleto",
            dataframe_columns=["Nombre Completo"],
            structures=STRUCTURES,
            logical_file="IN_SISTECREDITO",
        )
        self.assertIsInstance(result, CanonicalTargetBinding)
        self.assertEqual(result.dataframe_column, "Nombre Completo")
        self.assertEqual(result.canonical_alias, "NombreCompleto")

    def test_typo_is_not_fuzzy_corrected_across_structure_scope(self):
        result = bind_target_exact(
            "DocumentoDelIdentidad",
            dataframe_columns=["Documento de identidad"],
            structures=STRUCTURES,
            logical_file="IN_SISTECREDITO",
        )
        self.assertIsInstance(result, BindingFailure)
        self.assertEqual(result.code, "UNBOUND_CONFIG_TARGET")

    def test_both_physical_and_alias_columns_fail_ambiguous(self):
        result = bind_target_exact(
            "NombreCompleto",
            dataframe_columns=["Nombre Completo", "NombreCompleto"],
            structures=STRUCTURES,
            logical_file="IN_SISTECREDITO",
        )
        self.assertIsInstance(result, BindingFailure)
        self.assertEqual(result.code, "AMBIGUOUS_DATAFRAME_COLUMN")


class CleanEngineExecutionTests(unittest.TestCase):
    def test_trim_executes_on_bound_physical_column(self):
        df = pd.DataFrame({"Nombre Completo": ["  Ana   Pérez  "]})
        spec = pd.DataFrame([_spec('["NombreCompleto"]', "TXT_TRIM_SPACES", "TEXT_TRIM")])
        out, qa = apply_cleanengine_candidate(df, "df_final_sorted", df_spec=spec, df_presets=PRESETS, df_estructuras=STRUCTURES)
        self.assertEqual(out.loc[0, "Nombre Completo"], "Ana Pérez")
        self.assertEqual(len(qa["applied"]), 1)
        self.assertEqual(qa["binding"]["failure_count"], 0)

    def test_unbound_only_rule_is_not_falsely_counted_as_applied(self):
        df = pd.DataFrame({"Documento de identidad": ["1.234"]})
        spec = pd.DataFrame([_spec('["DocumentoDelIdentidad"]', "DOC_DI_NORMALIZE", "DOC_NORMALIZE", severity="info", action="set_null")])
        out, qa = apply_cleanengine_candidate(df, "df_final_sorted", df_spec=spec, df_presets=PRESETS, df_estructuras=STRUCTURES)
        self.assertTrue(out.equals(df))
        self.assertEqual(qa["applied"], [])
        self.assertEqual(qa["binding"]["failure_count"], 1)
        self.assertTrue(any("UNBOUND_CONFIG_TARGET:DocumentoDelIdentidad" in w for w in qa["warn"]))
        self.assertEqual(validate_u2_evidence(qa)["status"], "FAIL_NO_RULES_APPLIED")

    def test_block_policy_stops_on_binding_failure(self):
        df = pd.DataFrame({"Documento de identidad": ["1.234"]})
        row = _spec('["DocumentoDelIdentidad"]', "DOC_DI_NORMALIZE", "DOC_NORMALIZE", severity="", action="")
        out, qa = apply_cleanengine_candidate(df, "df_final_sorted", df_spec=pd.DataFrame([row]), df_presets=PRESETS, df_estructuras=STRUCTURES)
        self.assertTrue(out.equals(df))
        self.assertTrue(qa["hard_fail"])
        self.assertEqual(qa["applied"], [])
        self.assertEqual(validate_u2_evidence(qa)["status"], "FAIL_HARD_RULE")

    def test_phone_set_null_records_validation_warning(self):
        df = pd.DataFrame({"Telefono 1": ["+57 300 123 4567", "12"]})
        spec = pd.DataFrame([_spec('["Telefono1"]', "PHONE_DIGITS", "PHONE_DIGITS", severity="warn", action="set_null")])
        out, qa = apply_cleanengine_candidate(df, "df_final_sorted", df_spec=spec, df_presets=PRESETS, df_estructuras=STRUCTURES)
        self.assertEqual(out.loc[0, "Telefono 1"], "573001234567")
        self.assertTrue(pd.isna(out.loc[1, "Telefono 1"]))
        self.assertEqual(qa["applied"][0]["failed_cells"], 1)
        self.assertTrue(any("RULE_VALIDATION_FAILURE:PHONE_DIGITS" in w for w in qa["warn"]))

    def test_current_enabled_shape_yields_20_exact_bindings_zero_failures_for_both_datasets(self):
        text_targets = ["TipoDocumento","NombreCompleto","DireccionCliente","EstadoCentrales","Credito","Almacen","DireccionAlmacen"]
        phone_targets = ["Telefono1","Telefono2","Telefono3","Telefono4","TelefonoAlmacen"]
        extra_structures = pd.concat([STRUCTURES, pd.DataFrame([
            {"ArchivoLogico":"IN_SISTECREDITO","NombreColumna":"Tipo de Documento","AliasCanonico":"TipoDocumento"},
        ])], ignore_index=True)
        present_aliases = [*text_targets, "DocumentoDeIdentidad", *phone_targets]
        df = pd.DataFrame({c: [" X "] for c in present_aliases})
        df["DocumentoDeIdentidad"] = ["1.234"]
        df["Telefono1"] = ["3001234567"]
        df["Telefono2"] = ["3001234568"]
        df["Telefono3"] = ["3001234569"]
        df["Telefono4"] = ["3001234570"]
        df["TelefonoAlmacen"] = ["6041234567"]

        for alias in ("df_final_sorted", "df_in_full"):
            with self.subTest(dataset_alias=alias):
                spec = pd.DataFrame([
                    _spec(json_dumps(text_targets), "TXT_TRIM_SPACES", "TEXT_TRIM", 10, alias=alias),
                    _spec(json_dumps(text_targets), "TXT_STRIP_ACCENTS", "TEXT_UNICODE", 20, alias=alias),
                    _spec('["DocumentoDeIdentidad"]', "DOC_DI_NORMALIZE", "DOC_NORMALIZE", 30, "info", "set_null", alias=alias),
                    _spec(json_dumps(phone_targets), "PHONE_DIGITS", "PHONE_DIGITS", 40, "warn", "set_null", alias=alias),
                ])
                _, qa = apply_cleanengine_candidate(
                    df,
                    alias,
                    df_spec=spec,
                    df_presets=PRESETS,
                    df_estructuras=extra_structures,
                )
                self.assertEqual(qa["binding"]["resolved_count"], 20)
                self.assertEqual(qa["binding"]["failure_count"], 0)
                self.assertEqual(qa["binding"]["failures"], [])
                self.assertEqual(len(qa["applied"]), 4)
                self.assertFalse(qa["hard_fail"])


def json_dumps(value):
    import json
    return json.dumps(value, ensure_ascii=False)


class BridgeIntegrationTests(unittest.TestCase):
    def test_simple_bridge_injects_structures_into_real_engine(self):
        df = pd.DataFrame({"Nombre Completo": ["  Ana  "]})
        spec = pd.DataFrame([_spec('["NombreCompleto"]', "TXT_TRIM_SPACES", "TEXT_TRIM")])
        loader = lambda: {"presets": PRESETS, "spec": spec, "structures": STRUCTURES}
        out, qa, evidence = execute_u2_cleanengine(df, load_config=loader, apply_engine=apply_cleanengine_candidate)
        self.assertEqual(out.loc[0, "Nombre Completo"], "Ana")
        self.assertTrue(evidence["promotion_ok"])
        self.assertEqual(qa["binding"]["resolved_count"], 1)

    def test_integrated_bridge_uses_same_structures_and_run_id(self):
        df = pd.DataFrame({"Nombre Completo": ["  Ana  "]})
        spec = pd.DataFrame([_spec('["NombreCompleto"]', "TXT_TRIM_SPACES", "TEXT_TRIM")])
        loader = lambda: {"presets": PRESETS, "spec": spec, "estructuras": STRUCTURES}
        result = execute_u2_candidate(
            df,
            load_config=loader,
            quality_gate=lambda frame, ctx: (True, {"status": "OK"}),
            apply_engine=apply_cleanengine_candidate,
            run_id="run-real-engine",
        )
        self.assertEqual(result.output.loc[0, "Nombre Completo"], "Ana")
        self.assertEqual(result.evidence["run_id"], "run-real-engine")
        self.assertEqual(result.run["manifest"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
