import unittest
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pandas as pd

from candidate.pr04_promesas import PR04PromesasError
from candidate.pr04_promesas_binding import (
    PR04PromesasBindingError,
    bind_promesas_to_credit_base,
)


def _row(file_name, order, name, alias, data_type, required="Si", nullable="No"):
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


def structure_rows():
    return [
        _row("IN_SISTECREDITO", 1, "Documento de identidad", "DocumentoDeIdentidad", "Texto"),
        _row("IN_SISTECREDITO", 2, "Crédito", "Credito", "Texto"),
        _row("PROMESAS_ORIGINAL", 1, "CEDULA", "DocumentoDeIdentidad", "Texto"),
        _row("PROMESAS_ORIGINAL", 2, "CREDITO", "Credito", "Texto"),
        _row("PROMESAS_ORIGINAL", 3, "FECH_PROM", "FechaPromesa", "Fecha"),
        _row("PROMESAS_ORIGINAL", 4, "VALOR_CUOTA", "ValorPromesa", "Numero"),
        _row("PROMESAS_ORIGINAL", 5, "STATUS PROMESA", "EstadoPromesa", "Texto"),
    ]


def base_frame():
    return pd.DataFrame({
        "Documento de identidad": ["DOC-1", "DOC-2", "DOC-3"],
        "Crédito": ["CR-1", "CR-2", "CR-3"],
    })


def promises_frame():
    return pd.DataFrame({
        "CEDULA": ["DOC-1", "DOC-1", "DOC-2"],
        "CREDITO": ["CR-1", "CR-1", "CR-2"],
        "FECH_PROM": [
            pd.Timestamp("2026-09-20"),
            pd.Timestamp("2026-09-25"),
            pd.Timestamp("2026-09-22"),
        ],
        "VALOR_CUOTA": [1000, 500, 750],
        "STATUS PROMESA": ["VIGENTE", "NUEVA", "OTRO ESTADO FUENTE"],
    })


class PR04PromesasBindingTests(unittest.TestCase):
    def test_binds_every_event_to_its_exact_base_key_in_source_order(self):
        records, evidence = bind_promesas_to_credit_base(
            base_frame(), promises_frame(), structure_rows=structure_rows(),
        )
        self.assertEqual(
            [(record.document, record.credit) for record in records],
            [("DOC-1", "CR-1"), ("DOC-1", "CR-1"), ("DOC-2", "CR-2")],
        )
        self.assertEqual([record.source_row_position for record in records], [0, 1, 2])
        first, second, third = records
        self.assertEqual(first.promise_date, pd.Timestamp("2026-09-20"))
        self.assertEqual(first.promise_value, 1000)
        self.assertEqual(first.promise_status, "VIGENTE")
        self.assertEqual(second.promise_date, pd.Timestamp("2026-09-25"))
        self.assertEqual(second.promise_value, 500)
        self.assertEqual(second.promise_status, "NUEVA")
        self.assertEqual(third.promise_date, pd.Timestamp("2026-09-22"))
        self.assertEqual(third.promise_value, 750)
        self.assertEqual(third.promise_status, "OTRO ESTADO FUENTE")
        self.assertEqual(evidence.promise_rows_in, 3)
        self.assertEqual(evidence.promise_rows_bound, 3)
        self.assertEqual(evidence.promise_rows_unmatched, 0)
        self.assertEqual(evidence.bound_credit_keys, 2)
        self.assertEqual(evidence.unmatched_credits, ())
        self.assertEqual(evidence.unmatched_row_positions, ())

    def test_repeated_and_identical_events_are_preserved_without_deduplication(self):
        frame = pd.concat(
            [promises_frame().iloc[[0]], promises_frame().iloc[[0]]],
            ignore_index=True,
        )
        records, evidence = bind_promesas_to_credit_base(
            base_frame(), frame, structure_rows=structure_rows(),
        )
        self.assertEqual(len(records), 2)
        self.assertEqual([record.source_row_position for record in records], [0, 1])
        self.assertEqual(
            [
                (record.document, record.credit, record.promise_date,
                 record.promise_value, record.promise_status)
                for record in records
            ],
            [
                ("DOC-1", "CR-1", pd.Timestamp("2026-09-20"), 1000, "VIGENTE"),
                ("DOC-1", "CR-1", pd.Timestamp("2026-09-20"), 1000, "VIGENTE"),
            ],
        )
        self.assertEqual(evidence.promise_rows_in, 2)
        self.assertEqual(evidence.promise_rows_bound, 2)
        self.assertEqual(evidence.bound_credit_keys, 1)
        self.assertEqual(evidence.promise_rows_unmatched, 0)

    def test_empty_source_yields_empty_immutable_result(self):
        records, evidence = bind_promesas_to_credit_base(
            base_frame(), promises_frame().iloc[0:0].copy(), structure_rows=structure_rows(),
        )
        self.assertEqual(records, ())
        self.assertEqual(evidence.promise_rows_in, 0)
        self.assertEqual(evidence.promise_rows_bound, 0)
        self.assertEqual(evidence.promise_rows_unmatched, 0)
        self.assertEqual(evidence.bound_credit_keys, 0)
        self.assertEqual(evidence.unmatched_credits, ())
        self.assertEqual(evidence.unmatched_row_positions, ())

    def test_unmatched_credit_is_recorded_and_not_bound(self):
        frame = promises_frame().copy()
        frame.loc[frame.index[2], "CREDITO"] = "CR-9"
        records, evidence = bind_promesas_to_credit_base(
            base_frame(), frame, structure_rows=structure_rows(),
        )
        self.assertEqual(
            [(record.document, record.credit) for record in records],
            [("DOC-1", "CR-1"), ("DOC-1", "CR-1")],
        )
        self.assertEqual(evidence.promise_rows_bound, 2)
        self.assertEqual(evidence.promise_rows_unmatched, 1)
        self.assertEqual(evidence.unmatched_credits, ("CR-9",))
        self.assertEqual(evidence.unmatched_row_positions, (2,))

    def test_empty_base_leaves_every_event_unmatched(self):
        records, evidence = bind_promesas_to_credit_base(
            base_frame().iloc[0:0].copy(), promises_frame(), structure_rows=structure_rows(),
        )
        self.assertEqual(records, ())
        self.assertEqual(evidence.promise_rows_unmatched, 3)
        self.assertEqual(evidence.unmatched_credits, ("CR-1", "CR-2"))
        self.assertEqual(evidence.unmatched_row_positions, (0, 1, 2))

    def test_credit_case_difference_is_unmatched_not_fuzzy_match(self):
        frame = promises_frame().iloc[[0]].copy()
        frame.loc[frame.index[0], "CREDITO"] = "cr-1"
        records, evidence = bind_promesas_to_credit_base(
            base_frame(), frame, structure_rows=structure_rows(),
        )
        self.assertEqual(records, ())
        self.assertEqual(evidence.unmatched_credits, ("cr-1",))
        self.assertEqual(evidence.unmatched_row_positions, (0,))

    def test_credit_owned_by_another_document_is_fail_closed_contradiction(self):
        frame = promises_frame().iloc[[2]].copy()
        frame.loc[frame.index[0], "CREDITO"] = "CR-1"
        with self.assertRaisesRegex(PR04PromesasBindingError, "contradicts its Credito binding"):
            bind_promesas_to_credit_base(
                base_frame(), frame, structure_rows=structure_rows(),
            )

    def test_document_case_difference_is_contradiction_not_fuzzy_match(self):
        frame = promises_frame().iloc[[0]].copy()
        frame.loc[frame.index[0], "CEDULA"] = "doc-1"
        with self.assertRaisesRegex(PR04PromesasBindingError, "contradicts its Credito binding"):
            bind_promesas_to_credit_base(
                base_frame(), frame, structure_rows=structure_rows(),
            )

    def test_document_disambiguates_shared_credit_exactly(self):
        base = pd.DataFrame({
            "Documento de identidad": ["DOC-1", "DOC-2"],
            "Crédito": ["CR-X", "CR-X"],
        })
        frame = pd.DataFrame({
            "CEDULA": ["DOC-2", "DOC-1", "DOC-2"],
            "CREDITO": ["CR-X", "CR-X", "CR-X"],
            "FECH_PROM": [
                pd.Timestamp("2026-09-20"),
                pd.Timestamp("2026-09-21"),
                pd.Timestamp("2026-09-22"),
            ],
            "VALOR_CUOTA": [100, 200, 300],
            "STATUS PROMESA": ["VIGENTE", "NUEVA", "VIGENTE"],
        })
        records, evidence = bind_promesas_to_credit_base(
            base, frame, structure_rows=structure_rows(),
        )
        self.assertEqual(
            [(record.document, record.credit, record.source_row_position)
             for record in records],
            [("DOC-2", "CR-X", 0), ("DOC-1", "CR-X", 1), ("DOC-2", "CR-X", 2)],
        )
        self.assertEqual(evidence.promise_rows_bound, 3)
        self.assertEqual(evidence.bound_credit_keys, 2)
        self.assertEqual(evidence.promise_rows_unmatched, 0)

    def test_duplicate_base_document_credit_key_is_fail_closed(self):
        base = pd.concat([base_frame(), base_frame().iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(PR04PromesasBindingError, "duplicate IN_SISTECREDITO key"):
            bind_promesas_to_credit_base(
                base, promises_frame(), structure_rows=structure_rows(),
            )

    def test_blank_base_key_is_fail_closed(self):
        base = base_frame().copy()
        base.loc[base.index[0], "Documento de identidad"] = "   "
        with self.assertRaisesRegex(PR04PromesasBindingError, "non-blank text key"):
            bind_promesas_to_credit_base(
                base, promises_frame(), structure_rows=structure_rows(),
            )

    def test_records_and_evidence_are_frozen(self):
        records, evidence = bind_promesas_to_credit_base(
            base_frame(), promises_frame(), structure_rows=structure_rows(),
        )
        with self.assertRaises(FrozenInstanceError):
            records[0].document = "X"
        with self.assertRaises(FrozenInstanceError):
            evidence.promise_rows_bound = 99

    def test_inputs_and_config_rows_are_not_mutated(self):
        base = base_frame()
        promesas = promises_frame()
        rows = structure_rows()
        base_before = base.copy(deep=True)
        promesas_before = promesas.copy(deep=True)
        rows_before = deepcopy(rows)
        bind_promesas_to_credit_base(base, promesas, structure_rows=rows)
        pd.testing.assert_frame_equal(base, base_before)
        pd.testing.assert_frame_equal(promesas, promesas_before)
        self.assertEqual(rows, rows_before)

    def test_promesas_boundary_failure_propagates_unchanged(self):
        frame = promises_frame().loc[:, [
            "CREDITO", "CEDULA", "FECH_PROM", "VALOR_CUOTA", "STATUS PROMESA",
        ]]
        with self.assertRaisesRegex(PR04PromesasError, "FAIL_SCHEMA"):
            bind_promesas_to_credit_base(
                base_frame(), frame, structure_rows=structure_rows(),
            )

    def test_base_boundary_failure_is_fail_closed(self):
        base = base_frame().loc[:, ["Crédito", "Documento de identidad"]]
        with self.assertRaisesRegex(
            PR04PromesasBindingError, "IN_SISTECREDITO boundary invalid",
        ):
            bind_promesas_to_credit_base(
                base, promises_frame(), structure_rows=structure_rows(),
            )

    def test_missing_promesas_contract_propagates_fail_closed(self):
        rows = structure_rows()
        for row in rows:
            if row["ArchivoLogico"] == "PROMESAS_ORIGINAL":
                row["ArchivoLogico"] = "OTHER"
        with self.assertRaisesRegex(ValueError, "contract not found"):
            bind_promesas_to_credit_base(
                base_frame(), promises_frame(), structure_rows=rows,
            )

    def test_non_dataframe_inputs_propagate_boundary_type_errors(self):
        with self.assertRaises(TypeError):
            bind_promesas_to_credit_base(
                "not-a-frame", promises_frame(), structure_rows=structure_rows(),
            )
        with self.assertRaises(TypeError):
            bind_promesas_to_credit_base(
                base_frame(), [], structure_rows=structure_rows(),
            )


if __name__ == "__main__":
    unittest.main()
