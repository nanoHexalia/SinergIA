"""Pure PR_04 binding of validated payment facts to the governed credit base.

Inputs are injected DataFrames plus Config/Estructuras rows. The module performs no
I/O, persistence, balance mutation, eligibility decision, scoring or publication.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from numbers import Number
from typing import Any, Iterable, Mapping

import pandas as pd

from .config_contract import (
    DatasetColumnContract,
    DatasetContract,
    resolve_dataset_column,
    resolve_dataset_contract,
)
from .pr04_base import validate_pr04_base
from .pr04_pagos import prepare_pagos_original

SYSTEM = "SinergIA"
BASE_FILE = "IN_SISTECREDITO"
PAGOS_FILE = "PAGOS_ORIGINAL"


class PR04PagosBindingError(ValueError):
    """Fail-closed error for unsafe or contradictory payment-to-credit binding."""

@dataclass(frozen=True)
class CreditPaymentAggregate:
    document: str
    credit: str
    payment_count: int
    last_payment_date: pd.Timestamp | None
    total_paid: Number | None


@dataclass(frozen=True)
class PR04PagosBindingEvidence:
    payment_rows_in: int
    payment_rows_bound: int
    payment_rows_unmatched: int
    aggregated_credit_keys: int
    unmatched_credits: tuple[str, ...]
    unmatched_row_positions: tuple[int, ...]


def _optional_exact_column(
    contract: DatasetContract,
    token: str,
) -> DatasetColumnContract | None:
    matches = [
        column for column in contract.columns
        if token == column.name or (column.alias and token == column.alias)
    ]
    if len(matches) > 1:
        raise PR04PagosBindingError(
            f"ambiguous exact Config token {token!r}; matches={len(matches)}"
        )
    return matches[0] if matches else None

def _required_key(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PR04PagosBindingError(f"{label} must be a non-blank text key")
    return value


def _optional_document(value: Any) -> str | None:
    if pd.isna(value):
        return None
    if not isinstance(value, str):
        raise PR04PagosBindingError("payment DocumentoDeIdentidad must be text or null")
    return value if value.strip() else None


def _as_timestamp(value: Any) -> pd.Timestamp | None:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value
    if isinstance(value, (datetime, date)):
        return pd.Timestamp(value)
    try:
        return pd.Timestamp(pd.to_datetime(value, errors="raise", format="mixed", dayfirst=True))
    except (TypeError, ValueError) as exc:
        raise PR04PagosBindingError(f"invalid payment date during aggregation: {value!r}") from exc


def _sum_observed(values: list[Any]) -> Number | None:
    observed = [value for value in values if not pd.isna(value)]
    if not observed:
        return None
    total = sum(observed)
    return total.item() if hasattr(total, "item") else total

def bind_pagos_to_credit_base(
    base: pd.DataFrame,
    pagos: pd.DataFrame,
    *,
    structure_rows: Iterable[Mapping[str, Any]],
) -> tuple[tuple[CreditPaymentAggregate, ...], PR04PagosBindingEvidence]:
    """Bind governed payment events to the governed credit base without mutations."""
    structures = [dict(row) for row in structure_rows]

    base_validation = validate_pr04_base(
        base,
        structure_rows=structures,
        system=SYSTEM,
        logical_file=BASE_FILE,
    )
    if not base_validation.ok:
        raise PR04PagosBindingError(
            f"IN_SISTECREDITO boundary invalid: {base_validation.status}"
        )

    payment_facts, _ = prepare_pagos_original(
        pagos,
        structure_rows=structures,
    )

    base_contract = resolve_dataset_contract(structures, BASE_FILE, system=SYSTEM)
    pagos_contract = resolve_dataset_contract(structures, PAGOS_FILE, system=SYSTEM)
    base_document = resolve_dataset_column(base_contract, "DocumentoDeIdentidad")
    base_credit = resolve_dataset_column(base_contract, "Credito")
    payment_credit = resolve_dataset_column(pagos_contract, "Credito")
    payment_date = resolve_dataset_column(pagos_contract, "FechaPago")
    payment_value = resolve_dataset_column(pagos_contract, "ValorRecibo")
    payment_document = _optional_exact_column(pagos_contract, "DocumentoDeIdentidad")

    base_positions: dict[tuple[str, str], int] = {}
    credit_documents: dict[str, list[str]] = {}
    for position, (_, row) in enumerate(base.iterrows()):
        document = _required_key(row[base_document.name], label="base DocumentoDeIdentidad")
        credit = _required_key(row[base_credit.name], label="base Credito")
        key = (document, credit)
        if key in base_positions:
            raise PR04PagosBindingError(
                f"duplicate IN_SISTECREDITO key DocumentoDeIdentidad+Credito: {key!r}"
            )
        base_positions[key] = position
        credit_documents.setdefault(credit, []).append(document)

    bound_rows: dict[tuple[str, str], list[int]] = {}
    unmatched_positions: list[int] = []
    unmatched_credits: list[str] = []
    seen_unmatched: set[str] = set()

    for position in range(len(payment_facts)):
        credit = _required_key(
            payment_facts.iloc[position][payment_credit.name],
            label="payment Credito",
        )
        candidates = credit_documents.get(credit)
        if not candidates:
            unmatched_positions.append(position)
            if credit not in seen_unmatched:
                unmatched_credits.append(credit)
                seen_unmatched.add(credit)
            continue

        document_value = None
        if payment_document is not None:
            document_value = _optional_document(pagos.iloc[position][payment_document.name])

        if document_value is not None:
            if document_value not in candidates:
                raise PR04PagosBindingError(
                    "payment DocumentoDeIdentidad contradicts its Credito binding: "
                    f"credito={credit!r}, documento={document_value!r}, candidates={tuple(candidates)!r}"
                )
            document = document_value
        else:
            unique_candidates = tuple(dict.fromkeys(candidates))
            if len(unique_candidates) != 1:
                raise PR04PagosBindingError(
                    "ambiguous payment binding without DocumentoDeIdentidad: "
                    f"credito={credit!r}, candidates={unique_candidates!r}"
                )
            document = unique_candidates[0]

        bound_rows.setdefault((document, credit), []).append(position)

    aggregates: list[CreditPaymentAggregate] = []
    for key in sorted(bound_rows, key=lambda item: base_positions[item]):
        positions = bound_rows[key]
        dates = [
            _as_timestamp(payment_facts.iloc[position][payment_date.name])
            for position in positions
        ]
        observed_dates = [value for value in dates if value is not None]
        try:
            last_payment_date = max(observed_dates) if observed_dates else None
        except TypeError as exc:
            raise PR04PagosBindingError(
                f"incomparable payment dates for base key {key!r}"
            ) from exc

        values = [payment_facts.iloc[position][payment_value.name] for position in positions]
        aggregates.append(CreditPaymentAggregate(
            document=key[0],
            credit=key[1],
            payment_count=len(positions),
            last_payment_date=last_payment_date,
            total_paid=_sum_observed(values),
        ))

    bound_count = sum(len(positions) for positions in bound_rows.values())
    evidence = PR04PagosBindingEvidence(
        payment_rows_in=len(payment_facts),
        payment_rows_bound=bound_count,
        payment_rows_unmatched=len(unmatched_positions),
        aggregated_credit_keys=len(aggregates),
        unmatched_credits=tuple(unmatched_credits),
        unmatched_row_positions=tuple(unmatched_positions),
    )
    return tuple(aggregates), evidence
