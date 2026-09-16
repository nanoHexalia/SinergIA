import unittest
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pandas as pd

from candidate.pr04_pagos_binding import (
    PR04PagosBindingError,
    bind_pagos_to_credit_base,
)


def _row(file_name, order, name, alias, data_type, required="No", nullable="Si"):
    return {
        "Sistema": "SinergIA",
        "ArchivoLogico": file_name,
        "ColumnaOrden": str(order),
        "NombreColumna": name,
        "AliasCanonico": alias,
        "TipoDato": data_type,
        "Obligatoria": required,
        "PermiteNulos": nullable,
    }


def structure_rows(include_payment_document=True):
    rows = [
        _row("IN_SISTECREDITO", 1, "Documento de identidad", "DocumentoDeIdentidad", "Texto", "Si", "No"),
        _row("IN_SISTECREDITO", 2, "Crédito", "Credito", "Texto", "Si", "No"),
        _row("PAGOS_ORIGINAL", 1, "fecha2", "FechaPago", "Fecha", "Si", "Si"),
        _row("PAGOS_ORIGINAL", 2, "CreditoCodigo", "Credito", "Texto", "Si", "No"),
        _row("PAGOS_ORIGINAL", 3, "ValorRecibo", "ValorRecibo", "Numero", "Si", "Si"),
    ]
    if include_payment_document:
        rows.append(
            _row("PAGOS_ORIGINAL", 4, "CC", "DocumentoDeIdentidad", "Texto", "No", "Si")
        )
    return rows


def base_frame():
    return pd.DataFrame({
        "Documento de identidad": ["A", "B", "C"],
        "Crédito": ["CR-1", "CR-2", "CR-3"],
    })


def payments_frame():
    return pd.DataFrame({
        "fecha2": [pd.Timestamp("2026-09-14"), pd.Timestamp("2026-09-16"), None],
        "CreditoCodigo": ["CR-1", "CR-1", "CR-2"],
        "ValorRecibo": [100, 50, None],
        "CC": ["A", "A", "B"],
    })


class PR04PagosBindingTests(unittest.TestCase):
    def test_aggregates_payment_facts_by_resolved_base_key(self):
        aggregates, evidence = bind_pagos_to_credit_base(
            base_frame(), payments_frame(), structure_rows=structure_rows(),
        )
        self.assertEqual(len(aggregates), 2)
        first = aggregates[0]
        self.assertEqual((first.document, first.credit), ("A", "CR-1"))
        self.assertEqual(first.payment_count, 2)
        self.assertEqual(first.last_payment_date, pd.Timestamp("2026-09-16"))
        self.assertEqual(first.total_paid, 150)
        second = aggregates[1]
        self.assertEqual((second.document, second.credit), ("B", "CR-2"))
        self.assertEqual(second.payment_count, 1)
        self.assertIsNone(second.last_payment_date)
        self.assertIsNone(second.total_paid)
        self.assertEqual(evidence.payment_rows_in, 3)
        self.assertEqual(evidence.payment_rows_bound, 3)
        self.assertEqual(evidence.payment_rows_unmatched, 0)
        self.assertEqual(evidence.aggregated_credit_keys, 2)

    def test_unmatched_credit_is_recorded_and_excluded(self):
        pagos = payments_frame().iloc[[0]].copy()
        pagos.loc[pagos.index[0], "CreditoCodigo"] = "CR-X"
        pagos.loc[pagos.index[0], "CC"] = "X"
        aggregates, evidence = bind_pagos_to_credit_base(
            base_frame(), pagos, structure_rows=structure_rows(),
        )
        self.assertEqual(aggregates, ())
        self.assertEqual(evidence.payment_rows_unmatched, 1)
        self.assertEqual(evidence.unmatched_credits, ("CR-X",))
        self.assertEqual(evidence.unmatched_row_positions, (0,))

    def test_duplicate_base_document_credit_key_is_fail_closed(self):
        base = pd.concat([base_frame(), base_frame().iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(PR04PagosBindingError, "duplicate IN_SISTECREDITO key"):
            bind_pagos_to_credit_base(base, payments_frame(), structure_rows=structure_rows())

    def test_shared_credit_without_payment_document_is_ambiguous(self):
        base = pd.DataFrame({
            "Documento de identidad": ["A", "B"],
            "Crédito": ["CR-X", "CR-X"],
        })
        pagos = pd.DataFrame({
            "fecha2": [pd.Timestamp("2026-09-16")],
            "CreditoCodigo": ["CR-X"],
            "ValorRecibo": [100],
        })
        with self.assertRaisesRegex(PR04PagosBindingError, "ambiguous payment binding"):
            bind_pagos_to_credit_base(
                base,
                pagos,
                structure_rows=structure_rows(include_payment_document=False),
            )

    def test_document_disambiguates_shared_credit_exactly(self):
        base = pd.DataFrame({
            "Documento de identidad": ["A", "B"],
            "Crédito": ["CR-X", "CR-X"],
        })
        pagos = pd.DataFrame({
            "fecha2": [pd.Timestamp("2026-09-15"), pd.Timestamp("2026-09-16")],
            "CreditoCodigo": ["CR-X", "CR-X"],
            "ValorRecibo": [100, 200],
            "CC": ["B", "A"],
        })
        aggregates, evidence = bind_pagos_to_credit_base(
            base, pagos, structure_rows=structure_rows(),
        )
        self.assertEqual([(a.document, a.credit) for a in aggregates], [("A", "CR-X"), ("B", "CR-X")])
        self.assertEqual([a.total_paid for a in aggregates], [200, 100])
        self.assertEqual(evidence.payment_rows_bound, 2)

    def test_payment_document_contradiction_is_fail_closed(self):
        pagos = payments_frame().iloc[[0]].copy()
        pagos.loc[pagos.index[0], "CC"] = "B"
        with self.assertRaisesRegex(PR04PagosBindingError, "contradicts its Credito binding"):
            bind_pagos_to_credit_base(
                base_frame(), pagos, structure_rows=structure_rows(),
            )

    def test_blank_optional_document_behaves_as_absent_for_unique_credit(self):
        pagos = payments_frame().iloc[[0]].copy()
        pagos.loc[pagos.index[0], "CC"] = "   "
        aggregates, evidence = bind_pagos_to_credit_base(
            base_frame(), pagos, structure_rows=structure_rows(),
        )
        self.assertEqual([(a.document, a.credit) for a in aggregates], [("A", "CR-1")])
        self.assertEqual(evidence.payment_rows_bound, 1)

    def test_case_difference_does_not_fuzzy_match_credit(self):
        pagos = payments_frame().iloc[[0]].copy()
        pagos.loc[pagos.index[0], "CreditoCodigo"] = "cr-1"
        aggregates, evidence = bind_pagos_to_credit_base(
            base_frame(), pagos, structure_rows=structure_rows(),
        )
        self.assertEqual(aggregates, ())
        self.assertEqual(evidence.unmatched_credits, ("cr-1",))

    def test_empty_payments_returns_empty_immutable_result(self):
        pagos = payments_frame().iloc[0:0].copy()
        aggregates, evidence = bind_pagos_to_credit_base(
            base_frame(), pagos, structure_rows=structure_rows(),
        )
        self.assertEqual(aggregates, ())
        self.assertEqual(evidence.payment_rows_in, 0)
        self.assertEqual(evidence.payment_rows_bound, 0)
        self.assertEqual(evidence.payment_rows_unmatched, 0)

    def test_inputs_and_config_rows_are_not_mutated(self):
        base = base_frame()
        pagos = payments_frame()
        rows = structure_rows()
        base_before = base.copy(deep=True)
        pagos_before = pagos.copy(deep=True)
        rows_before = deepcopy(rows)
        bind_pagos_to_credit_base(base, pagos, structure_rows=rows)
        pd.testing.assert_frame_equal(base, base_before)
        pd.testing.assert_frame_equal(pagos, pagos_before)
        self.assertEqual(rows, rows_before)

    def test_aggregate_and_evidence_are_frozen(self):
        aggregates, evidence = bind_pagos_to_credit_base(
            base_frame(), payments_frame(), structure_rows=structure_rows(),
        )
        with self.assertRaises(FrozenInstanceError):
            aggregates[0].payment_count = 99
        with self.assertRaises(FrozenInstanceError):
            evidence.payment_rows_bound = 99

    def test_invalid_base_boundary_is_fail_closed(self):
        base = base_frame().loc[:, ["Crédito", "Documento de identidad"]]
        with self.assertRaisesRegex(PR04PagosBindingError, "IN_SISTECREDITO boundary invalid"):
            bind_pagos_to_credit_base(base, payments_frame(), structure_rows=structure_rows())

    def test_duplicate_payment_fact_remains_fail_closed_from_029(self):
        pagos = pd.concat([payments_frame().iloc[[0]], payments_frame().iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "ambiguous duplicate payment facts"):
            bind_pagos_to_credit_base(base_frame(), pagos, structure_rows=structure_rows())


if __name__ == "__main__":
    unittest.main()
