"""Pure CleanEngine candidate with exact canonical target binding.

No network, Drive, Colab, Gradio, production data, or runtime activation occurs here.
Config frames and the Estructuras frame are injected by the caller.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
import unicodedata
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from .config_contract import CleanRulePolicy, resolve_clean_rule_policy


DEFAULT_LOGICAL_FILE_BY_DATASET = {
    "df_final_sorted": "IN_SISTECREDITO",
    "df_in_full": "IN_SISTECREDITO",
}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _truthy(value: Any) -> bool:
    return _text(value).casefold() in {"1", "true", "verdadero", "si", "sí", "yes", "y"}


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if isinstance(frame, pd.DataFrame):
        return frame.to_dict(orient="records")
    if isinstance(frame, Mapping):
        return [dict(frame)]
    return [dict(row) for row in frame]


def _parse_targets(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [_text(v) for v in value if _text(v)]
    raw = _text(value)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [_text(v) for v in parsed if _text(v)]
    return [_text(v).strip('"\'') for v in raw.strip("[]").split(",") if _text(v).strip('"\'')]


def _spec_value(row: Mapping[str, Any], *names: str, default: Any = "") -> Any:
    for name in names:
        if name in row and _text(row.get(name)):
            return row.get(name)
    return default


@dataclass(frozen=True)
class CanonicalTargetBinding:
    requested_target: str
    logical_file: str
    canonical_name: str
    canonical_alias: str
    dataframe_column: str


@dataclass(frozen=True)
class BindingFailure:
    requested_target: str
    code: str
    detail: str


def _structure_scope(structures: Any, logical_file: str) -> list[dict[str, Any]]:
    rows = _records(structures)
    if not logical_file:
        return rows
    return [row for row in rows if _text(row.get("ArchivoLogico")) == logical_file]


def bind_target_exact(
    target: str,
    *,
    dataframe_columns: Sequence[str],
    structures: Any,
    logical_file: str,
) -> CanonicalTargetBinding | BindingFailure:
    """Bind only exact NombreColumna/AliasCanonico matches; never fuzzy-correct drift."""
    target = _text(target)
    scope = _structure_scope(structures, logical_file)
    matches = [
        row for row in scope
        if target in {_text(row.get("NombreColumna")), _text(row.get("AliasCanonico"))}
    ]
    if not matches:
        return BindingFailure(target, "UNBOUND_CONFIG_TARGET", f"no exact Estructuras match in {logical_file}")
    if len(matches) != 1:
        return BindingFailure(target, "AMBIGUOUS_STRUCTURE_TARGET", f"matches={len(matches)} in {logical_file}")

    row = matches[0]
    name = _text(row.get("NombreColumna"))
    alias = _text(row.get("AliasCanonico"))
    present = [c for c in (name, alias) if c and c in dataframe_columns]
    present = list(dict.fromkeys(present))
    if not present:
        return BindingFailure(target, "MISSING_DATAFRAME_COLUMN", f"expected one of {name!r}/{alias!r}")
    if len(present) != 1:
        return BindingFailure(target, "AMBIGUOUS_DATAFRAME_COLUMN", f"both canonical forms are present: {present!r}")
    return CanonicalTargetBinding(target, logical_file, name, alias, present[0])


def _strip_accents(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch))


def _nonempty_mask(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype("string").str.strip().fillna("").ne("")


def _apply_series_rule(rule_id: str, series: pd.Series, params: Mapping[str, Any]) -> tuple[pd.Series, pd.Series]:
    """Return transformed series plus a boolean failure mask."""
    rid = _text(rule_id).upper()
    before = series.copy()
    fail = pd.Series(False, index=series.index, dtype=bool)

    if rid == "TEXT_TRIM":
        out = series.astype("string")
        if bool(params.get("trim", True)):
            out = out.str.strip()
        if bool(params.get("collapse_internal_spaces", True)):
            out = out.str.replace(r"\s+", " ", regex=True)
        return out, fail

    if rid == "TEXT_UNICODE":
        trim = bool(params.get("trim", True))
        strip_accents = bool(params.get("strip_accents", False))
        to_upper = bool(params.get("to_upper", False))
        def transform(v: Any) -> Any:
            if pd.isna(v):
                return pd.NA
            s = str(v)
            if trim:
                s = s.strip()
            if strip_accents:
                s = _strip_accents(s)
            if to_upper:
                s = s.upper()
            return s
        return series.map(transform).astype("string"), fail

    if rid == "TEXT_ALLOWED_CHARS":
        allowed = _text(params.get("allowed_chars"))
        if not allowed:
            return series.copy(), fail
        pattern = f"[^{allowed}]"
        out = series.astype("string").str.replace(pattern, "", regex=True).str.replace(r"\s+", " ", regex=True).str.strip()
        return out, fail

    if rid == "DOC_NORMALIZE":
        trim = bool(params.get("trim", True))
        keep_alnum = bool(params.get("keep_alnum_only", True))
        to_upper = bool(params.get("to_upper", True))
        strip_accents = bool(params.get("strip_accents", True))
        def transform(v: Any) -> Any:
            if pd.isna(v):
                return pd.NA
            s = str(v)
            if trim:
                s = s.strip()
            if strip_accents:
                s = _strip_accents(s)
            if to_upper:
                s = s.upper()
            if keep_alnum:
                s = re.sub(r"[^A-Za-z0-9]", "", s)
            return s if s else pd.NA
        return series.map(transform).astype("string"), fail

    if rid in {"PHONE_DIGITS", "PHONE_CO_10"}:
        out = series.astype("string").str.replace(r"\D+", "", regex=True)
        if rid == "PHONE_CO_10":
            out = out.map(lambda v: v[-10:] if pd.notna(v) and str(v).startswith("57") and len(str(v)) > 10 else v).astype("string")
            expected = int(params.get("co_len", 10) or 10)
            prefixes = tuple(str(p) for p in (params.get("co_mobile_prefix") or []))
            fail = _nonempty_mask(before) & (out.str.len().fillna(0).ne(expected))
            if prefixes:
                fail = fail | (_nonempty_mask(before) & ~out.str.startswith(prefixes, na=False))
        else:
            minimum = int(params.get("min_len", 0) or 0)
            maximum = int(params.get("max_len", 0) or 0)
            fail = _nonempty_mask(before) & out.str.len().fillna(0).lt(minimum)
            if maximum > 0:
                fail = fail | (_nonempty_mask(before) & out.str.len().fillna(0).gt(maximum))
        return out, fail

    if rid == "NUM_PARSE":
        raw = series.astype("string").str.strip().str.replace(r"[^\d,\.\-]", "", regex=True)
        locale = _text(params.get("locale")).casefold()
        if locale in {"es_co", "co", "es-co"}:
            raw = raw.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
        else:
            raw = raw.str.replace(",", "", regex=False)
        out = pd.to_numeric(raw, errors="coerce")
        fail = _nonempty_mask(before) & out.isna()
        return out, fail

    if rid == "NUM_NON_NEGATIVE":
        out = pd.to_numeric(series, errors="coerce")
        minimum = float(params.get("min", params.get("min_value", 0)) or 0)
        fail = out.notna() & out.lt(minimum)
        return out, fail

    if rid == "NUM_ROUND":
        out = pd.to_numeric(series, errors="coerce").round(int(params.get("decimals", 0) or 0))
        fail = _nonempty_mask(before) & out.isna()
        return out, fail

    if rid == "DATE_PARSE":
        out = pd.to_datetime(series, errors="coerce", dayfirst=bool(params.get("dayfirst", True)))
        fail = _nonempty_mask(before) & out.isna()
        return out, fail

    if rid == "DATE_RANGE":
        out = pd.to_datetime(series, errors="coerce")
        min_dt = pd.to_datetime(params.get("min", "1900-01-01"), errors="coerce")
        max_raw = _text(params.get("max", "today")).casefold()
        max_dt = pd.Timestamp.today().normalize() if max_raw == "today" else pd.to_datetime(max_raw, errors="coerce")
        fail = out.notna() & ((out < min_dt) | (out > max_dt))
        return out, fail

    raise KeyError(f"unsupported CleanEngine rule_id={rule_id!r}")


def _apply_failure_action(
    before: pd.Series,
    after: pd.Series,
    fail: pd.Series,
    policy: CleanRulePolicy,
) -> tuple[pd.Series, bool]:
    action = policy.action_on_fail
    if not bool(fail.any()):
        return after, False
    if action == "warn_only":
        result = after.copy()
        result.loc[fail] = before.loc[fail]
        return result, False
    if action in {"set_null", "drop_row", "block_run"}:
        result = after.copy()
        result.loc[fail] = pd.NA
        return result, action == "block_run"
    raise ValueError(f"unsupported action_on_fail={action!r} for rule_id={policy.rule_id!r}")


def apply_cleanengine_candidate(
    dataframe: pd.DataFrame,
    dataset_alias: str,
    *,
    df_spec: Any,
    df_presets: Any,
    df_estructuras: Any = None,
    overrides_enabled_by_rule_id: Mapping[str, bool] | None = None,
    overrides_enabled_by_preset_id: Mapping[str, bool] | None = None,
    logical_file_by_dataset_alias: Mapping[str, str] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Execute enabled CleanSpec rules using exact canonical bindings and explicit QA proof."""
    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("CleanEngine candidate requires a pandas DataFrame")

    overrides_rule = dict(overrides_enabled_by_rule_id or {})
    overrides_preset = dict(overrides_enabled_by_preset_id or {})
    logical_map = {**DEFAULT_LOGICAL_FILE_BY_DATASET, **dict(logical_file_by_dataset_alias or {})}
    logical_file = _text(logical_map.get(dataset_alias))

    spec_rows = [r for r in _records(df_spec) if _text(r.get("dataset_alias")) == _text(dataset_alias)]
    preset_rows = _records(df_presets)
    def order_key(row: Mapping[str, Any]) -> tuple[str, float]:
        raw = _spec_value(row, "rule_order", "RULE_ORDER", default=999999)
        try:
            order = float(raw)
        except (TypeError, ValueError):
            order = 999999.0
        return (_text(_spec_value(row, "stage", "STAGE")).casefold(), order)
    spec_rows.sort(key=order_key)

    out = dataframe.copy()
    applied: list[dict[str, Any]] = []
    warnings: list[str] = []
    failures: list[dict[str, Any]] = []
    hard_fail_reasons: list[str] = []
    resolved_bindings: list[dict[str, Any]] = []

    if not logical_file:
        warnings.append(f"NO_STRUCTURE_SCOPE_FOR_DATASET:{dataset_alias}")

    for row in spec_rows:
        enabled = _truthy(_spec_value(row, "enabled", "ENABLED", default=True))
        policy = resolve_clean_rule_policy(row, preset_rows)
        if policy.preset_id in overrides_preset:
            enabled = bool(overrides_preset[policy.preset_id])
        elif policy.rule_id in overrides_rule:
            enabled = bool(overrides_rule[policy.rule_id])
        if not enabled:
            continue

        targets = _parse_targets(_spec_value(row, "target_columns", "TARGET_COLUMNS"))
        rule_failures: list[BindingFailure] = []
        bindings: list[CanonicalTargetBinding] = []
        for target in targets:
            result = bind_target_exact(
                target,
                dataframe_columns=list(out.columns),
                structures=df_estructuras,
                logical_file=logical_file,
            )
            if isinstance(result, BindingFailure):
                rule_failures.append(result)
                failures.append(asdict(result))
                warnings.append(f"{result.code}:{result.requested_target}:{result.detail}")
            else:
                bindings.append(result)
                resolved_bindings.append(asdict(result))

        if rule_failures and (policy.severity == "block" or policy.action_on_fail == "block_run"):
            hard_fail_reasons.extend(f"{f.code}:{f.requested_target}" for f in rule_failures)
            warnings.append(f"RULE_BLOCKED_BY_BINDING:{policy.rule_id}:{policy.preset_id}")
            break
        if not bindings:
            warnings.append(f"RULE_NOT_APPLIED_NO_BOUND_TARGETS:{policy.rule_id}:{policy.preset_id}")
            continue

        try:
            changed_cells = 0
            failed_cells = 0
            rows_to_drop = pd.Series(False, index=out.index, dtype=bool)
            rule_hard_fail = False
            for binding in bindings:
                col = binding.dataframe_column
                before = out[col].copy()
                transformed, fail = _apply_series_rule(policy.rule_id, before, policy.params)
                transformed, action_hard_fail = _apply_failure_action(before, transformed, fail, policy)
                failed_cells += int(fail.sum())
                try:
                    changed_cells += int((before.astype("string").fillna("") != transformed.astype("string").fillna("")).sum())
                except Exception:
                    pass
                out[col] = transformed
                if policy.action_on_fail == "drop_row":
                    rows_to_drop = rows_to_drop | fail
                rule_hard_fail = rule_hard_fail or action_hard_fail

            dropped_rows = int(rows_to_drop.sum())
            if dropped_rows:
                out = out.loc[~rows_to_drop].copy()
            detail = {
                "preset_id": policy.preset_id,
                "rule_id": policy.rule_id,
                "stage": _text(_spec_value(row, "stage", "STAGE")),
                "severity": policy.severity,
                "action_on_fail": policy.action_on_fail,
                "requested_targets": targets,
                "bound_columns": [b.dataframe_column for b in bindings],
                "binding_failure_count": len(rule_failures),
                "changed_cells": changed_cells,
                "failed_cells": failed_cells,
                "dropped_rows": dropped_rows,
            }
            applied.append(detail)
            if failed_cells and policy.severity in {"warn", "block"}:
                warnings.append(f"RULE_VALIDATION_FAILURE:{policy.rule_id}:failed_cells={failed_cells}")
            if rule_hard_fail:
                hard_fail_reasons.append(f"RULE_FAIL_BLOCK:{policy.rule_id}")
                break
        except Exception as exc:
            warnings.append(f"RULE_EXECUTION_ERROR:{policy.rule_id}:{type(exc).__name__}:{exc}")
            if policy.severity == "block" or policy.action_on_fail == "block_run":
                hard_fail_reasons.append(f"RULE_EXECUTION_ERROR:{policy.rule_id}")
                break

    warnings = list(dict.fromkeys(warnings))
    hard_fail_reasons = list(dict.fromkeys(hard_fail_reasons))
    qa = {
        "engine": "CleanEngineCandidate",
        "dataset_alias": dataset_alias,
        "structure_logical_file": logical_file,
        "applied": applied,
        "warn": warnings,
        "hard_fail": bool(hard_fail_reasons),
        "hard_fail_reasons": hard_fail_reasons,
        "binding": {
            "resolved": resolved_bindings,
            "failures": failures,
            "resolved_count": len(resolved_bindings),
            "failure_count": len(failures),
        },
        "rows_in": int(len(dataframe)),
        "rows_out": int(len(out)),
    }
    return out, qa
