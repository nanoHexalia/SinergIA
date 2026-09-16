"""Pure PR_04 MejorGest builder from injected TRAZA and Config authority."""
from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral, Real
from typing import Any, Iterable, Mapping
import math

import pandas as pd

from .config_contract import (
    DatasetContract,
    resolve_dataset_column,
    resolve_dataset_contract,
)
from .pr04_base import validate_pr04_base

SYSTEM = "SinergIA"
TRAZA_FILE = "TRAZA"
BASE_FILE = "IN_SISTECREDITO"
OUTPUT_FILE = "CONSOLIDADO_MEJORGEST"


class PR04MejorGestError(ValueError):
    """Fail-closed PR_04 MejorGest contract or data error."""


@dataclass(frozen=True)
class PR04MejorGestEvidence:
    rows_in: int
    rows_out: int
    documents: int
    months: int
    mapped_codes: int


def _column_name(contract: DatasetContract, token: str) -> str:
    return resolve_dataset_column(contract, token).name


def _require_exact_schema(
    dataframe: pd.DataFrame,
    contract: DatasetContract,
    *,
    role: str,
) -> None:
    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError(f"{role} must be a pandas DataFrame")
    actual = tuple(str(column) for column in dataframe.columns)
    if actual != contract.columns_ordered:
        raise PR04MejorGestError(
            f"{role} schema must exactly match Config/Estructuras; "
            f"expected={contract.columns_ordered!r}; actual={actual!r}"
        )


def _code_token(value: Any) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        raise PR04MejorGestError("CAP_TIPIFICACION/COD Tipi cannot be null")
    if isinstance(value, bool):
        raise PR04MejorGestError("CAP_TIPIFICACION/COD Tipi cannot be boolean")
    if isinstance(value, Integral):
        return str(int(value))
    if isinstance(value, Real):
        number = float(value)
        if not math.isfinite(number) or not number.is_integer():
            raise PR04MejorGestError(f"invalid numeric tipification code: {value!r}")
        return str(int(number))
    token = str(value).strip()
    if not token:
        raise PR04MejorGestError("CAP_TIPIFICACION/COD Tipi cannot be blank")
    return token


def _build_arbol_map(
    arbol_rows: Iterable[Mapping[str, Any]],
) -> dict[str, tuple[float, str, str]]:
    source = [dict(row) for row in arbol_rows]
    if not source:
        raise PR04MejorGestError("ArbolHeuristico cannot be empty when TRAZA has rows")
    required = {"COD Tipi", "Tipo Contacto", "Tipificacion", "Prioridad"}
    result: dict[str, tuple[float, str, str]] = {}
    for index, row in enumerate(source, start=1):
        missing = sorted(required.difference(row))
        if missing:
            raise PR04MejorGestError(
                f"ArbolHeuristico row {index} missing fields: {missing!r}"
            )
        code = _code_token(row["COD Tipi"])
        if code in result:
            raise PR04MejorGestError(f"duplicate ArbolHeuristico COD Tipi: {code!r}")
        raw_priority = row["Prioridad"]
        if isinstance(raw_priority, bool):
            raise PR04MejorGestError(f"invalid Prioridad for COD Tipi {code!r}")
        try:
            priority = float(raw_priority)
        except (TypeError, ValueError) as exc:
            raise PR04MejorGestError(
                f"invalid Prioridad for COD Tipi {code!r}: {raw_priority!r}"
            ) from exc
        if not math.isfinite(priority):
            raise PR04MejorGestError(f"invalid Prioridad for COD Tipi {code!r}")
        raw_contact = row["Tipo Contacto"]
        raw_tipification = row["Tipificacion"]
        if raw_contact is None or (not isinstance(raw_contact, str) and pd.isna(raw_contact)):
            raise PR04MejorGestError(f"blank ArbolHeuristico mapping for COD Tipi {code!r}")
        if raw_tipification is None or (not isinstance(raw_tipification, str) and pd.isna(raw_tipification)):
            raise PR04MejorGestError(f"blank ArbolHeuristico mapping for COD Tipi {code!r}")
        contact_type = str(raw_contact).strip()
        tipification = str(raw_tipification).strip()
        if not contact_type or not tipification:
            raise PR04MejorGestError(f"blank ArbolHeuristico mapping for COD Tipi {code!r}")
        result[code] = (priority, contact_type, tipification)
    return result


def build_mejorgest_from_traza(
    df_traza: pd.DataFrame,
    df_base: pd.DataFrame,
    *,
    structure_rows: Iterable[Mapping[str, Any]],
    arbol_rows: Iterable[Mapping[str, Any]],
) -> tuple[pd.DataFrame, PR04MejorGestEvidence]:
    """Build Config-governed CONSOLIDADO_MEJORGEST with no side effects."""
    structures = [dict(row) for row in structure_rows]
    trace_contract = resolve_dataset_contract(structures, TRAZA_FILE, system=SYSTEM)
    base_contract = resolve_dataset_contract(structures, BASE_FILE, system=SYSTEM)
    output_contract = resolve_dataset_contract(structures, OUTPUT_FILE, system=SYSTEM)

    _require_exact_schema(df_traza, trace_contract, role="TRAZA")
    base_validation = validate_pr04_base(df_base, structure_rows=structures)
    if not base_validation.ok:
        raise PR04MejorGestError(
            f"IN_SISTECREDITO boundary invalid: {base_validation.status}"
        )
    if base_validation.contract != base_contract:
        raise PR04MejorGestError("IN_SISTECREDITO contract resolution diverged")

    trace_doc = _column_name(trace_contract, "InDocumentoDeIdentidad")
    trace_code = _column_name(trace_contract, "CapTipificacion")
    trace_date = _column_name(trace_contract, "CapFecha")
    base_doc = _column_name(base_contract, "DocumentoDeIdentidad")

    output_columns = {
        "doc": _column_name(output_contract, "DocumentoDeIdentidad"),
        "month": _column_name(output_contract, "FechaMes"),
        "priority": _column_name(output_contract, "MinPrioridad"),
        "contact": _column_name(output_contract, "TipoContacto"),
        "tipification": _column_name(output_contract, "Tipificacion"),
        "bd": _column_name(output_contract, "Bd"),
    }
    if set(output_columns.values()) != set(output_contract.columns_ordered):
        raise PR04MejorGestError(
            "CONSOLIDADO_MEJORGEST must contain exactly the six governed columns"
        )

    base_docs_raw = df_base[base_doc]
    bad_base_doc = base_docs_raw.map(
        lambda value: not isinstance(value, str) or not value.strip()
    )
    if bool(bad_base_doc.any()):
        raise PR04MejorGestError("IN_SISTECREDITO contains blank/non-text document keys")

    if df_traza.empty:
        empty = pd.DataFrame(columns=output_contract.columns_ordered)
        return empty, PR04MejorGestEvidence(
            rows_in=0, rows_out=0, documents=0, months=0, mapped_codes=0
        )

    docs = df_traza[trace_doc]
    bad_doc = docs.map(lambda value: not isinstance(value, str) or not value.strip())
    if bool(bad_doc.any()):
        raise PR04MejorGestError("TRAZA contains blank/non-text document keys")

    raw_dates = df_traza[trace_date]
    parsed_dates = pd.to_datetime(raw_dates, errors="coerce", format="ISO8601")
    if bool(raw_dates.isna().any()) or bool(parsed_dates.isna().any()):
        raise PR04MejorGestError("TRAZA CAP_FECHA contains null or invalid dates")
    if not pd.api.types.is_datetime64_any_dtype(parsed_dates.dtype):
        raise PR04MejorGestError("TRAZA CAP_FECHA did not resolve deterministically")

    arbol_map = _build_arbol_map(arbol_rows)
    codes = df_traza[trace_code].map(_code_token)
    unknown = sorted(set(codes.tolist()).difference(arbol_map))
    if unknown:
        raise PR04MejorGestError(
            f"TRAZA contains unmapped CAP_TIPIFICACION codes: {unknown!r}"
        )

    work = pd.DataFrame(index=df_traza.index)
    work["_doc"] = docs
    work["_date"] = parsed_dates
    work["_month"] = parsed_dates.dt.to_period("M").dt.to_timestamp()
    work["_code"] = codes
    work["_priority"] = codes.map(lambda code: arbol_map[code][0])
    work["_contact"] = codes.map(lambda code: arbol_map[code][1])
    work["_tipification"] = codes.map(lambda code: arbol_map[code][2])

    group_keys = ["_doc", "_month"]
    work["_best_priority"] = work.groupby(group_keys, sort=False)["_priority"].transform("min")
    candidates = work[work["_priority"] == work["_best_priority"]].copy()
    candidates["_best_date"] = candidates.groupby(group_keys, sort=False)["_date"].transform("max")
    finalists = candidates[candidates["_date"] == candidates["_best_date"]].copy()

    ambiguous = finalists.duplicated(group_keys, keep=False)
    if bool(ambiguous.any()):
        keys = finalists.loc[ambiguous, group_keys].drop_duplicates()
        sample = [tuple(row) for row in keys.head(5).itertuples(index=False, name=None)]
        raise PR04MejorGestError(
            f"ambiguous best management after priority/date tie: {sample!r}"
        )

    base_docs = set(base_docs_raw.tolist())
    finalists["_bd"] = finalists["_doc"].map(
        lambda document: "EnBD" if document in base_docs else "FueraBD"
    )
    finalists.sort_values(group_keys, kind="mergesort", inplace=True)

    data = {
        output_columns["doc"]: finalists["_doc"].tolist(),
        output_columns["month"]: finalists["_month"].tolist(),
        output_columns["priority"]: finalists["_priority"].tolist(),
        output_columns["contact"]: finalists["_contact"].tolist(),
        output_columns["tipification"]: finalists["_tipification"].tolist(),
        output_columns["bd"]: finalists["_bd"].tolist(),
    }
    output = pd.DataFrame(data).loc[:, output_contract.columns_ordered]
    if len(output) != len(output.drop_duplicates(subset=[output_columns["doc"], output_columns["month"]])):
        raise PR04MejorGestError("CONSOLIDADO_MEJORGEST grain violation")

    evidence = PR04MejorGestEvidence(
        rows_in=int(len(df_traza)),
        rows_out=int(len(output)),
        documents=int(output[output_columns["doc"]].nunique(dropna=False)),
        months=int(output[output_columns["month"]].nunique(dropna=False)),
        mapped_codes=int(codes.nunique(dropna=False)),
    )
    return output, evidence
