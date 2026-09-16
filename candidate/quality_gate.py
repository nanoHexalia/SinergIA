"""Pure Config-driven QualityGate evaluator for the Phase B2 candidate.

The evaluator consumes already-loaded Config rows and metrics. It performs no I/O,
metric calculation, persistence, runtime activation, or external calls.
"""
from __future__ import annotations

from math import isfinite
from numbers import Real
from typing import Any, Iterable, Mapping

QUALITY_GATE = "QualityGate"
FAIL_CODE = "QUALITY_GATE_FAIL"
WARN_CODE = "QUALITY_GATE_WARN"
_REQUIRED_GATE_FIELDS = ("Gate", "Regla", "MetricKey", "Operador", "Umbral", "ResultadoFail")
_SUPPORTED_OPERATORS = {"<=", "<", ">=", ">", "=", "!="}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _rows(values: Iterable[Mapping[str, Any]], *, name: str) -> list[Mapping[str, Any]]:
    try:
        rows = list(values)
    except TypeError as exc:
        raise ValueError(f"{name} must be an iterable of mappings") from exc
    if any(not isinstance(row, Mapping) for row in rows):
        raise ValueError(f"{name} must contain mappings only")
    return rows


def _flag(value: Any, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, Real) and not isinstance(value, bool) and value in (0, 1):
        return bool(value)
    normalized = _text(value).casefold()
    if normalized in {"true", "1", "yes", "si", "sí"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"{field} must be boolean")


def _active(row: Mapping[str, Any]) -> bool:
    return True if "Activo" not in row else _flag(row.get("Activo"), field="Activo")


def _number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or value is None or _text(value) == "":
        raise ValueError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _compare(actual: float, operator: str, threshold: float) -> bool:
    if operator == "<=":
        return actual <= threshold
    if operator == "<":
        return actual < threshold
    if operator == ">=":
        return actual >= threshold
    if operator == ">":
        return actual > threshold
    if operator == "=":
        return actual == threshold
    if operator == "!=":
        return actual != threshold
    raise ValueError(f"unsupported operator: {operator!r}")


def _closed(reason: str, *, code_available: bool, rules: list[dict[str, Any]] | None = None) -> tuple[bool, dict[str, Any]]:
    return False, {
        "gate": QUALITY_GATE,
        "status": "STOP",
        "blocking": True,
        "degraded": False,
        "reason": reason,
        "expected_code": FAIL_CODE,
        "codes_emitted": [FAIL_CODE] if code_available else [],
        "rules": list(rules or []),
    }


def _resolve_trace(rows: list[Mapping[str, Any]], code: str, *, level: str, action: str, blocking: bool) -> Mapping[str, Any]:
    matches = [row for row in rows if _text(row.get("Codigo")) == code]
    if len(matches) != 1:
        raise ValueError(f"TraceCode {code!r} must resolve exactly once; matches={len(matches)}")
    row = matches[0]
    if not _active(row):
        raise ValueError(f"TraceCode {code!r} is inactive")
    if _text(row.get("Nivel")) != level:
        raise ValueError(f"TraceCode {code!r} Nivel must be {level}")
    if _text(row.get("Etapa")) != "PR_03":
        raise ValueError(f"TraceCode {code!r} Etapa must be PR_03")
    if _text(row.get("Accion")) != action:
        raise ValueError(f"TraceCode {code!r} Accion must be {action}")
    if "EsBloqueante" in row and _flag(row.get("EsBloqueante"), field="EsBloqueante") is not blocking:
        raise ValueError(f"TraceCode {code!r} EsBloqueante mismatch")
    return row


def _validate_trace_contract(rows: list[Mapping[str, Any]]) -> None:
    _resolve_trace(rows, FAIL_CODE, level="ERROR", action="STOP", blocking=True)
    _resolve_trace(rows, WARN_CODE, level="WARN", action="DEGRADE", blocking=False)


def _quality_rows(rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    selected: list[Mapping[str, Any]] = []
    for row in rows:
        if _text(row.get("Gate")) == QUALITY_GATE and _active(row):
            selected.append(row)
    return selected


def _validate_gate_rows(rows: list[Mapping[str, Any]]) -> None:
    if not rows:
        raise ValueError("QualityGate has no active rules")
    seen_rules: set[str] = set()
    seen_metrics: set[str] = set()
    for row in rows:
        missing = [field for field in _REQUIRED_GATE_FIELDS if field not in row or _text(row.get(field)) == ""]
        if missing:
            raise ValueError(f"QualityGate row missing required fields: {missing}")
        rule = _text(row.get("Regla"))
        metric = _text(row.get("MetricKey"))
        if rule in seen_rules:
            raise ValueError(f"duplicate QualityGate Regla: {rule}")
        if metric in seen_metrics:
            raise ValueError(f"duplicate QualityGate MetricKey: {metric}")
        seen_rules.add(rule)
        seen_metrics.add(metric)
        operator = _text(row.get("Operador"))
        if operator not in _SUPPORTED_OPERATORS:
            raise ValueError(f"unsupported QualityGate operator: {operator!r}")
        _number(row.get("Umbral"), field=f"Umbral[{rule}]")
        result_fail = _text(row.get("ResultadoFail"))
        if result_fail not in {"STOP", "DEGRADE"}:
            raise ValueError(f"unsupported ResultadoFail for {rule!r}: {result_fail!r}")


def _emit_once(codes: list[str], code: str) -> None:
    if code not in codes:
        codes.append(code)


def evaluate_quality_gate(
    metrics: Mapping[str, Any],
    gate_rows: Iterable[Mapping[str, Any]],
    trace_rows: Iterable[Mapping[str, Any]],
) -> tuple[bool, dict[str, Any]]:
    """Evaluate CURRENT QualityGate policy from injected Config rows.

    Returns ``(ok, detail)`` so it can be consumed by the existing U2 bridge.
    ``ok`` is False only for STOP or fail-closed outcomes; DEGRADE remains non-blocking.
    """
    if not isinstance(metrics, Mapping):
        return _closed("metrics must be a mapping", code_available=False)
    try:
        traces = _rows(trace_rows, name="trace_rows")
        _validate_trace_contract(traces)
    except (TypeError, ValueError) as exc:
        return _closed(f"TRACE_CONTRACT_INVALID: {exc}", code_available=False)

    try:
        gates = _quality_rows(_rows(gate_rows, name="gate_rows"))
        _validate_gate_rows(gates)
    except (TypeError, ValueError) as exc:
        return _closed(f"GATE_CONTRACT_INVALID: {exc}", code_available=True)

    status = "PASS"
    codes: list[str] = []
    evaluated: list[dict[str, Any]] = []

    for row in gates:
        rule = _text(row.get("Regla"))
        metric_key = _text(row.get("MetricKey"))
        if metric_key not in metrics:
            return _closed(f"METRIC_MISSING: {metric_key}", code_available=True, rules=evaluated)
        try:
            actual = _number(metrics.get(metric_key), field=f"metric[{metric_key}]")
            threshold = _number(row.get("Umbral"), field=f"Umbral[{rule}]")
            operator = _text(row.get("Operador"))
            passed = _compare(actual, operator, threshold)
        except ValueError as exc:
            return _closed(f"EVALUATION_INVALID: {exc}", code_available=True, rules=evaluated)

        result_fail = _text(row.get("ResultadoFail"))
        evaluated.append({
            "regla": rule,
            "metric_key": metric_key,
            "operator": operator,
            "threshold": threshold,
            "actual": actual,
            "passed": passed,
            "result_fail": result_fail,
        })
        if passed:
            continue
        if result_fail == "STOP":
            status = "STOP"
            _emit_once(codes, FAIL_CODE)
        else:
            _emit_once(codes, WARN_CODE)
            if status != "STOP":
                status = "DEGRADE"

    blocking = status == "STOP"
    detail = {
        "gate": QUALITY_GATE,
        "status": status,
        "blocking": blocking,
        "degraded": status == "DEGRADE",
        "codes_emitted": codes,
        "rules": evaluated,
    }
    return not blocking, detail
