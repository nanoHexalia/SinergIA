import unittest
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pandas as pd

from candidate.pr04_promesas import (
    PR04PromesasError,
    prepare_promesas_original,
)


def _row(order, name, alias, data_type, required="Si", nullable="No"):
    return {
        "Sistema": "SinergIA",
        "ArchivoLogico": "PROMESAS_ORIGINAL",
        "ColumnaOrden": str(order),
        "NombreColumna": name,
        "AliasCanonico": alias,
        "TipoDato": data_type,
        "Obligatoria": required,
        "PermiteNulos": nullable,
    }


def structure_rows():
    return [
        _row(1, "CEDULA", "DocumentoDeIdentidad", "Texto"),
        _row(2, "CREDITO", "Credito", "Texto"),
        _row(3, "FECH_PROM", "FechaPromesa", "Fecha"),
        _row(4, "VALOR_CUOTA", "ValorPromesa", "Numero"),
        _row(5, "STATUS PROMESA", "EstadoPromesa", "Texto"),
    ]


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


class PR04PromesasTests(unittest.TestCase):
    def test_prepares_exact_promise_facts_without_mutating_inputs(self):
        frame = promises_frame()
        before = frame.copy(deep=True)
        rows = structure_rows()
        rows_before = deepcopy(rows)

        facts, evidence = prepare_promesas_original(frame, structure_rows=rows)

        self.assertEqual(
            list(facts.columns),
            ["CEDULA", "CREDITO", "FECH_PROM", "VALOR_CUOTA", "STATUS PROMESA"],
        )
        self.assertEqual(evidence.rows_in, 3)
        self.assertEqual(evidence.rows_out, 3)
        self.assertEqual(evidence.unique_documents, 2)
        self.assertEqual(evidence.unique_credits, 2)
        self.assertEqual(evidence.unique_document_credit_pairs, 2)
        pd.testing.assert_frame_equal(facts, frame)
        pd.testing.assert_frame_equal(frame, before)
        self.assertEqual(rows, rows_before)

    def test_schema_reorder_is_fail_closed(self):
        frame = promises_frame().loc[:, [
            "CREDITO", "CEDULA", "FECH_PROM", "VALOR_CUOTA", "STATUS PROMESA",
        ]]
        with self.assertRaisesRegex(PR04PromesasError, "FAIL_SCHEMA"):
            prepare_promesas_original(frame, structure_rows=structure_rows())

    def test_missing_or_extra_column_is_fail_closed(self):
        missing = promises_frame().drop(columns=["STATUS PROMESA"])
        extra = promises_frame().assign(Extra="x")
        for frame in (missing, extra):
            with self.subTest(columns=list(frame.columns)):
                with self.assertRaisesRegex(PR04PromesasError, "FAIL_SCHEMA"):
                    prepare_promesas_original(frame, structure_rows=structure_rows())

    def test_null_governed_fields_fail_closed_by_config(self):
        for column in (
            "CEDULA", "CREDITO", "FECH_PROM", "VALOR_CUOTA", "STATUS PROMESA",
        ):
            frame = promises_frame()
            frame.loc[0, column] = None
            with self.subTest(column=column):
                with self.assertRaisesRegex(PR04PromesasError, "FAIL_NULLABILITY"):
                    prepare_promesas_original(frame, structure_rows=structure_rows())

    def test_blank_document_is_fail_closed(self):
        frame = promises_frame()
        frame.loc[0, "CEDULA"] = "   "
        with self.assertRaisesRegex(PR04PromesasError, "blank/non-text document"):
            prepare_promesas_original(frame, structure_rows=structure_rows())

    def test_blank_credit_is_fail_closed(self):
        frame = promises_frame()
        frame.loc[0, "CREDITO"] = ""
        with self.assertRaisesRegex(PR04PromesasError, "blank/non-text credit"):
            prepare_promesas_original(frame, structure_rows=structure_rows())

    def test_blank_status_is_fail_closed_without_inventing_status_enum(self):
        frame = promises_frame()
        frame.loc[0, "STATUS PROMESA"] = "   "
        with self.assertRaisesRegex(PR04PromesasError, "blank/non-text promise status"):
            prepare_promesas_original(frame, structure_rows=structure_rows())

    def test_arbitrary_nonblank_source_status_is_preserved(self):
        frame = promises_frame().iloc[[0]].copy()
        frame.loc[frame.index[0], "STATUS PROMESA"] = "ESTADO_FISICO_NO_ENUMERADO"
        facts, _ = prepare_promesas_original(frame, structure_rows=structure_rows())
        self.assertEqual(facts.iloc[0]["STATUS PROMESA"], "ESTADO_FISICO_NO_ENUMERADO")

    def test_negative_promise_value_is_fail_closed(self):
        frame = promises_frame()
        frame.loc[0, "VALOR_CUOTA"] = -1
        with self.assertRaisesRegex(PR04PromesasError, "ValorPromesa must be >= 0"):
            prepare_promesas_original(frame, structure_rows=structure_rows())

    def test_boolean_promise_value_is_fail_closed_by_type_contract(self):
        frame = promises_frame()
        frame["VALOR_CUOTA"] = frame["VALOR_CUOTA"].astype(object)
        frame.loc[0, "VALOR_CUOTA"] = True
        with self.assertRaisesRegex(PR04PromesasError, "FAIL_TYPE"):
            prepare_promesas_original(frame, structure_rows=structure_rows())

    def test_invalid_promise_date_is_fail_closed_by_type_contract(self):
        frame = promises_frame()
        frame["FECH_PROM"] = frame["FECH_PROM"].astype(object)
        frame.loc[0, "FECH_PROM"] = "not-a-date"
        with self.assertRaisesRegex(PR04PromesasError, "FAIL_TYPE"):
            prepare_promesas_original(frame, structure_rows=structure_rows())

    def test_multiple_events_for_same_document_credit_are_preserved(self):
        facts, evidence = prepare_promesas_original(
            promises_frame(), structure_rows=structure_rows()
        )
        self.assertEqual(len(facts[facts["CREDITO"] == "CR-1"]), 2)
        self.assertEqual(evidence.unique_document_credit_pairs, 2)

    def test_identical_source_events_are_preserved_without_inferred_event_key(self):
        frame = pd.concat(
            [promises_frame().iloc[[0]], promises_frame().iloc[[0]]],
            ignore_index=True,
        )
        facts, evidence = prepare_promesas_original(frame, structure_rows=structure_rows())
        self.assertEqual(len(facts), 2)
        self.assertEqual(evidence.rows_in, 2)
        self.assertEqual(evidence.rows_out, 2)
        self.assertEqual(evidence.unique_document_credit_pairs, 1)

    def test_empty_source_is_valid_and_produces_empty_facts(self):
        frame = promises_frame().iloc[0:0].copy()
        facts, evidence = prepare_promesas_original(frame, structure_rows=structure_rows())
        self.assertTrue(facts.empty)
        self.assertEqual(evidence.rows_in, 0)
        self.assertEqual(evidence.rows_out, 0)
        self.assertEqual(evidence.unique_documents, 0)
        self.assertEqual(evidence.unique_credits, 0)
        self.assertEqual(evidence.unique_document_credit_pairs, 0)

    def test_missing_promesas_contract_is_fail_closed(self):
        rows = structure_rows()
        for row in rows:
            row["ArchivoLogico"] = "OTHER"
        with self.assertRaisesRegex(ValueError, "contract not found"):
            prepare_promesas_original(promises_frame(), structure_rows=rows)

    def test_canonical_binding_must_be_exact(self):
        rows = structure_rows()
        rows[0]["AliasCanonico"] = "documentodeidentidad"
        with self.assertRaisesRegex(
            ValueError, "dataset column token must resolve exactly once"
        ):
            prepare_promesas_original(promises_frame(), structure_rows=rows)

    def test_evidence_is_frozen(self):
        _, evidence = prepare_promesas_original(
            promises_frame(), structure_rows=structure_rows()
        )
        with self.assertRaises(FrozenInstanceError):
            evidence.rows_out = 99

    def test_non_dataframe_is_rejected(self):
        with self.assertRaises(TypeError):
            prepare_promesas_original([], structure_rows=structure_rows())


if __name__ == "__main__":
    unittest.main()
