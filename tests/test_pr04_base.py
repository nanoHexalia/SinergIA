import unittest
from copy import deepcopy

import pandas as pd

from candidate.config_contract import resolve_dataset_contract
from candidate.pr04_base import validate_pr04_base


def structure_rows():
    return [
        {"Sistema":"SinergIA","ArchivoLogico":"IN_SISTECREDITO","ColumnaOrden":"1","NombreColumna":"Documento","AliasCanonico":"DocumentoCanon","TipoDato":"Texto","Obligatoria":"Si","PermiteNulos":"No"},
        {"Sistema":"SinergIA","ArchivoLogico":"IN_SISTECREDITO","ColumnaOrden":"2","NombreColumna":"Valor","AliasCanonico":"ValorCanon","TipoDato":"Numero","Obligatoria":"Si","PermiteNulos":"Si"},
        {"Sistema":"SinergIA","ArchivoLogico":"IN_SISTECREDITO","ColumnaOrden":"3","NombreColumna":"Fecha","AliasCanonico":"FechaCanon","TipoDato":"Fecha","Obligatoria":"No","PermiteNulos":"Si"},
    ]


def good_frame():
    return pd.DataFrame({
        "Documento":["100","200"],
        "Valor":["10.5",20],
        "Fecha":["01/02/2026", pd.Timestamp("2026-03-04")],
    })


class DatasetContractTests(unittest.TestCase):
    def test_resolves_exact_order_and_flags(self):
        contract = resolve_dataset_contract(structure_rows(), "IN_SISTECREDITO")
        self.assertEqual(contract.columns_ordered, ("Documento","Valor","Fecha"))
        self.assertEqual(contract.required_columns, ("Documento","Valor"))
        self.assertFalse(contract.columns[0].nullable)
        self.assertTrue(contract.columns[2].nullable)

    def test_exact_scope_does_not_casefold_authority(self):
        with self.assertRaises(ValueError):
            resolve_dataset_contract(structure_rows(), "in_sistecredito")

    def test_rejects_duplicate_order(self):
        rows = structure_rows(); rows[1]["ColumnaOrden"] = "1"
        with self.assertRaises(ValueError):
            resolve_dataset_contract(rows, "IN_SISTECREDITO")

    def test_rejects_non_contiguous_order(self):
        rows = structure_rows(); rows[2]["ColumnaOrden"] = "4"
        with self.assertRaises(ValueError):
            resolve_dataset_contract(rows, "IN_SISTECREDITO")

    def test_rejects_duplicate_name(self):
        rows = structure_rows(); rows[2]["NombreColumna"] = "Valor"
        with self.assertRaises(ValueError):
            resolve_dataset_contract(rows, "IN_SISTECREDITO")

    def test_rejects_cross_column_alias_ambiguity(self):
        rows = structure_rows(); rows[2]["AliasCanonico"] = "Documento"
        with self.assertRaises(ValueError):
            resolve_dataset_contract(rows, "IN_SISTECREDITO")

    def test_rejects_unknown_type(self):
        rows = structure_rows(); rows[1]["TipoDato"] = "DecimalMagico"
        with self.assertRaises(ValueError):
            resolve_dataset_contract(rows, "IN_SISTECREDITO")

    def test_rejects_implicit_boolean(self):
        rows = structure_rows(); rows[0]["PermiteNulos"] = "quizas"
        with self.assertRaises(ValueError):
            resolve_dataset_contract(rows, "IN_SISTECREDITO")


class PR04BaseTests(unittest.TestCase):
    def test_passes_exact_schema_nullability_and_types(self):
        df = good_frame(); before = df.copy(deep=True)
        result = validate_pr04_base(df, structure_rows=structure_rows())
        self.assertTrue(result.ok); self.assertEqual(result.status, "PASS")
        pd.testing.assert_frame_equal(df, before)

    def test_missing_column_fails_schema(self):
        result = validate_pr04_base(good_frame().drop(columns=["Fecha"]), structure_rows=structure_rows())
        self.assertFalse(result.ok); self.assertEqual(result.status, "FAIL_SCHEMA")
        self.assertEqual(result.missing_columns, ("Fecha",))

    def test_extra_column_fails_schema(self):
        df = good_frame(); df["Extra"] = 1
        result = validate_pr04_base(df, structure_rows=structure_rows())
        self.assertFalse(result.ok); self.assertEqual(result.extra_columns, ("Extra",))

    def test_wrong_order_fails_schema(self):
        df = good_frame().loc[:, ["Valor","Documento","Fecha"]]
        result = validate_pr04_base(df, structure_rows=structure_rows())
        self.assertFalse(result.ok); self.assertFalse(result.order_ok)

    def test_nonnullable_null_fails(self):
        df = good_frame(); df.loc[0,"Documento"] = None
        result = validate_pr04_base(df, structure_rows=structure_rows())
        self.assertEqual(result.status, "FAIL_NULLABILITY")
        self.assertEqual(result.null_violations, {"Documento":1})

    def test_nullable_null_is_allowed(self):
        df = good_frame(); df.loc[0,"Fecha"] = None
        result = validate_pr04_base(df, structure_rows=structure_rows())
        self.assertTrue(result.ok)

    def test_numeric_validation_does_not_coerce_dataframe(self):
        df = good_frame(); dtype_before = df["Valor"].dtype
        result = validate_pr04_base(df, structure_rows=structure_rows())
        self.assertTrue(result.ok); self.assertEqual(df["Valor"].dtype, dtype_before)

    def test_invalid_numeric_fails_type(self):
        df = good_frame(); df.loc[0,"Valor"] = "not-number"
        result = validate_pr04_base(df, structure_rows=structure_rows())
        self.assertEqual(result.status, "FAIL_TYPE"); self.assertEqual(result.type_violations, {"Valor":1})

    def test_invalid_date_fails_type(self):
        df = good_frame(); df.loc[0,"Fecha"] = "not-date"
        result = validate_pr04_base(df, structure_rows=structure_rows())
        self.assertEqual(result.status, "FAIL_TYPE"); self.assertEqual(result.type_violations, {"Fecha":1})

    def test_contract_size_is_config_driven(self):
        rows = structure_rows()[:2]
        df = good_frame().loc[:, ["Documento","Valor"]]
        result = validate_pr04_base(df, structure_rows=rows)
        self.assertTrue(result.ok); self.assertEqual(len(result.contract.columns), 2)

    def test_rejects_non_dataframe(self):
        with self.assertRaises(TypeError):
            validate_pr04_base([], structure_rows=structure_rows())


if __name__ == "__main__":
    unittest.main()
