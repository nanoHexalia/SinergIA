from __future__ import annotations

import copy
import unittest

from candidate.quality_gate import evaluate_quality_gate


def gate_rows():
    return [
        {
            "Gate": "QualityGate",
            "Regla": "null_rate_documento_id",
            "MetricKey": "null_rate_documento_id_ter",
            "Operador": "<=",
            "Umbral": "0.00",
            "ResultadoFail": "STOP",
            "Activo": True,
        },
        {
            "Gate": "QualityGate",
            "Regla": "null_rate_credito_id",
            "MetricKey": "null_rate_credito_id_ter",
            "Operador": "<=",
            "Umbral": "0.01",
            "ResultadoFail": "DEGRADE",
            "Activo": True,
        },
    ]


def trace_rows():
    return [
        {
            "Codigo": "QUALITY_GATE_WARN",
            "Nivel": "WARN",
            "Etapa": "PR_03",
            "Accion": "DEGRADE",
            "EsBloqueante": False,
            "Activo": True,
        },
        {
            "Codigo": "QUALITY_GATE_FAIL",
            "Nivel": "ERROR",
            "Etapa": "PR_03",
            "Accion": "STOP",
            "EsBloqueante": True,
            "Activo": True,
        },
    ]


def good_metrics():
    return {
        "null_rate_documento_id_ter": 0.0,
        "null_rate_credito_id_ter": 0.01,
    }


class QualityGateTests(unittest.TestCase):
    def test_pass_at_current_thresholds(self):
        ok, detail = evaluate_quality_gate(good_metrics(), gate_rows(), trace_rows())
        self.assertTrue(ok)
        self.assertEqual(detail["status"], "PASS")
        self.assertFalse(detail["blocking"])
        self.assertFalse(detail["degraded"])
        self.assertEqual(detail["codes_emitted"], [])
        self.assertEqual(len(detail["rules"]), 2)

    def test_degrade_is_non_blocking_and_emits_warn(self):
        metrics = good_metrics()
        metrics["null_rate_credito_id_ter"] = 0.02
        ok, detail = evaluate_quality_gate(metrics, gate_rows(), trace_rows())
        self.assertTrue(ok)
        self.assertEqual(detail["status"], "DEGRADE")
        self.assertTrue(detail["degraded"])
        self.assertFalse(detail["blocking"])
        self.assertEqual(detail["codes_emitted"], ["QUALITY_GATE_WARN"])

    def test_stop_is_blocking_and_emits_fail(self):
        metrics = good_metrics()
        metrics["null_rate_documento_id_ter"] = 0.01
        ok, detail = evaluate_quality_gate(metrics, gate_rows(), trace_rows())
        self.assertFalse(ok)
        self.assertEqual(detail["status"], "STOP")
        self.assertTrue(detail["blocking"])
        self.assertEqual(detail["codes_emitted"], ["QUALITY_GATE_FAIL"])

    def test_stop_dominates_degrade_but_both_failures_are_traced(self):
        metrics = {
            "null_rate_documento_id_ter": 0.01,
            "null_rate_credito_id_ter": 0.02,
        }
        ok, detail = evaluate_quality_gate(metrics, gate_rows(), trace_rows())
        self.assertFalse(ok)
        self.assertEqual(detail["status"], "STOP")
        self.assertEqual(
            detail["codes_emitted"],
            ["QUALITY_GATE_FAIL", "QUALITY_GATE_WARN"],
        )
        self.assertEqual([rule["passed"] for rule in detail["rules"]], [False, False])

    def test_missing_required_metric_fails_closed(self):
        metrics = good_metrics()
        del metrics["null_rate_documento_id_ter"]
        ok, detail = evaluate_quality_gate(metrics, gate_rows(), trace_rows())
        self.assertFalse(ok)
        self.assertEqual(detail["status"], "STOP")
        self.assertIn("METRIC_MISSING", detail["reason"])
        self.assertEqual(detail["codes_emitted"], ["QUALITY_GATE_FAIL"])

    def test_non_numeric_or_non_finite_metric_fails_closed(self):
        for value in ("not-a-number", None, True, float("inf"), float("nan")):
            with self.subTest(value=value):
                metrics = good_metrics()
                metrics["null_rate_documento_id_ter"] = value
                ok, detail = evaluate_quality_gate(metrics, gate_rows(), trace_rows())
                self.assertFalse(ok)
                self.assertEqual(detail["status"], "STOP")
                self.assertIn("EVALUATION_INVALID", detail["reason"])
                self.assertEqual(detail["codes_emitted"], ["QUALITY_GATE_FAIL"])

    def test_malformed_gate_contract_fails_closed(self):
        mutations = []
        bad_operator = gate_rows()
        bad_operator[0]["Operador"] = "~="
        mutations.append(bad_operator)
        bad_threshold = gate_rows()
        bad_threshold[0]["Umbral"] = "not-a-threshold"
        mutations.append(bad_threshold)
        bad_result = gate_rows()
        bad_result[0]["ResultadoFail"] = "CONTINUE"
        mutations.append(bad_result)
        missing_field = gate_rows()
        del missing_field[0]["MetricKey"]
        mutations.append(missing_field)
        no_quality = gate_rows()
        for row in no_quality:
            row["Gate"] = "OtherGate"
        mutations.append(no_quality)
        for rows in mutations:
            with self.subTest(rows=rows):
                ok, detail = evaluate_quality_gate(good_metrics(), rows, trace_rows())
                self.assertFalse(ok)
                self.assertIn("GATE_CONTRACT_INVALID", detail["reason"])

    def test_duplicate_quality_contract_fails_closed(self):
        duplicate_rule = gate_rows()
        duplicate_rule.append(copy.deepcopy(duplicate_rule[0]))
        duplicate_metric = gate_rows()
        extra = copy.deepcopy(duplicate_metric[0])
        extra["Regla"] = "another_rule_same_metric"
        duplicate_metric.append(extra)
        for rows in (duplicate_rule, duplicate_metric):
            with self.subTest(rows=rows):
                ok, detail = evaluate_quality_gate(good_metrics(), rows, trace_rows())
                self.assertFalse(ok)
                self.assertIn("GATE_CONTRACT_INVALID", detail["reason"])
                self.assertEqual(detail["codes_emitted"], ["QUALITY_GATE_FAIL"])

    def test_invalid_trace_contract_fails_closed_without_unvalidated_emission(self):
        invalid_sets = []
        missing_warn = [row for row in trace_rows() if row["Codigo"] != "QUALITY_GATE_WARN"]
        invalid_sets.append(missing_warn)
        duplicate_fail = trace_rows()
        duplicate_fail.append(copy.deepcopy(duplicate_fail[1]))
        invalid_sets.append(duplicate_fail)
        wrong_level = trace_rows()
        wrong_level[1]["Nivel"] = "WARN"
        invalid_sets.append(wrong_level)
        inactive_fail = trace_rows()
        inactive_fail[1]["Activo"] = False
        invalid_sets.append(inactive_fail)
        for rows in invalid_sets:
            with self.subTest(rows=rows):
                ok, detail = evaluate_quality_gate(good_metrics(), gate_rows(), rows)
                self.assertFalse(ok)
                self.assertEqual(detail["status"], "STOP")
                self.assertIn("TRACE_CONTRACT_INVALID", detail["reason"])
                self.assertEqual(detail["codes_emitted"], [])
                self.assertEqual(detail["expected_code"], "QUALITY_GATE_FAIL")


if __name__ == "__main__":
    unittest.main()
