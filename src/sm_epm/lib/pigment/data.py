"""Read Pigment data straight into pandas DataFrames.

Every function takes an optional ``client``. When it's omitted, one is built with
``sm_epm.lib.pigment.client.client_from_env()``. Nothing here writes to Pigment.
Failures raise ``sm_epm.lib.errors.EPMError`` subclasses.

- ``view_df`` reads a saved view, laid out as the view is.
- ``list_df``, ``metric_df`` and ``table_df`` read a block's raw data in flat form: dimension
  columns first, then values.
- ``block_df`` picks the right raw export from a block's type, as ``list_blocks()`` reports it.

Extra keyword arguments go to ``pd.read_csv``, for example ``dtype=str`` to keep codes with
leading zeros.
"""

from __future__ import annotations

import io
from typing import Any

import pandas as pd
from pigment import PigmentClient

from sm_epm.lib.errors import RequestError
from sm_epm.lib.pigment.client import client_from_env
from sm_epm.lib.pigment.errors import SERVICE, pigment_errors

# Pigment's own defaults are semicolons, technical headers and a UTF-8 BOM.
RAW_EXPORT_FORMAT = {
    'fieldDelimiter': 'Comma',
    'dateFormat': 'Iso8601',
    'encoding': 'Utf8WithoutBom',
    'friendlyHeaders': True,
}

# Block type (from list_blocks) -> raw export kind.
BLOCK_EXPORTS = {
    'DimensionList': 'list',
    'TransactionList': 'list',
    'Metric': 'metric',
    'Table': 'table',
}


@pigment_errors
def view_df(view_id: str, *, client: PigmentClient | None = None, **read_kwargs: Any) -> pd.DataFrame:
    client = client or client_from_env()
    return _read_csv(client.export_view(view_id, date_format='Iso8601', field_delimiter='Comma'), read_kwargs)


@pigment_errors
def list_df(
    list_id: str,
    *,
    client: PigmentClient | None = None,
    options: dict[str, Any] | None = None,
    **read_kwargs: Any,
) -> pd.DataFrame:
    """Read a dimension or transaction list. ``options`` adds export body fields, for example
    ``{'propertyTechnicalNames': [...]}``."""
    return _raw('list', list_id, client, options, read_kwargs)


@pigment_errors
def metric_df(
    metric_id: str,
    *,
    client: PigmentClient | None = None,
    options: dict[str, Any] | None = None,
    **read_kwargs: Any,
) -> pd.DataFrame:
    """Read a metric. ``options`` adds export body fields, for example ``{'scenarios': [...]}`` or
    ``{'exportFilter': {...}}``."""
    return _raw('metric', metric_id, client, options, read_kwargs)


@pigment_errors
def table_df(
    table_id: str,
    *,
    client: PigmentClient | None = None,
    options: dict[str, Any] | None = None,
    **read_kwargs: Any,
) -> pd.DataFrame:
    """Read a table. ``options`` adds export body fields, for example ``{'metrics': [...]}``."""
    return _raw('table', table_id, client, options, read_kwargs)


@pigment_errors
def block_df(
    block_id: str,
    block_type: str,
    *,
    client: PigmentClient | None = None,
    options: dict[str, Any] | None = None,
    **read_kwargs: Any,
) -> pd.DataFrame:
    """Read any list, metric or table block, given its ``type`` from ``list_blocks()``."""
    kind = BLOCK_EXPORTS.get(block_type)
    if kind is None:
        raise RequestError(
            f'block type {block_type!r} has no raw export; expected one of {sorted(BLOCK_EXPORTS)}', service=SERVICE
        )
    return _raw(kind, block_id, client, options, read_kwargs)


def _raw(
    kind: str,
    block_id: str,
    client: PigmentClient | None,
    options: dict[str, Any] | None,
    read_kwargs: dict[str, Any],
) -> pd.DataFrame:
    client = client or client_from_env()
    export = getattr(client, f'export_{kind}')
    return _read_csv(export(block_id, **(RAW_EXPORT_FORMAT | (options or {}))), read_kwargs)


def _read_csv(text: str, read_kwargs: dict[str, Any]) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(text.lstrip('﻿')), **read_kwargs)
