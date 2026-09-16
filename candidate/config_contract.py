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


@dataclass(frozen=True)
class DatasetColumnContract:
    order: int
    name: str
    alias: str
    data_type: str
    required: bool
    nullable: bool


@dataclass(frozen=True)
class DatasetContract:
    system: str
    logical_file: str
    columns: tuple[DatasetColumnContract, ...]

    @property
    def columns_ordered(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    @property
    def required_columns(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns if column.required)


def _strict_bool(value: Any, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    text = _text(value).casefold()
    truthy = {"1", "true", "verdadero", "si", "sí", "yes"}
    falsy = {"0", "false", "falso", "no"}
    if text in truthy:
        return True
    if text in falsy:
        return False
    raise ValueError(f"{field} must be an explicit boolean value; got {value!r}")


def _positive_integer(value: Any, *, field: str) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer; got {value!r}") from exc
    integer = int(number)
    if number != integer or integer <= 0:
        raise ValueError(f"{field} must be a positive integer; got {value!r}")
    return integer


def resolve_dataset_contract(
    rows: Iterable[Mapping[str, Any]],
    logical_file: str,
    *,
    system: str = "SinergIA",
) -> DatasetContract:
    """Resolve one exact Config/Estructuras dataset contract without inference."""
    system = _text(system)
    logical_file = _text(logical_file)
    if not system or not logical_file:
        raise ValueError("system and logical_file must be non-empty")
    source = [dict(row) for row in rows]
    selected = [
        row for row in source
        if _text(row.get("Sistema")) == system
        and _text(row.get("ArchivoLogico")) == logical_file
    ]
    if not selected:
        raise ValueError(f"Estructuras contract not found for {system!r}/{logical_file!r}")

    required_fields = {
        "Sistema", "ArchivoLogico", "ColumnaOrden", "NombreColumna",
        "AliasCanonico", "TipoDato", "Obligatoria", "PermiteNulos",
    }
    columns: list[DatasetColumnContract] = []
    for row in selected:
        missing_fields = sorted(required_fields.difference(row))
        if missing_fields:
            raise ValueError(f"Estructuras row missing fields: {missing_fields!r}")
        order = _positive_integer(row.get("ColumnaOrden"), field="ColumnaOrden")
        name = _text(row.get("NombreColumna"))
        alias = _text(row.get("AliasCanonico"))
        data_type = _text(row.get("TipoDato"))
        if not name or not data_type:
            raise ValueError(f"Estructuras row {order} requires NombreColumna and TipoDato")
        if data_type.casefold() not in {"texto", "numero", "fecha", "bool"}:
            raise ValueError(f"unsupported TipoDato for {name!r}: {data_type!r}")
        columns.append(DatasetColumnContract(
            order=order, name=name, alias=alias, data_type=data_type,
            required=_strict_bool(row.get("Obligatoria"), field=f"{name}.Obligatoria"),
            nullable=_strict_bool(row.get("PermiteNulos"), field=f"{name}.PermiteNulos"),
        ))

    columns.sort(key=lambda column: column.order)
    orders = [column.order for column in columns]
    if orders != list(range(1, len(columns) + 1)):
        raise ValueError(f"ColumnaOrden must be contiguous 1..N; got {orders!r}")
    names = [column.name for column in columns]
    if len(names) != len(set(names)):
        raise ValueError("duplicate NombreColumna in Estructuras contract")

    token_owner: dict[str, str] = {}
    for column in columns:
        for token in (column.name, column.alias):
            if not token:
                continue
            owner = token_owner.get(token)
            if owner is not None and owner != column.name:
                raise ValueError(f"ambiguous Estructuras canonical token {token!r}")
            token_owner[token] = column.name
    return DatasetContract(system=system, logical_file=logical_file, columns=tuple(columns))


def resolve_dataset_column(
    contract: DatasetContract,
    token: str,
) -> DatasetColumnContract:
    """Resolve one column by exact physical name or exact canonical alias."""
    if not isinstance(contract, DatasetContract):
        raise TypeError("contract must be a DatasetContract")
    wanted = _text(token)
    if not wanted:
        raise ValueError("dataset column token must be non-empty")
    matches = [
        column for column in contract.columns
        if wanted == column.name or (column.alias and wanted == column.alias)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"dataset column token must resolve exactly once: {token!r}; matches={len(matches)}"
        )
    return matches[0]
