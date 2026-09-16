"""Pure PR_04 PAGOS_ORIGINAL contract validation and fact preparation.

Callers inject the dataframe and Config/Estructuras rows. This module performs no
filesystem, network, Drive, runtime, persistence, balance or contact mutations.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import pandas as pd

from .config_contract import resolve_dataset_column, resolve_dataset_contract
from .pr04_base import validate_pr04_base

SYSTEM = "SinergIA"
PAGOS_FILE = "PAGOS_ORIGINAL"


class PR04PagosError(ValueError):
    """Fail-closed PAGOS_ORIGINAL contract or payment-fact error."""


@dataclass(frozen=True)
class PR04PagosEvidence:
    rows_in: int
    unique_credits: int
    null_dates: int
    null_values: int


def prepare_pagos_original(
    dataframe: pd.DataFrame,
    *,
    structure_rows: Iterable[Mapping[str, Any]],
) -> tuple[pd.DataFrame, PR04PagosEvidence]:
    """Validate PAGOS_ORIGINAL and return immutable payment facts for later joins."""
    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("PAGOS_ORIGINAL must be a pandas DataFrame")

    structures = [dict(row) for row in structure_rows]
    contract = resolve_dataset_contract(structures, PAGOS_FILE, system=SYSTEM)
    validation = validate_pr04_base(
        dataframe,
        structure_rows=structures,
        system=SYSTEM,
        logical_file=PAGOS_FILE,
    )
    if not validation.ok:
        raise PR04PagosError(f"PAGOS_ORIGINAL boundary invalid: {validation.status}")
    if validation.contract != contract:
        raise PR04PagosError("PAGOS_ORIGINAL contract resolution diverged")

    credit = resolve_dataset_column(contract, "Credito")
    payment_date = resolve_dataset_column(contract, "FechaPago")
    payment_value = resolve_dataset_column(contract, "ValorRecibo")

    credits = dataframe[credit.name]
    bad_credit = credits.map(
        lambda value: not isinstance(value, str) or not value.strip()
    )
    if bool(bad_credit.any()):
        raise PR04PagosError("PAGOS_ORIGINAL contains blank/non-text credit keys")

    non_null_values = dataframe[payment_value.name].dropna()
    if not non_null_values.empty:
        numeric_values = pd.to_numeric(non_null_values, errors="coerce")
        if bool(numeric_values.isna().any()):
            raise PR04PagosError("PAGOS_ORIGINAL ValorRecibo contains invalid numbers")
        if bool((numeric_values < 0).any()):
            raise PR04PagosError("PAGOS_ORIGINAL ValorRecibo must be >= 0")

    facts = dataframe.loc[:, [credit.name, payment_date.name, payment_value.name]].copy()
    duplicate_mask = facts.duplicated(
        subset=[credit.name, payment_date.name, payment_value.name],
        keep=False,
    )
    if bool(duplicate_mask.any()):
        raise PR04PagosError(
            "PAGOS_ORIGINAL contains ambiguous duplicate payment facts: "
            f"rows={int(duplicate_mask.sum())}"
        )

    evidence = PR04PagosEvidence(
        rows_in=int(len(dataframe)),
        unique_credits=int(credits.nunique(dropna=False)),
        null_dates=int(dataframe[payment_date.name].isna().sum()),
        null_values=int(dataframe[payment_value.name].isna().sum()),
    )
    return facts, evidence
