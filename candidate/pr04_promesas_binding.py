"""Pure PR_04 binding of validated promise events to the governed credit base.

Inputs are injected DataFrames plus Config/Estructuras rows. The module performs no
I/O, persistence, promise-state classification, payment matching, fulfillment,
balance mutation, eligibility decision, scoring or publication.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import pandas as pd

from .config_contract import resolve_dataset_column, resolve_dataset_contract
from .pr04_base import validate_pr04_base
from .pr04_promesas import prepare_promesas_original

SYSTEM = "SinergIA"
BASE_FILE = "IN_SISTECREDITO"
PROMISES_FILE = "PROMESAS_ORIGINAL"


class PR04PromesasBindingError(ValueError):
    """Fail-closed error for unsafe or contradictory promise-to-credit binding."""


@dataclass(frozen=True)
class PromiseCreditRecord:
    """One promise event bound to its exact governed base key.

    promise_date, promise_value and promise_status carry the validated source
    values unchanged: binding adds identity and source position only, with no
    normalization, coercion, classification or aggregation.
    """

    document: str
    credit: str
    source_row_position: int
    promise_date: Any
    promise_value: Any
    promise_status: str


@dataclass(frozen=True)
class PR04PromesasBindingEvidence:
    promise_rows_in: int
    promise_rows_bound: int
    promise_rows_unmatched: int
    bound_credit_keys: int
    unmatched_credits: tuple[str, ...]
    unmatched_row_positions: tuple[int, ...]


def _required_key(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PR04PromesasBindingError(f"{label} must be a non-blank text key")
    return value


def bind_promesas_to_credit_base(
    base: pd.DataFrame,
    promesas: pd.DataFrame,
    *,
    structure_rows: Iterable[Mapping[str, Any]],
) -> tuple[tuple[PromiseCreditRecord, ...], PR04PromesasBindingEvidence]:
    """Bind governed promise events to the governed credit base without mutations.

    Every promise event is preserved in source order; no event key is inferred and
    events are never deduplicated, aggregated or classified. A promise whose
    Credito is absent from the base is recorded as unmatched/orphan evidence and
    is not bound. A promise whose Credito exists under a different
    DocumentoDeIdentidad is a fail-closed contradiction.
    """
    structures = [dict(row) for row in structure_rows]

    base_validation = validate_pr04_base(
        base,
        structure_rows=structures,
        system=SYSTEM,
        logical_file=BASE_FILE,
    )
    if not base_validation.ok:
        raise PR04PromesasBindingError(
            f"IN_SISTECREDITO boundary invalid: {base_validation.status}"
        )

    promise_facts, _ = prepare_promesas_original(
        promesas,
        structure_rows=structures,
    )

    base_contract = resolve_dataset_contract(structures, BASE_FILE, system=SYSTEM)
    promises_contract = resolve_dataset_contract(structures, PROMISES_FILE, system=SYSTEM)
    base_document = resolve_dataset_column(base_contract, "DocumentoDeIdentidad")
    base_credit = resolve_dataset_column(base_contract, "Credito")
    promise_document = resolve_dataset_column(promises_contract, "DocumentoDeIdentidad")
    promise_credit = resolve_dataset_column(promises_contract, "Credito")
    promise_date = resolve_dataset_column(promises_contract, "FechaPromesa")
    promise_value = resolve_dataset_column(promises_contract, "ValorPromesa")
    promise_status = resolve_dataset_column(promises_contract, "EstadoPromesa")

    base_positions: dict[tuple[str, str], int] = {}
    credit_documents: dict[str, list[str]] = {}
    for position, (_, row) in enumerate(base.iterrows()):
        document = _required_key(row[base_document.name], label="base DocumentoDeIdentidad")
        credit = _required_key(row[base_credit.name], label="base Credito")
        key = (document, credit)
        if key in base_positions:
            raise PR04PromesasBindingError(
                f"duplicate IN_SISTECREDITO key DocumentoDeIdentidad+Credito: {key!r}"
            )
        base_positions[key] = position
        credit_documents.setdefault(credit, []).append(document)

    records: list[PromiseCreditRecord] = []
    unmatched_positions: list[int] = []
    unmatched_credits: list[str] = []
    seen_unmatched: set[str] = set()

    for position in range(len(promise_facts)):
        row = promise_facts.iloc[position]
        document = _required_key(
            row[promise_document.name],
            label="promise DocumentoDeIdentidad",
        )
        credit = _required_key(row[promise_credit.name], label="promise Credito")
        if credit not in credit_documents:
            unmatched_positions.append(position)
            if credit not in seen_unmatched:
                unmatched_credits.append(credit)
                seen_unmatched.add(credit)
            continue
        key = (document, credit)
        if key not in base_positions:
            raise PR04PromesasBindingError(
                "promise DocumentoDeIdentidad contradicts its Credito binding: "
                f"credito={credit!r}, documento={document!r}, "
                f"candidates={tuple(credit_documents[credit])!r}"
            )
        records.append(PromiseCreditRecord(
            document=document,
            credit=credit,
            source_row_position=position,
            promise_date=row[promise_date.name],
            promise_value=row[promise_value.name],
            promise_status=row[promise_status.name],
        ))

    evidence = PR04PromesasBindingEvidence(
        promise_rows_in=len(promise_facts),
        promise_rows_bound=len(records),
        promise_rows_unmatched=len(unmatched_positions),
        bound_credit_keys=len({(record.document, record.credit) for record in records}),
        unmatched_credits=tuple(unmatched_credits),
        unmatched_row_positions=tuple(unmatched_positions),
    )
    return tuple(records), evidence
