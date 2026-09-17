"""Pure PR_04 PROMESAS_ORIGINAL contract validation and fact preparation.

Callers inject the dataframe and Config/Estructuras rows. This module performs no
filesystem, network, Drive, runtime, persistence, payment matching, promise-state
classification, balance, scoring or contact mutations.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import pandas as pd

from .config_contract import resolve_dataset_column, resolve_dataset_contract
from .pr04_base import validate_pr04_base

SYSTEM = "SinergIA"
PROMISES_FILE = "PROMESAS_ORIGINAL"


class PR04PromesasError(ValueError):
    """Fail-closed PROMESAS_ORIGINAL contract or promise-fact error."""


@dataclass(frozen=True)
class PR04PromesasEvidence:
    rows_in: int
    rows_out: int
    unique_documents: int
    unique_credits: int
    unique_document_credit_pairs: int


def _blank_or_non_text(series: pd.Series) -> pd.Series:
    return series.map(lambda value: not isinstance(value, str) or not value.strip())


def prepare_promesas_original(
    dataframe: pd.DataFrame,
    *,
    structure_rows: Iterable[Mapping[str, Any]],
) -> tuple[pd.DataFrame, PR04PromesasEvidence]:
    """Validate PROMESAS_ORIGINAL and preserve its governed source events.

    No uniqueness rule is inferred for promise events. Repeated Documento/Credito
    pairs, including identical source rows, are preserved because CURRENT defines
    those fields as binding keys but does not define a natural event key.
    """
    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("PROMESAS_ORIGINAL must be a pandas DataFrame")

    structures = [dict(row) for row in structure_rows]
    contract = resolve_dataset_contract(structures, PROMISES_FILE, system=SYSTEM)
    validation = validate_pr04_base(
        dataframe,
        structure_rows=structures,
        system=SYSTEM,
        logical_file=PROMISES_FILE,
    )
    if not validation.ok:
        raise PR04PromesasError(
            f"PROMESAS_ORIGINAL boundary invalid: {validation.status}"
        )
    if validation.contract != contract:
        raise PR04PromesasError("PROMESAS_ORIGINAL contract resolution diverged")

    document = resolve_dataset_column(contract, "DocumentoDeIdentidad")
    credit = resolve_dataset_column(contract, "Credito")
    promise_date = resolve_dataset_column(contract, "FechaPromesa")
    promise_value = resolve_dataset_column(contract, "ValorPromesa")
    promise_status = resolve_dataset_column(contract, "EstadoPromesa")

    if bool(_blank_or_non_text(dataframe[document.name]).any()):
        raise PR04PromesasError(
            "PROMESAS_ORIGINAL contains blank/non-text document keys"
        )
    if bool(_blank_or_non_text(dataframe[credit.name]).any()):
        raise PR04PromesasError(
            "PROMESAS_ORIGINAL contains blank/non-text credit keys"
        )
    if bool(_blank_or_non_text(dataframe[promise_status.name]).any()):
        raise PR04PromesasError(
            "PROMESAS_ORIGINAL contains blank/non-text promise status"
        )

    numeric_values = pd.to_numeric(dataframe[promise_value.name], errors="coerce")
    if bool(numeric_values.isna().any()):
        # Normally caught by the exact type/nullability boundary; retain a local
        # fail-closed guard so this invariant cannot silently weaken downstream.
        raise PR04PromesasError(
            "PROMESAS_ORIGINAL ValorPromesa contains invalid numbers"
        )
    if bool((numeric_values < 0).any()):
        raise PR04PromesasError("PROMESAS_ORIGINAL ValorPromesa must be >= 0")

    facts = dataframe.loc[
        :,
        [
            document.name,
            credit.name,
            promise_date.name,
            promise_value.name,
            promise_status.name,
        ],
    ].copy()

    evidence = PR04PromesasEvidence(
        rows_in=int(len(dataframe)),
        rows_out=int(len(facts)),
        unique_documents=int(dataframe[document.name].nunique(dropna=False)),
        unique_credits=int(dataframe[credit.name].nunique(dropna=False)),
        unique_document_credit_pairs=int(
            dataframe.loc[:, [document.name, credit.name]].drop_duplicates().shape[0]
        ),
    )
    return facts, evidence
