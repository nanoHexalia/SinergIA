import unittest
from copy import deepcopy

import pandas as pd

from candidate.pr04_pagos import PR04PagosError, prepare_pagos_original


def _row(order, name, alias, data_type, required="No", nullable="Si"):
    return {
        "Sistema": "SinergIA",
        "ArchivoLogico": "PAGOS_ORIGINAL",
        "ColumnaOrden": str(order),
        "NombreColumna": name,
        "AliasCanonico": alias,
        "TipoDato": data_type,
        "Obligatoria": required,
        "PermiteNulos": nullable,
    }


def structure_rows():
    return [
        _row(1, "fecha2", "FechaPago", "Fecha", "Si", "Si"),
        _row(2, "CreditoCodigo", "Credito", "Texto", "Si", "No"),
        _row(3, "NombreCompleto", "NombreCompleto", "Texto", "No", "Si"),
        _row(4, "ValorRecibo", "ValorRecibo", "Numero", "Si", "Si"),
    ]


def payments_frame():
    return pd.DataFrame({
        "fecha2": [pd.Timestamp("2026-09-15"), pd.Timestamp("2026-09-16"), None],
        "CreditoCodigo": ["CR-1", "CR-1", "CR-2"],
        "NombreCompleto": ["A", "A", "B"],
        "ValorRecibo": [1000, 500, None],
    })


class PR04PagosTests(unittest.TestCase):
    def test_prepares_exact_payment_facts_without_mutating_input(self):
        frame = payments_frame()
        before = frame.copy(deep=True)
        rows = structure_rows()
        rows_before = deepcopy(rows)

        facts, evidence = prepare_pagos_original(frame, structure_rows=rows)

        self.assertEqual(list(facts.columns), ["CreditoCodigo", "fecha2", "ValorRecibo"])
        self.assertEqual(len(facts), 3)
        self.assertEqual(evidence.rows_in, 3)
        self.assertEqual(evidence.unique_credits, 2)
        self.assertEqual(evidence.null_dates, 1)
        self.assertEqual(evidence.null_values, 1)
        pd.testing.assert_frame_equal(frame, before)
        self.assertEqual(rows, rows_before)

    def test_schema_reorder_is_fail_closed(self):
        frame = payments_frame().loc[:, [
            "CreditoCodigo", "fecha2", "NombreCompleto", "ValorRecibo",
        ]]
        with self.assertRaisesRegex(PR04PagosError, "FAIL_SCHEMA"):
            prepare_pagos_original(frame, structure_rows=structure_rows())

    def test_missing_or_extra_column_is_fail_closed(self):
        missing = payments_frame().drop(columns=["NombreCompleto"])
        extra = payments_frame().assign(Extra="x")
        for frame in (missing, extra):
            with self.subTest(columns=list(frame.columns)):
                with self.assertRaisesRegex(PR04PagosError, "FAIL_SCHEMA"):
                    prepare_pagos_original(frame, structure_rows=structure_rows())

    def test_null_credit_is_fail_closed_by_config_nullability(self):
        frame = payments_frame()
        frame.loc[0, "CreditoCodigo"] = None
        with self.assertRaisesRegex(PR04PagosError, "FAIL_NULLABILITY"):
            prepare_pagos_original(frame, structure_rows=structure_rows())

    def test_blank_credit_is_fail_closed(self):
        frame = payments_frame()
        frame.loc[0, "CreditoCodigo"] = "   "
        with self.assertRaisesRegex(PR04PagosError, "blank/non-text credit"):
            prepare_pagos_original(frame, structure_rows=structure_rows())

    def test_negative_payment_value_is_fail_closed(self):
        frame = payments_frame()
        frame.loc[0, "ValorRecibo"] = -1
        with self.assertRaisesRegex(PR04PagosError, "ValorRecibo must be >= 0"):
            prepare_pagos_original(frame, structure_rows=structure_rows())

    def test_boolean_payment_value_is_fail_closed_by_type_contract(self):
        frame = payments_frame()
        frame["ValorRecibo"] = frame["ValorRecibo"].astype(object)
        frame.loc[0, "ValorRecibo"] = True
        with self.assertRaisesRegex(PR04PagosError, "FAIL_TYPE"):
            prepare_pagos_original(frame, structure_rows=structure_rows())

    def test_invalid_payment_date_is_fail_closed_by_type_contract(self):
        frame = payments_frame()
        frame["fecha2"] = frame["fecha2"].astype(object)
        frame.loc[0, "fecha2"] = "not-a-date"
        with self.assertRaisesRegex(PR04PagosError, "FAIL_TYPE"):
            prepare_pagos_original(frame, structure_rows=structure_rows())

    def test_config_nullable_date_and_value_are_preserved(self):
        facts, evidence = prepare_pagos_original(
            payments_frame(), structure_rows=structure_rows()
        )
        self.assertTrue(pd.isna(facts.loc[2, "fecha2"]))
        self.assertTrue(pd.isna(facts.loc[2, "ValorRecibo"]))
        self.assertEqual(evidence.null_dates, 1)
        self.assertEqual(evidence.null_values, 1)

    def test_exact_duplicate_payment_fact_is_fail_closed(self):
        frame = pd.concat([payments_frame(), payments_frame().iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(PR04PagosError, "ambiguous duplicate payment facts"):
            prepare_pagos_original(frame, structure_rows=structure_rows())

    def test_same_credit_and_date_with_different_value_is_not_ambiguous(self):
        frame = payments_frame().iloc[:2].copy()
        frame.loc[1, "fecha2"] = frame.loc[0, "fecha2"]
        facts, evidence = prepare_pagos_original(frame, structure_rows=structure_rows())
        self.assertEqual(len(facts), 2)
        self.assertEqual(evidence.unique_credits, 1)

    def test_missing_pagos_contract_is_fail_closed(self):
        rows = structure_rows()
        for row in rows:
            row["ArchivoLogico"] = "OTHER"
        with self.assertRaisesRegex(ValueError, "contract not found"):
            prepare_pagos_original(payments_frame(), structure_rows=rows)

    def test_canonical_binding_must_be_exact(self):
        rows = structure_rows()
        rows[1]["AliasCanonico"] = "credito"
        with self.assertRaisesRegex(ValueError, "dataset column token must resolve exactly once"):
            prepare_pagos_original(payments_frame(), structure_rows=rows)

    def test_non_dataframe_is_rejected(self):
        with self.assertRaises(TypeError):
            prepare_pagos_original([], structure_rows=structure_rows())


if __name__ == "__main__":
    unittest.main()
