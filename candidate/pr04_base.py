"""Pure PR_04 base boundary validation against Config/Estructuras.

No network, filesystem, Drive, runtime activation, publication or mutation occurs here.
The caller injects both the dataframe and Estructuras rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from numbers import Number
from typing import Any, Iterable, Mapping

import pandas as pd

from .config_contract import DatasetContract, resolve_dataset_contract

PR04_SYSTEM = "SinergIA"
PR04_LOGICAL_FILE = "IN_SISTECREDITO"


@dataclass(frozen=True)
class PR04BaseValidation:
    ok: bool
    status: str
    contract: DatasetContract
    actual_columns: tuple[str, ...]
    missing_columns: tuple[str, ...]
    extra_columns: tuple[str, ...]
    required_missing: tuple[str, ...]
    order_ok: bool
    null_violations: Mapping[str, int]
    type_violations: Mapping[str, int]


def _invalid_type_count(series: pd.Series, data_type: str) -> int:
    values = series[~series.isna()]
    if values.empty:
        return 0
    kind = data_type.casefold()
    if kind == "texto":
        return sum(not isinstance(value, str) for value in values.tolist())
    if kind == "numero":
        invalid_bool = values.map(lambda value: isinstance(value, bool))
        parsed = pd.to_numeric(values.where(~invalid_bool), errors="coerce")
        return int(parsed.isna().sum() + invalid_bool.sum())
    if kind == "fecha":
        if pd.api.types.is_datetime64_any_dtype(values.dtype):
            return 0
        native = values.map(lambda value: isinstance(value, (date, datetime, pd.Timestamp)))
        remaining = values[~native]
        parsed = pd.to_datetime(remaining, errors="coerce", dayfirst=True) if not remaining.empty else remaining
        return int(parsed.isna().sum())
    if kind == "bool":
        return sum(not isinstance(value, bool) for value in values.tolist())
    raise ValueError(f"unsupported TipoDato: {data_type!r}")


def validate_pr04_base(
    dataframe: pd.DataFrame,
    *,
    structure_rows: Iterable[Mapping[str, Any]],
    system: str = PR04_SYSTEM,
    logical_file: str = PR04_LOGICAL_FILE,
) -> PR04BaseValidation:
    """Validate the exact PR_03 -> PR_04 dataset boundary without changing data."""
    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("PR_04 base must be a pandas DataFrame")
    contract = resolve_dataset_contract(structure_rows, logical_file, system=system)
    expected = contract.columns_ordered
    actual = tuple(str(column) for column in dataframe.columns)
    expected_set = set(expected)
    actual_set = set(actual)
    missing = tuple(column for column in expected if column not in actual_set)
    extra = tuple(column for column in actual if column not in expected_set)
    required_missing = tuple(column for column in contract.required_columns if column not in actual_set)
    order_ok = actual == expected

    null_violations: dict[str, int] = {}
    type_violations: dict[str, int] = {}
    for column in contract.columns:
        if column.name not in dataframe.columns:
            continue
        series = dataframe[column.name]
        if not column.nullable:
            count = int(series.isna().sum())
            if count:
                null_violations[column.name] = count
        invalid = _invalid_type_count(series, column.data_type)
        if invalid:
            type_violations[column.name] = invalid

    if missing or extra or not order_ok:
        status = "FAIL_SCHEMA"
    elif null_violations:
        status = "FAIL_NULLABILITY"
    elif type_violations:
        status = "FAIL_TYPE"
    else:
        status = "PASS"
    return PR04BaseValidation(
        ok=(status == "PASS"), status=status, contract=contract, actual_columns=actual,
        missing_columns=missing, extra_columns=extra, required_missing=required_missing,
        order_ok=order_ok, null_violations=null_violations, type_violations=type_violations,
    )
