import unittest
from copy import deepcopy

import pandas as pd

from candidate.config_contract import (
    resolve_dataset_column,
    resolve_dataset_contract,
)
from candidate.pr04_mejorgest import (
    PR04MejorGestError,
    build_mejorgest_from_traza,
)


def _row(file_name, order, name, alias, data_type, required="No", nullable="Si"):
    return {
        "Sistema": "SinergIA", "ArchivoLogico": file_name,
        "ColumnaOrden": str(order), "NombreColumna": name,
        "AliasCanonico": alias, "TipoDato": data_type,
        "Obligatoria": required, "PermiteNulos": nullable,
    }


def structure_rows():
    return [
        _row("TRAZA", 1, "IN_DOCUMENTO_DE_IDENTIDAD", "InDocumentoDeIdentidad", "Texto", "Si", "No"),
        _row("TRAZA", 2, "CAP_FECHA", "CapFecha", "Fecha", "Si", "Si"),
        _row("TRAZA", 3, "CAP_TIPIFICACION", "CapTipificacion", "Texto", "No", "Si"),
        _row("IN_SISTECREDITO", 1, "Documento de identidad", "DocumentoDeIdentidad", "Texto", "Si", "No"),
        _row("IN_SISTECREDITO", 2, "Crédito", "Credito", "Texto", "Si", "No"),
        _row("CONSOLIDADO_MEJORGEST", 1, "Documento de identidad", "DocumentoDeIdentidad", "Texto", "Si", "No"),
        _row("CONSOLIDADO_MEJORGEST", 2, "Fecha Mes", "FechaMes", "Fecha", "Si", "No"),
        _row("CONSOLIDADO_MEJORGEST", 3, "Mín. de Prioridad", "MinPrioridad", "Numero", "Si", "No"),
        _row("CONSOLIDADO_MEJORGEST", 4, "Tipo Contacto", "TipoContacto", "Texto"),
        _row("CONSOLIDADO_MEJORGEST", 5, "Tipificacion", "Tipificacion", "Texto"),
        _row("CONSOLIDADO_MEJORGEST", 6, "BD", "Bd", "Texto"),
    ]


def arbol_rows():
    return [
        {"COD Tipi": "1", "Tipo Contacto": "Contacto Directo", "Tipificacion": "Pago Total", "Prioridad": 1},
        {"COD Tipi": "2", "Tipo Contacto": "Contacto Directo", "Tipificacion": "Pago Parcial", "Prioridad": 3},
        {"COD Tipi": "3", "Tipo Contacto": "No Contacto", "Tipificacion": "Sin Respuesta", "Prioridad": 63},
    ]


def base_frame():
    return pd.DataFrame({
        "Documento de identidad": ["A", "B"],
        "Crédito": ["CRED-A", "CRED-B"],
    })


def trace_frame():
    return pd.DataFrame({
        "IN_DOCUMENTO_DE_IDENTIDAD": ["A", "A", "A", "A", "C"],
        "CAP_FECHA": ["2026-09-01", "2026-09-02", "2026-09-03", "2026-10-01", "2026-09-04"],
        "CAP_TIPIFICACION": ["2", "1", "1", "2", "1"],
    })


class DatasetColumnResolutionTests(unittest.TestCase):
    def test_resolves_exact_physical_name_and_alias_only(self):
        contract = resolve_dataset_contract(structure_rows(), "TRAZA")
        self.assertEqual(
            resolve_dataset_column(contract, "CapFecha").name,
            "CAP_FECHA",
        )
        self.assertEqual(
            resolve_dataset_column(contract, "CAP_FECHA").alias,
            "CapFecha",
        )
        with self.assertRaises(ValueError):
            resolve_dataset_column(contract, "capfecha")


class PR04MejorGestTests(unittest.TestCase):
    def test_builds_exact_current_output_and_grain(self):
        out, evidence = build_mejorgest_from_traza(
            trace_frame(), base_frame(),
            structure_rows=structure_rows(), arbol_rows=arbol_rows(),
        )
        self.assertEqual(list(out.columns), [
            "Documento de identidad", "Fecha Mes", "Mín. de Prioridad",
            "Tipo Contacto", "Tipificacion", "BD",
        ])
        self.assertEqual(len(out), 3)
        self.assertEqual(evidence.rows_in, 5)
        self.assertEqual(evidence.rows_out, 3)
        self.assertEqual(evidence.documents, 2)
        a_sep = out[(out["Documento de identidad"] == "A") & (out["Fecha Mes"] == pd.Timestamp("2026-09-01"))].iloc[0]
        self.assertEqual(a_sep["Mín. de Prioridad"], 1.0)
        self.assertEqual(a_sep["Tipificacion"], "Pago Total")
        self.assertEqual(a_sep["BD"], "EnBD")
        c_sep = out[out["Documento de identidad"] == "C"].iloc[0]
        self.assertEqual(c_sep["BD"], "FueraBD")

    def test_lower_priority_wins_even_when_older(self):
        trace = pd.DataFrame({
            "IN_DOCUMENTO_DE_IDENTIDAD": ["A", "A"],
            "CAP_FECHA": ["2026-09-01", "2026-09-30"],
            "CAP_TIPIFICACION": ["1", "2"],
        })
        out, _ = build_mejorgest_from_traza(
            trace, base_frame(), structure_rows=structure_rows(), arbol_rows=arbol_rows(),
        )
        self.assertEqual(out.loc[0, "Tipificacion"], "Pago Total")
        self.assertEqual(out.loc[0, "Mín. de Prioridad"], 1.0)

    def test_equal_priority_uses_most_recent_cap_fecha(self):
        arbol = arbol_rows() + [
            {"COD Tipi": "4", "Tipo Contacto": "Contacto Directo", "Tipificacion": "Confirma Pago", "Prioridad": 1},
        ]
        trace = pd.DataFrame({
            "IN_DOCUMENTO_DE_IDENTIDAD": ["A", "A"],
            "CAP_FECHA": ["2026-09-01", "2026-09-30"],
            "CAP_TIPIFICACION": ["1", "4"],
        })
        out, _ = build_mejorgest_from_traza(
            trace, base_frame(), structure_rows=structure_rows(), arbol_rows=arbol,
        )
        self.assertEqual(out.loc[0, "Tipificacion"], "Confirma Pago")

    def test_same_priority_and_date_is_fail_closed_ambiguity(self):
        arbol = arbol_rows() + [
            {"COD Tipi": "4", "Tipo Contacto": "Contacto Directo", "Tipificacion": "Confirma Pago", "Prioridad": 1},
        ]
        trace = pd.DataFrame({
            "IN_DOCUMENTO_DE_IDENTIDAD": ["A", "A"],
            "CAP_FECHA": ["2026-09-30", "2026-09-30"],
            "CAP_TIPIFICACION": ["1", "4"],
        })
        with self.assertRaisesRegex(PR04MejorGestError, "ambiguous best management"):
            build_mejorgest_from_traza(
                trace, base_frame(), structure_rows=structure_rows(), arbol_rows=arbol,
            )

    def test_unmapped_tipification_is_fail_closed(self):
        trace = trace_frame().copy()
        trace.loc[0, "CAP_TIPIFICACION"] = "404"
        with self.assertRaisesRegex(PR04MejorGestError, "unmapped CAP_TIPIFICACION"):
            build_mejorgest_from_traza(
                trace, base_frame(), structure_rows=structure_rows(), arbol_rows=arbol_rows(),
            )

    def test_duplicate_arbol_code_is_fail_closed(self):
        arbol = arbol_rows() + [dict(arbol_rows()[0])]
        with self.assertRaisesRegex(PR04MejorGestError, "duplicate ArbolHeuristico COD Tipi"):
            build_mejorgest_from_traza(
                trace_frame(), base_frame(), structure_rows=structure_rows(), arbol_rows=arbol,
            )

    def test_invalid_or_null_cap_fecha_is_fail_closed(self):
        for bad_value in ("not-a-date", None):
            trace = trace_frame().copy()
            trace.loc[0, "CAP_FECHA"] = bad_value
            with self.subTest(value=bad_value):
                with self.assertRaisesRegex(PR04MejorGestError, "CAP_FECHA"):
                    build_mejorgest_from_traza(
                        trace, base_frame(), structure_rows=structure_rows(), arbol_rows=arbol_rows(),
                    )

    def test_schema_drift_is_fail_closed(self):
        trace = trace_frame().loc[:, [
            "CAP_FECHA", "IN_DOCUMENTO_DE_IDENTIDAD", "CAP_TIPIFICACION",
        ]]
        with self.assertRaisesRegex(PR04MejorGestError, "schema must exactly match"):
            build_mejorgest_from_traza(
                trace, base_frame(), structure_rows=structure_rows(), arbol_rows=arbol_rows(),
            )

    def test_empty_traza_returns_exact_empty_output_without_inventing_rows(self):
        trace = trace_frame().iloc[0:0].copy()
        out, evidence = build_mejorgest_from_traza(
            trace, base_frame(), structure_rows=structure_rows(), arbol_rows=[],
        )
        self.assertTrue(out.empty)
        self.assertEqual(list(out.columns), [
            "Documento de identidad", "Fecha Mes", "Mín. de Prioridad",
            "Tipo Contacto", "Tipificacion", "BD",
        ])
        self.assertEqual(evidence.rows_in, 0)
        self.assertEqual(evidence.rows_out, 0)

    def test_inputs_are_not_mutated(self):
        trace = trace_frame()
        base = base_frame()
        trace_before = trace.copy(deep=True)
        base_before = base.copy(deep=True)
        arbol = arbol_rows()
        arbol_before = deepcopy(arbol)
        build_mejorgest_from_traza(
            trace, base, structure_rows=structure_rows(), arbol_rows=arbol,
        )
        pd.testing.assert_frame_equal(trace, trace_before)
        pd.testing.assert_frame_equal(base, base_before)
        self.assertEqual(arbol, arbol_before)

    def test_blank_document_key_is_fail_closed(self):
        trace = trace_frame().copy()
        trace.loc[0, "IN_DOCUMENTO_DE_IDENTIDAD"] = "   "
        with self.assertRaisesRegex(PR04MejorGestError, "blank/non-text document"):
            build_mejorgest_from_traza(
                trace, base_frame(), structure_rows=structure_rows(), arbol_rows=arbol_rows(),
            )

    def test_output_contract_drift_is_fail_closed(self):
        rows = structure_rows()
        rows.append(
            _row("CONSOLIDADO_MEJORGEST", 7, "Extra", "ExtraCanonico", "Texto")
        )
        with self.assertRaisesRegex(PR04MejorGestError, "exactly the six governed columns"):
            build_mejorgest_from_traza(
                trace_frame(), base_frame(), structure_rows=rows, arbol_rows=arbol_rows(),
            )

    def test_null_arbol_mapping_is_fail_closed(self):
        arbol = arbol_rows()
        arbol[0]["Tipo Contacto"] = None
        with self.assertRaisesRegex(PR04MejorGestError, "blank ArbolHeuristico mapping"):
            build_mejorgest_from_traza(
                trace_frame(), base_frame(), structure_rows=structure_rows(), arbol_rows=arbol,
            )

    def test_ambiguous_non_iso_date_is_fail_closed(self):
        trace = trace_frame().copy()
        trace.loc[0, "CAP_FECHA"] = "01/02/2026"
        with self.assertRaisesRegex(PR04MejorGestError, "CAP_FECHA"):
            build_mejorgest_from_traza(
                trace, base_frame(), structure_rows=structure_rows(), arbol_rows=arbol_rows(),
            )


if __name__ == "__main__":
    unittest.main()
