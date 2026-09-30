"""Load Anaplan P&L account values into Pigment's 4. OpEx & COGS as Manual Input OpEx.

Source: Anaplan module "CALC: P&L Account Values by BOD" (102000000101), line item Amount, read through
the export action "FY26-27 EXPORT" in the FP&A Production model.

Targets, both in the Pigment application "4. OpEx & COGS", loaded in this order:
1. "INP - Planning Method by Account" is set to "Manual Input" for every Department L3 x P&L GL Account
   x Reporting Version that gets a value in step 2. The metric has no Subsidiary dimension, so one
   flag covers every subsidiary.
2. "CALC - Consolidated OpEx" gets the monthly values by Reporting Version x Subsidiary S2 x
   Department L3 x P&L GL Account x Month, limited to each version's VERSION_SCOPES: a month window
   and a set of GL types (COR, HC, Non-HC, read from Pigment). Revenue GLs are skipped.

Run the file directly for a dry run: it runs the Anaplan export, reads the GL types from Pigment, builds
both payloads and writes them as CSVs to output/. main(load=True) also pushes them through the Pigment import configurations, and
raises a ConfigurationError if either import config ID is unset. Open items are tagged TODO here and
listed in docs/anaplan-to-pigment-pl-account-values-load.md.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from pigment import PigmentClient

from sm_epm.lib.anaplan.client import client_from_env as anaplan_client_from_env
from sm_epm.lib.anaplan.errors import anaplan_errors
from sm_epm.lib.env import PROJECT_ROOT
from sm_epm.lib.errors import ConfigurationError, DataFormatError
from sm_epm.lib.mappings import REPORTING_VERSIONS, map_item
from sm_epm.lib.pigment.client import client_from_env as pigment_client_from_env
from sm_epm.lib.pigment.data import list_df
from sm_epm.lib.pigment.errors import pigment_errors
from sm_epm.lib.pigment.imports import to_csv, wait_for_import

NAME = 'pl_account_values'
OUTPUT_DIR = PROJECT_ROOT / 'output'
MONTH_HEADER = re.compile(r'^[A-Z][a-z]{2} \d{2}$')
# Every GL code is 6 digits and every department prefix 4 characters (XXXX for No Department), which
# is how transform() tells the blank-headed row columns apart.
GL_NAME = re.compile(r'^(\d{6}) - ')
DEPARTMENT_NAME = re.compile(r'^(\d{4}|XXXX) - ')

# Anaplan: "FY26-27 EXPORT" on "CALC: P&L Account Values by BOD" (102000000101). Its Amount line item is
# 'CALC: P&L Account Values (GAAP)'.Amount, so these are GAAP values. The export is GRID_CURRENT_PAGE:
#   line 1: the page line, "Amount"
#   line 2: 3 blank row-column headers, then the Reporting Version of each data column
#   line 3: 3 blank row-column headers, then the Month of each data column (Jan 26 to Dec 27)
#   then rows of Subsidiary S2, Department L3, P&L GL Account, by name only.
# As of 2026-09-29 the versions are Forecast, Q3'26 Outlook and 2026 Plan, 24 months each.
ANAPLAN_EXPORT_ID = 116000000017
ROW_KEYS = ('Subsidiary S2', 'Department L3', 'P&L GL Account')
EXPECTED_LINE_ITEM = 'Amount'

# Pigment's "P&L GL Account L3" (2. General Data Hub). Its Type property (COR, HC, Non-HC) decides which
# GLs each version loads. Revenue GLs (4xxxxx) have no Type.
GL_LIST_ID = '161419d7-9a9f-4c17-8886-2297659302a9'
GL_TYPES = frozenset({'COR', 'HC', 'Non-HC'})
REVENUE_GL_PREFIX = '4'


@dataclass(frozen=True)
class VersionScope:
    first_month: str  # inclusive
    last_month: str  # inclusive
    gl_types: frozenset[str]


# What each Anaplan version loads (decided 2026-09-29). Every month in a window must be in the export;
# months outside it are skipped. Q3'26 Outlook and 2026 Plan are historic, reporting-only versions, so
# they load HC as well. Current Forecast leaves HC out.
VERSION_SCOPES = {
    '2026 Plan': VersionScope('Jan 26', 'Dec 26', GL_TYPES),
    "Q3'26 Outlook": VersionScope('Jul 26', 'Dec 26', GL_TYPES),
    'Forecast': VersionScope('Sep 26', 'Dec 26', frozenset({'COR', 'Non-HC'})),
}
# Out of scope for this load (decided 2026-09-29). Their columns are skipped if the export includes them.
# Any other version without a VERSION_SCOPES entry stops the run.
EXCLUDED_VERSIONS = frozenset({'Actual'})
# TODO(revenue): revenue GLs (4xxxxx, no Type in Pigment) are skipped here. They need to load into a
#  different Pigment metric, which isn't decided yet.

# Subsidiary S2 items match Pigment's "Subsidiary S2" by name (all 73 leaves, checked 2026-09-29), so
# they pass through unmapped. These are its parents: the export filter already leaves them out, and
# this catches the filter changing.
# Every leaf subsidiary in the export is in scope, eliminations and stat-to-GAAP adjustments included
# (decided 2026-09-29). A subsidiary loads whenever it has values inside a version's VERSION_SCOPES.
ROLLUP_SUBSIDIARIES = frozenset({'Total Company', 'US', 'International', 'New Subsidiary'})

MANUAL_INPUT = 'Manual Input'  # an item of Pigment's "Planning Methods" dimension


@dataclass(frozen=True)
class Target:
    name: str
    metric: str
    metric_id: str
    import_config_id: str | None
    header: tuple[str, ...]


# Pigment application "4. OpEx & COGS" (08b9beb0-55db-4f96-9bc3-48bbb883ef1e). Loaded in this order,
# so the planning method is in place before the values arrive.
# Import configurations "ANAPLAN -> Planning Method" and "ANAPLAN -> Consolidated Opex", created in the
# Pigment UI on 2026-09-29. Sample uploads through both landed exactly, which confirmed that Consolidated
# OpEx accepts input despite its CALC name, and that the Month and GL code formats match.
# TODO(pigment-import-config): check whether each config replaces or overwrites. Skipped zero cells
#  leave any value already in Pigment as it is.
PLANNING_METHOD = Target(
    name=f'{NAME}_planning_method',
    metric='INP - Planning Method by Account',
    metric_id='ca06b2bc-b843-40fb-8b83-175b9d237a4e',
    import_config_id='ad139bb8-391d-4729-af28-39172ec593dc',
    header=('Department L3', 'P&L GL Account L3', 'Reporting Version', 'Planning Method'),
)
CONSOLIDATED_OPEX = Target(
    name=f'{NAME}_consolidated_opex',
    metric='CALC - Consolidated OpEx',
    metric_id='7136d600-35ec-413d-99e1-dcfa5db12161',
    import_config_id='ab867889-f47c-4d87-87ce-9413c6f1da5f',
    header=('Reporting Version', 'Subsidiary S2', 'Department L3', 'P&L GL Account L3', 'Month', 'Amount'),
)
TARGETS = (PLANNING_METHOD, CONSOLIDATED_OPEX)


def _month(label: str) -> date:
    return datetime.strptime(label, '%b %y').date()


def read_gl_types(pigment: PigmentClient) -> dict[str, str]:
    """GL code -> Type from Pigment's P&L GL Account L3, with '' for GLs that have no Type."""
    gls = list_df(GL_LIST_ID, client=pigment, dtype=str)
    codes = gls['Code'].dropna()
    if codes.duplicated().any():
        raise DataFormatError(f'duplicate GL codes in P&L GL Account L3: {sorted(set(codes[codes.duplicated()]))}', service='pigment')
    return dict(zip(codes, gls.loc[codes.index, 'Type'].fillna('')))


def transform(raw: str, gl_types: Mapping[str, str]) -> list[list[str]]:
    """Unpivot the Anaplan grid export (page line, version and month headers, rows) into Consolidated
    OpEx rows, one per version and month, keeping only what each version's VERSION_SCOPES allows and
    skipping zeros.

    ``gl_types`` maps GL code to its Pigment Type (see read_gl_types). Each Reporting Version is mapped to
    Pigment's through lib.mappings.REPORTING_VERSIONS, and the GL code is the part of the GL name before
    " - ". EXCLUDED_VERSIONS and revenue GLs are skipped. Raises ConfigurationError if a version has no
    scope or isn't mapped, or a GL has an unknown Type, and DataFormatError on an unexpected page line or
    headers, a repeated version and month column, a window month missing from the export, a ragged row,
    a rollup subsidiary, a department or GL name that doesn't match its pattern (which is also how a
    change in row order shows up), a GL missing from Pigment or with no Type outside revenue, or a
    duplicate row.
    """
    lines = list(csv.reader(io.StringIO(raw)))
    pages, version_header, month_header, body = lines[0], lines[1], lines[2], lines[3:]

    if EXPECTED_LINE_ITEM not in pages:
        raise DataFormatError(f'export pages are {pages}, expected {EXPECTED_LINE_ITEM!r}', service='anaplan')
    n = len(ROW_KEYS)
    versions, months = version_header[n:], month_header[n:]
    # The row columns have blank headers, so their order is checked per row instead, by the department
    # and GL name patterns.
    if (
        any(version_header[:n])
        or any(month_header[:n])
        or not months
        or len(versions) != len(months)
        or not all(v.strip() for v in versions)
        or not all(map(MONTH_HEADER.match, months))
    ):
        raise DataFormatError(f'unexpected export headers {version_header} / {month_header}', service='anaplan')
    columns = list(zip(versions, months))
    if len(set(columns)) != len(columns):
        raise DataFormatError('export repeats a (version, month) column', service='anaplan')

    # Check every version up front, so a bad one fails before any rows are processed.
    loaded = sorted({v for v in versions if v not in EXCLUDED_VERSIONS})
    for version in loaded:
        if version not in VERSION_SCOPES:
            raise ConfigurationError(f'version {version!r} has no VERSION_SCOPES entry', service='pigment')
        exported = {_month(m) for v, m in columns if v == version}
        missing = [d for d in _window_months(VERSION_SCOPES[version]) if d not in exported]
        if missing:
            scope = VERSION_SCOPES[version]
            raise DataFormatError(
                f'export is missing {len(missing)} months of the {version!r} window '
                f'{scope.first_month} to {scope.last_month}',
                service='anaplan',
            )
    pigment_versions = {v: map_item(REPORTING_VERSIONS, v, dimension='Reporting Version') for v in loaded}
    # For each data column, (Pigment version, scope) if it's in a loaded version's window, else None.
    column_scopes = [
        (pigment_versions[v], VERSION_SCOPES[v])
        if v in pigment_versions and _in_window(VERSION_SCOPES[v], m)
        else None
        for v, m in columns
    ]

    rows = []
    seen: set[tuple[str, ...]] = set()
    for line_no, record in enumerate(body, start=4):
        if len(record) != len(month_header):
            raise DataFormatError(
                f'line {line_no} has {len(record)} columns, expected {len(month_header)}', service='anaplan'
            )
        subsidiary, department, gl_name = record[:n]
        if subsidiary in ROLLUP_SUBSIDIARIES:
            raise DataFormatError(f'line {line_no}: rollup subsidiary {subsidiary!r} in export', service='anaplan')
        if not DEPARTMENT_NAME.match(department):
            raise DataFormatError(f"line {line_no}: department {department!r} is not '<code> - <name>'", service='anaplan')
        match = GL_NAME.match(gl_name)
        if not match:
            raise DataFormatError(f"line {line_no}: GL account {gl_name!r} is not '<code> - <name>'", service='anaplan')
        key = (subsidiary, department, gl_name)
        if key in seen:
            raise DataFormatError(f'line {line_no}: duplicate row {key}', service='anaplan')
        seen.add(key)

        # Values pass through as Anaplan writes them, float noise included (for example 214328.30999999997).
        # The sample load on 2026-09-29 confirmed the import config accepts them.
        cells = [
            (column, month, value)
            for column, month, value in zip(column_scopes, months, record[n:])
            if column is not None and value.strip() and float(value) != 0
        ]
        if not cells:
            continue
        # The GL is only checked against Pigment when the row has values to load, so a GL that exists
        # only in Anaplan doesn't block the run while its values are all outside the windows.
        gl_code = match.group(1)
        if gl_code not in gl_types:
            raise DataFormatError(f'line {line_no}: GL {gl_code} is not in Pigment P&L GL Account L3', service='pigment')
        gl_type = gl_types[gl_code]
        if not gl_type:
            if gl_code.startswith(REVENUE_GL_PREFIX):
                continue  # TODO(revenue)
            raise DataFormatError(f'line {line_no}: GL {gl_code} has no Type in Pigment', service='pigment')
        if gl_type not in GL_TYPES:
            raise ConfigurationError(f'line {line_no}: GL {gl_code} has unknown Type {gl_type!r}', service='pigment')

        for (version, scope), month, value in cells:
            if gl_type in scope.gl_types:
                rows.append([version, subsidiary, department, gl_code, month, value])
    return rows


def _window_months(scope: VersionScope) -> list[date]:
    first, last = _month(scope.first_month), _month(scope.last_month)
    months = [first]
    while months[-1] < last:
        d = months[-1]
        months.append(date(d.year + d.month // 12, d.month % 12 + 1, 1))
    return months


def _in_window(scope: VersionScope, month: str) -> bool:
    return _month(scope.first_month) <= _month(month) <= _month(scope.last_month)


def planning_method_rows(opex_rows: Sequence[Sequence[str]]) -> list[list[str]]:
    """One Manual Input row per Department L3 x P&L GL Account x Reporting Version in the OpEx rows,
    across all subsidiaries, sorted."""
    keys = {(department, gl_code, version) for version, _, department, gl_code, _, _ in opex_rows}
    return [[*key, MANUAL_INPUT] for key in sorted(keys)]


def main(load: bool = False, run_export: bool = True) -> None:
    """Export, build both payloads and write them to output/. Push to Pigment only when load is True.

    With run_export=False, the file from the export's latest completed run is downloaded instead of
    starting a new run. Use it when Anaplan is slow: a start request that times out is retried by the
    SDK, and every retry queues another export task on the model.
    """
    if load and any(t.import_config_id is None for t in TARGETS):
        raise ConfigurationError('an import config ID is not set; see TODO(pigment-import-config)', service='pigment')

    anaplan = anaplan_client_from_env()
    # Pigment is read in a dry run too, for the GL types. It's only written when load is True.
    pigment = pigment_client_from_env()
    load_date = date.today().isoformat()
    OUTPUT_DIR.mkdir(exist_ok=True)

    with anaplan_errors:
        content = anaplan.export_and_download(ANAPLAN_EXPORT_ID) if run_export else anaplan.get_file(ANAPLAN_EXPORT_ID)
        raw = content.decode('utf-8-sig')
    opex_rows = transform(raw, read_gl_types(pigment))
    payloads = {PLANNING_METHOD: planning_method_rows(opex_rows), CONSOLIDATED_OPEX: opex_rows}
    print(f'{NAME}: {len(raw.splitlines()) - 3} Anaplan rows')

    for target in TARGETS:
        rows = payloads[target]
        payload = to_csv(target.header, rows)
        path = OUTPUT_DIR / f'{target.name}_{load_date}.csv'
        path.write_text(payload)
        print(f'{target.metric}: {len(rows)} rows')
        if target is CONSOLIDATED_OPEX:
            totals: dict[str, list[float]] = {}
            for r in rows:
                totals.setdefault(r[0], []).append(float(r[-1]))
            for version, values in totals.items():
                print(f'  {version}: {len(values)} rows, total {sum(values):,.2f}')
        print(f'  wrote {path}')

        if not load:
            print('  dry run: not loaded to Pigment')
            continue
        with pigment_errors:
            import_id = pigment.import_csv(target.import_config_id, payload)
        status = wait_for_import(pigment, import_id)
        print(f"  Pigment import {import_id}: {status['importStatus']}")


if __name__ == '__main__':
    main()
