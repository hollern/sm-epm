"""Read Anaplan data straight into pandas DataFrames.

Every function takes an optional ``client``. When it's omitted, one is built with
``sm_epm.lib.anaplan.client.client_from_env()``, which points at the default model in ``.env`` (production).
Pass ``client_from_env(model_id=...)`` to read from another model. Nothing here writes to Anaplan.
Failures raise ``sm_epm.lib.errors.EPMError`` subclasses.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from typing import Any

import anaplan_sdk
import pandas as pd

from sm_epm.lib.anaplan.client import client_from_env
from sm_epm.lib.anaplan.errors import SERVICE, anaplan_errors
from sm_epm.lib.errors import DataFormatError, NotFoundError

_CSV_SEPARATORS = {'text/csv': ',', 'text/plain': '\t'}


@anaplan_errors
def view_df(
    view_id: int,
    *,
    client: anaplan_sdk.Client | None = None,
    pages: Sequence[tuple[int, int]] | None = None,
    max_rows: int | None = None,
    long: bool = False,
) -> pd.DataFrame:
    """Read a module or saved view as it's laid out in Anaplan.

    Rows are indexed by the view's row dimensions and columns by its column dimensions, so a
    module with months across the top comes back with one column per month. Anaplan caps a single
    read at 1,000,000 cells.

    Args:
        view_id: A module ID, saved view ID or line item ID.
        pages: ``(dimension_id, item_id)`` pairs that override the view's default page selection.
        max_rows: Cap on the number of data rows.
        long: Return one row per cell instead, with a column per dimension and a ``value`` column.

    The page selection that was read is stored in ``df.attrs['pages']`` as ``{dimension: item}``.
    """
    client = client or client_from_env()
    info = client.tr.get_view_info(view_id)
    data = client.tr.get_view_data(view_id, pages=list(pages) if pages else None, max_rows=max_rows)

    rows = data.get('rows', [])
    df = pd.DataFrame(
        [r['cells'] for r in rows],
        index=_axis([r['rowCoordinates'] for r in rows], [d.name for d in info.rows]),
        columns=_axis(data.get('columnCoordinates', []), [d.name for d in info.columns]),
    )
    df = _coerce_numeric(df)
    df.attrs['pages'] = dict(zip((d.name for d in info.pages), data.get('pages', [])))
    if long:
        attrs = df.attrs
        df = df.stack(list(range(df.columns.nlevels))).rename('value').reset_index()
        df.attrs = attrs
    return df


@anaplan_errors
def export_df(export_id: int, *, client: anaplan_sdk.Client | None = None, **read_kwargs: Any) -> pd.DataFrame:
    """Run a bulk export action and read its file.

    Runs the export (which doesn't change model data), downloads the file and parses it according
    to the export's format: CSV, tab-delimited text or Excel. For ``GRID_CURRENT_PAGE`` exports the
    first line is the page selection, not data. It's skipped and kept in ``df.attrs['pages']``.

    Extra keyword arguments go to ``pd.read_csv`` / ``pd.read_excel``, for example
    ``dtype=str`` to keep codes with leading zeros.
    """
    client = client or client_from_env()
    export = next((e for e in client.get_exports() if e.id == export_id), None)
    if export is None:
        raise NotFoundError(f'no export {export_id} in this model', service=SERVICE)
    content = client.export_and_download(export_id)
    has_page_line = export.layout == 'GRID_CURRENT_PAGE'

    if 'spreadsheetml' in export.format:
        df = pd.read_excel(io.BytesIO(content), header=1 if has_page_line else 0, **read_kwargs)
        pages = list(pd.read_excel(io.BytesIO(content), header=None, nrows=1).iloc[0].dropna()) if has_page_line else []
    else:
        sep = _CSV_SEPARATORS.get(export.format)
        if sep is None:
            raise DataFormatError(f'export {export_id} has unsupported format {export.format!r}', service=SERVICE)
        text = content.decode(export.encoding or 'utf-8-sig').lstrip('﻿')
        pages = []
        if has_page_line:
            first, _, text = text.partition('\n')
            pages = next(csv.reader([first], delimiter=sep))
        df = pd.read_csv(io.StringIO(text), sep=sep, **read_kwargs)
    df.attrs['pages'] = pages
    return df


@anaplan_errors
def list_items_df(list_id: int, *, client: anaplan_sdk.Client | None = None) -> pd.DataFrame:
    """Read every item in a list: ``id``, ``name``, ``code``, ``parent``, ``parentId``, then one
    column per property (named as in Anaplan) and one ``subsets.<name>`` column per subset."""
    client = client or client_from_env()
    items = client.tr.get_list_items(list_id, return_raw=True)
    df = pd.json_normalize(items)
    renames = {c: c.removeprefix('properties.') for c in df.columns if c.startswith('properties.')}
    if len(set(renames.values()) | (set(df.columns) - set(renames))) == len(df.columns):
        df = df.rename(columns=renames)
    return df


def _axis(coordinates: Sequence[Sequence[str]], names: list[str]) -> pd.Index:
    tuples = [tuple(c) for c in coordinates]
    width = len(tuples[0]) if tuples else len(names)
    level_names = names if len(names) == width else None
    if width == 1:
        return pd.Index([t[0] for t in tuples], name=level_names[0] if level_names else None)
    return pd.MultiIndex.from_tuples(tuples, names=level_names)


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """The JSON view read returns every cell as a string. Convert columns whose non-blank cells
    are all numbers, and leave text, dates and booleans as they are."""
    out = df.copy()
    for i in range(out.shape[1]):
        col = out.iloc[:, i].replace('', None)
        converted = pd.to_numeric(col, errors='coerce')
        if converted.notna().sum() == col.notna().sum():
            out.isetitem(i, converted)
    return out
