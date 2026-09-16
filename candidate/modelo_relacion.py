"""Pure, fail-closed ModeloRelacion -> IN_SISTECREDITO builder.

The caller injects Config rows and the TER dataframe. This module performs no
network, filesystem, Google/Drive, runtime activation, or publication actions.
It interprets only the five rule kinds currently governed by Config_SinergIA.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

SYSTEM = "SinergIA"
DESTINATION = "IN_SISTECREDITO"
SUPPORTED_RULES = frozenset({"DIRECTO", "DEFAULT", "REGLA_TELEFONOS", "REGLA_FRANJAS", "REGLA_PRIORIDAD"})
REQUIRED_MODEL_COLUMNS = frozenset({
    "Sistema", "ArchivoDestino", "OrdenDestino", "ColumnaDestino", "TipoDatoDestino",
    "ColumnaOrigen", "ValorPredeterminado", "TipoRegla", "ParametrosRegla",
})
TRANSFORMS = frozenset({"upper", "lower", "title", "strip"})


class ModeloRelacionError(ValueError):
    """Raised whenever the governed mapping cannot be interpreted exactly."""


@dataclass(frozen=True)
class BuildEvidence:
    system: str
    destination: str
    mapping_count: int
    output_columns: tuple[str, ...]
    rule_counts: Mapping[str, int]


def _text(value: Any) -> str:
    if value is None or value is pd.NA:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _parse_params(raw: Any, *, required: Sequence[str], allowed: Sequence[str]) -> dict[str, str]:
    text = _text(raw)
    if not text:
        raise ModeloRelacionError(f"missing ParametrosRegla; required={tuple(required)!r}")
    out: dict[str, str] = {}
    allowed_set = set(allowed)
    for part in text.split(";"):
        piece = part.strip()
        if not piece or "=" not in piece:
            raise ModeloRelacionError(f"malformed ParametrosRegla token: {piece!r}")
        key, value = (item.strip() for item in piece.split("=", 1))
        if not key or not value:
            raise ModeloRelacionError(f"malformed ParametrosRegla token: {piece!r}")
        if key not in allowed_set:
            raise ModeloRelacionError(f"unsupported ParametrosRegla key: {key!r}")
        if key in out:
            raise ModeloRelacionError(f"duplicate ParametrosRegla key: {key!r}")
        out[key] = value
    missing = [key for key in required if key not in out]
    if missing:
        raise ModeloRelacionError(f"missing ParametrosRegla keys: {missing!r}")
    return out


def _governed_rows(model_rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in model_rows]
    if not rows:
        raise ModeloRelacionError("ModeloRelacion is empty")
    missing_headers = sorted(REQUIRED_MODEL_COLUMNS.difference(rows[0].keys()))
    if missing_headers:
        raise ModeloRelacionError(f"ModeloRelacion missing columns: {missing_headers!r}")

    selected = [
        row for row in rows
        if _text(row.get("Sistema")) == SYSTEM and _text(row.get("ArchivoDestino")) == DESTINATION
    ]
    if len(selected) != 29:
        raise ModeloRelacionError(f"expected exactly 29 governed mappings; got {len(selected)}")

    ordered: list[tuple[int, dict[str, Any]]] = []
    for row in selected:
        raw_order = row.get("OrdenDestino")
        try:
            order_float = float(raw_order)
            order = int(order_float)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ModeloRelacionError(f"invalid OrdenDestino: {raw_order!r}") from exc
        if not math.isfinite(order_float) or order_float != order:
            raise ModeloRelacionError(f"non-integral OrdenDestino: {raw_order!r}")
        dest = _text(row.get("ColumnaDestino"))
        if not dest:
            raise ModeloRelacionError(f"empty ColumnaDestino at order {order}")
        rule = _text(row.get("TipoRegla")).upper()
        if rule not in SUPPORTED_RULES:
            raise ModeloRelacionError(f"unsupported TipoRegla {rule!r} at order {order}")
        row["_order"] = order
        row["_dest"] = dest
        row["_rule"] = rule
        ordered.append((order, row))

    ordered.sort(key=lambda item: item[0])
    orders = [item[0] for item in ordered]
    if orders != list(range(1, 30)):
        raise ModeloRelacionError(f"OrdenDestino must be exactly 1..29; got {orders!r}")
    destinations = [item[1]["_dest"] for item in ordered]
    if len(set(destinations)) != len(destinations):
        raise ModeloRelacionError("duplicate ColumnaDestino in governed mapping")
    return [item[1] for item in ordered]


def _ensure_unique_source_column(df: pd.DataFrame, name: str) -> None:
    count = sum(1 for col in df.columns if col == name)
    if count == 0:
        raise ModeloRelacionError(f"required source column missing: {name!r}")
    if count != 1:
        raise ModeloRelacionError(f"ambiguous source column: {name!r}; matches={count}")


def _direct_series(df: pd.DataFrame, spec: Any) -> pd.Series:
    tokens = [token.strip() for token in _text(spec).split(";") if token.strip()]
    if not tokens:
        raise ModeloRelacionError("DIRECTO requires ColumnaOrigen")
    transforms = [token.lower() for token in tokens if token.lower() in TRANSFORMS]
    if len(transforms) > 1:
        raise ModeloRelacionError(f"DIRECTO allows at most one transform; got {transforms!r}")
    source_tokens = [token for token in tokens if token.lower() not in TRANSFORMS]
    matches = [token for token in source_tokens if sum(1 for col in df.columns if col == token) == 1]
    ambiguous = [token for token in source_tokens if sum(1 for col in df.columns if col == token) > 1]
    if ambiguous:
        raise ModeloRelacionError(f"ambiguous DIRECTO source token(s): {ambiguous!r}")
    if not matches:
        raise ModeloRelacionError(f"no literal DIRECTO source matched from {source_tokens!r}")

    source = matches[0]
    series = df[source].copy()
    if transforms:
        string = series.astype("string")
        transform = transforms[0]
        if transform == "upper":
            series = string.str.upper()
        elif transform == "lower":
            series = string.str.lower()
        elif transform == "title":
            series = string.str.title()
        elif transform == "strip":
            series = string.str.strip()
    return series


def _phone_digits(value: Any) -> str:
    if value is None or value is pd.NA:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    return re.sub(r"\D+", "", str(value))


def _apply_phones(out: pd.DataFrame, src: pd.DataFrame, rows: Sequence[Mapping[str, Any]]) -> None:
    if len(rows) != 4:
        raise ModeloRelacionError(f"REGLA_TELEFONOS requires exactly 4 destinations; got {len(rows)}")
    params_raw = {_text(row.get("ParametrosRegla")) for row in rows}
    if len(params_raw) != 1:
        raise ModeloRelacionError("REGLA_TELEFONOS destinations must share exactly one parameter contract")
    params = _parse_params(next(iter(params_raw)), required=("cols", "minlen", "maxlen"), allowed=("cols", "minlen", "maxlen"))
    source_cols = [item.strip() for item in params["cols"].split(",") if item.strip()]
    if not source_cols or len(set(source_cols)) != len(source_cols):
        raise ModeloRelacionError("REGLA_TELEFONOS cols must be a non-empty unique ordered list")
    for col in source_cols:
        _ensure_unique_source_column(src, col)
    try:
        minlen, maxlen = int(params["minlen"]), int(params["maxlen"])
    except ValueError as exc:
        raise ModeloRelacionError("REGLA_TELEFONOS minlen/maxlen must be integers") from exc
    if minlen <= 0 or maxlen < minlen:
        raise ModeloRelacionError("invalid REGLA_TELEFONOS length bounds")

    destinations = [str(row["_dest"]) for row in rows]
    values = {dest: [] for dest in destinations}
    for index in src.index:
        unique: list[str] = []
        for col in source_cols:
            digits = _phone_digits(src.at[index, col])
            if digits and minlen <= len(digits) <= maxlen and digits not in unique:
                unique.append(digits)
        for position, dest in enumerate(destinations):
            values[dest].append(unique[position] if position < len(unique) else "")
    for dest in destinations:
        out[dest] = pd.Series(values[dest], index=src.index, dtype="string")


def _active_ranges(parameter_rows: Iterable[Mapping[str, Any]], parameter: str) -> list[tuple[float, float, str]]:
    rows = [dict(row) for row in parameter_rows]
    required_headers = {"Parametro", "Preset", "Nombre", "Etiqueta", "Desde", "Hasta"}
    if not rows or not required_headers.issubset(rows[0].keys()):
        raise ModeloRelacionError("Parameters contract missing required columns")
    selector = [
        row for row in rows
        if _text(row.get("Parametro")) == f"{parameter}Preset" and _text(row.get("Nombre")) in {"Active", "Activo"}
    ]
    if len(selector) != 1:
        raise ModeloRelacionError(f"expected exactly one active preset selector for {parameter!r}; got {len(selector)}")
    preset = _text(selector[0].get("Desde")) or _text(selector[0].get("Etiqueta")) or _text(selector[0].get("Hasta"))
    if not preset:
        raise ModeloRelacionError(f"active preset value missing for {parameter!r}")

    selected = [row for row in rows if _text(row.get("Parametro")) == parameter and _text(row.get("Preset")) == preset]
    if not selected:
        raise ModeloRelacionError(f"no parameter ranges for {parameter!r} preset {preset!r}")
    ranges: list[tuple[float, float, str]] = []
    for row in selected:
        try:
            low, high = float(row.get("Desde")), float(row.get("Hasta"))
        except (TypeError, ValueError) as exc:
            raise ModeloRelacionError(f"invalid range for {parameter!r}: {row!r}") from exc
        label = _text(row.get("Etiqueta")) or _text(row.get("Nombre"))
        if not label or not math.isfinite(low) or not math.isfinite(high) or low > high:
            raise ModeloRelacionError(f"invalid range contract for {parameter!r}: {row!r}")
        ranges.append((low, high, label))
    ranges.sort(key=lambda item: item[0])
    for previous, current in zip(ranges, ranges[1:]):
        if current[0] <= previous[1]:
            raise ModeloRelacionError(f"overlapping ranges for {parameter!r}: {previous!r} / {current!r}")
    return ranges


def _apply_franja(out: pd.DataFrame, parameter_rows: Iterable[Mapping[str, Any]], row: Mapping[str, Any]) -> None:
    params = _parse_params(row.get("ParametrosRegla"), required=("param", "col_dias"), allowed=("param", "col_dias"))
    source = params["col_dias"]
    if source not in out.columns:
        raise ModeloRelacionError(f"REGLA_FRANJAS output dependency missing: {source!r}")
    ranges = _active_ranges(parameter_rows, params["param"])
    numeric = pd.to_numeric(out[source], errors="coerce")

    def label_for(value: Any) -> Any:
        if pd.isna(value):
            return pd.NA
        matches = [label for low, high, label in ranges if low <= float(value) <= high]
        if len(matches) > 1:
            raise ModeloRelacionError(f"ambiguous range for {params['param']!r} value={value!r}")
        return matches[0] if matches else pd.NA

    out[str(row["_dest"])] = numeric.map(label_for).astype("string")


def _apply_priority(out: pd.DataFrame, row: Mapping[str, Any]) -> None:
    params = _parse_params(
        row.get("ParametrosRegla"),
        required=("cols", "numeric", "fillna", "rank", "ascending"),
        allowed=("cols", "numeric", "fillna", "rank", "ascending"),
    )
    columns = [item.strip() for item in params["cols"].split(",") if item.strip()]
    if not columns or len(set(columns)) != len(columns):
        raise ModeloRelacionError("REGLA_PRIORIDAD cols must be a non-empty unique ordered list")
    if params["numeric"] != "coerce" or params["rank"] != "dense" or params["ascending"].lower() not in {"true", "false"}:
        raise ModeloRelacionError("unsupported REGLA_PRIORIDAD semantics")
    try:
        fill = float(params["fillna"])
    except ValueError as exc:
        raise ModeloRelacionError("REGLA_PRIORIDAD fillna must be numeric") from exc
    missing = [col for col in columns if col not in out.columns]
    if missing:
        raise ModeloRelacionError(f"REGLA_PRIORIDAD output dependency missing: {missing!r}")
    score = pd.Series(0.0, index=out.index)
    for col in columns:
        score = score + pd.to_numeric(out[col], errors="coerce").fillna(fill)
    ascending = params["ascending"].lower() == "true"
    out[str(row["_dest"])] = score.rank(method="dense", ascending=ascending).astype("Int64")


def build_in_sistecredito(
    source: pd.DataFrame,
    *,
    model_rows: Iterable[Mapping[str, Any]],
    parameter_rows: Iterable[Mapping[str, Any]],
) -> tuple[pd.DataFrame, BuildEvidence]:
    """Build the governed 29-column IN dataframe without external side effects."""
    if not isinstance(source, pd.DataFrame):
        raise ModeloRelacionError("source must be a pandas DataFrame")
    rows = _governed_rows(model_rows)
    out = pd.DataFrame(index=source.index)
    rule_counts = {rule: 0 for rule in sorted(SUPPORTED_RULES)}

    phone_rows = [row for row in rows if row["_rule"] == "REGLA_TELEFONOS"]
    for row in rows:
        rule = str(row["_rule"])
        dest = str(row["_dest"])
        rule_counts[rule] += 1
        if rule == "DIRECTO":
            out[dest] = _direct_series(source, row.get("ColumnaOrigen"))
        elif rule == "DEFAULT":
            out[dest] = pd.Series([row.get("ValorPredeterminado")] * len(source), index=source.index)
        elif rule == "REGLA_TELEFONOS":
            if dest not in out.columns:
                out[dest] = pd.Series([""] * len(source), index=source.index, dtype="string")
        elif rule == "REGLA_FRANJAS":
            _apply_franja(out, parameter_rows, row)
        elif rule == "REGLA_PRIORIDAD":
            _apply_priority(out, row)

    _apply_phones(out, source, phone_rows)
    expected = tuple(str(row["_dest"]) for row in rows)
    out = out.loc[:, list(expected)]
    if tuple(out.columns) != expected or len(out.columns) != 29:
        raise ModeloRelacionError("output contract mismatch after build")
    return out, BuildEvidence(
        system=SYSTEM,
        destination=DESTINATION,
        mapping_count=len(rows),
        output_columns=expected,
        rule_counts={key: value for key, value in rule_counts.items() if value},
    )
