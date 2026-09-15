"""Pure, import-safe Config contracts for the Phase B2 candidate.

This module performs no network or spreadsheet access.  Callers inject rows already
read from the canonical Config authority.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
from typing import Any, Iterable, Mapping, Sequence

_MISSING = object()


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _first(row: Mapping[str, Any], names: Sequence[str], default: Any = "") -> Any:
    for name in names:
        if name in row and _text(row.get(name)) != "":
            return row.get(name)
    return default


def resolve_setting_id(
    rows: Iterable[Mapping[str, Any]],
    setting_id: str,
    *,
    value_columns: Sequence[str],
) -> Any:
    """Resolve one SettingID exactly; missing and duplicate matches fail closed."""
    wanted = _text(setting_id).casefold()
    if not wanted:
        raise ValueError("setting_id must be non-empty")
    matches = [r for r in rows if _text(r.get("SettingID")).casefold() == wanted]
    if len(matches) != 1:
        raise ValueError(f"SettingID must resolve exactly once: {setting_id!r}; matches={len(matches)}")
    value = _first(matches[0], value_columns, _MISSING)
    if value is _MISSING:
        raise KeyError(f"SettingID {setting_id!r} has no configured value in {tuple(value_columns)!r}")
    return value


@dataclass(frozen=True)
class CleanRulePolicy:
    preset_id: str
    rule_id: str
    severity: str
    action_on_fail: str
    params: Mapping[str, Any]


def _json_object(value: Any) -> dict[str, Any]:
    if value is None or _text(value) == "":
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    parsed = json.loads(str(value))
    if not isinstance(parsed, dict):
        raise TypeError("CleanEngine params_json must decode to an object")
    return parsed


def resolve_clean_rule_policy(
    spec_row: Mapping[str, Any],
    preset_rows: Iterable[Mapping[str, Any]],
) -> CleanRulePolicy:
    """Mirror demonstrated provenance precedence without consuming *_eff columns.

    Explicit CleanSpec rule/severity/action values win.  Missing values fall back
    to the referenced CleanPresets defaults.  Preset params are overlaid only by
    an explicit raw CleanSpec params_json, matching the demonstrated engine.
    """
    preset_id = _text(_first(spec_row, ("preset_id_calc", "preset_id", "PresetId", "PRESET_ID", "PRESET_ID_CALC")))
    # Provenance builds preset_map by row order, so the last matching preset wins.
    # Preserve that demonstrated behavior rather than introducing a new business rule.
    preset = {}
    for row in preset_rows:
        if _text(_first(row, ("preset_id", "PresetId", "PRESET_ID"))) == preset_id:
            preset = row

    rule_id = _text(_first(spec_row, ("rule_id_calc", "rule_id", "RuleId", "RULE_ID", "RULE_ID_CALC")))
    if not rule_id:
        rule_id = _text(_first(preset, ("rule_id", "RuleId", "RULE_ID")))

    severity = _text(_first(spec_row, ("severity", "default_severity", "SEVERITY"))).lower()
    if not severity:
        severity = _text(_first(preset, ("default_severity", "severity", "DEFAULT_SEVERITY"))).lower()

    action = _text(_first(spec_row, ("action_on_fail", "default_action_on_fail", "ACTION_ON_FAIL"))).lower()
    if not action:
        action = _text(_first(preset, ("default_action_on_fail", "action_on_fail", "DEFAULT_ACTION_ON_FAIL"))).lower()

    params = _json_object(_first(preset, ("params_json", "ParamsJson", "PARAMS_JSON"), None))
    params.update(_json_object(_first(spec_row, ("params_json", "ParamsJson", "PARAMS_JSON"), None)))
    return CleanRulePolicy(preset_id=preset_id, rule_id=rule_id, severity=severity, action_on_fail=action, params=params)
