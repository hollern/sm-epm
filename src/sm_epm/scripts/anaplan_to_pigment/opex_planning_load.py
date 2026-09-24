"""Load Anaplan opex planning inputs into Pigment's General Data Hub transaction lists.

Run the file directly for a dry run: it runs the Anaplan exports, reshapes them to Pigment's layout
and writes CSVs to output/. Call main(load=True) to also push them through the Pigment import
configurations.
"""

from __future__ import annotations

import csv
import io
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from sm_epm.lib.anaplan.client import client_from_env as anaplan_client_from_env
from sm_epm.lib.anaplan.errors import anaplan_errors
from sm_epm.lib.env import PROJECT_ROOT
from sm_epm.lib.errors import DataFormatError, OperationFailedError, OperationTimeoutError
from sm_epm.lib.pigment.client import client_from_env as pigment_client_from_env
from sm_epm.lib.pigment.errors import pigment_errors

OUTPUT_DIR = PROJECT_ROOT / 'output'
MONTH_HEADER = re.compile(r'^[A-Z][a-z]{2} \d{2}$')

# The exports fix these page selections. 110 is the only leaf in s.Subsidiary.Non-HC Planning.
EXPECTED_VERSION = 'Forecast'
SUBSIDIARY = '110 - SurveyMonkey Inc.'


def _vendor_keys(keys: Sequence[str]) -> list[str]:
    department, vendor_name, code, _ = keys
    # Anaplan combines GL account and vendor in one dimension, coded "<GL account>|<NetSuite vendor ID>";
    # Pigment keeps them as separate dimensions.
    gl_code, sep, vendor_id = code.partition('|')
    if not sep or not gl_code or not vendor_id:
        raise DataFormatError(f"vendor code {code!r} is not '<GL account>|<vendor ID>'", service='anaplan')
    return [department, gl_code, vendor_name, vendor_id]


@dataclass(frozen=True)
class Load:
    name: str
    anaplan_export_id: int
    pigment_import_config_id: str
    source_keys: tuple[str, ...]
    target_header: tuple[str, ...]
    map_keys: Callable[[Sequence[str]], list[str]]


LOADS = (
    Load(
        name='non_vendor_planning',
        # Anaplan: "Pigment Import: Business Partner Opex Planning" (INPUT: Business Partner Opex Planning)
        anaplan_export_id=116000000013,
        # Pigment: "Non-Vendor Planning Load" on 2. General Data Hub / Non-Vendor Planning
        pigment_import_config_id='5ff899cc-2d59-4437-8fdb-a0e254ca8f45',
        source_keys=(
            's.Department.BP OPEX Planning',
            's.P&L GL Account.BP Opex Planning',
            's.P&L GL Account.BP Opex Planning: Code',
        ),
        target_header=(
            'Load Date',
            'Subsidiary',
            'Department',
            'P&L GL Account',
            'P&L GL Account Code',
            'Month',
            'Total Expense',
        ),
        map_keys=list,
    ),
    Load(
        name='vendor_planning',
        # Anaplan: "Pigment Import: Vendor Planning" (INPUT: Existing NetSuite Vendor Planning)
        anaplan_export_id=116000000014,
        # Pigment: "Vendor Planning Load" on 2. General Data Hub / Vendor Planning
        pigment_import_config_id='1bce0307-e218-49e8-8556-d9b086fdb53e',
        source_keys=(
            'Department L3',
            's.Vendor.NetSuite Created Vendor',
            's.Vendor.NetSuite Created Vendor: Code',
            's.Vendor.NetSuite Created Vendor: Name',
        ),
        target_header=(
            'Load Date',
            'Subsidiary',
            'Department L3',
            'P&L GL Account Code',
            'Vendor (NetSuite) Name',
            'Vendor (NetSuite) ID > Vendor ID',
            'Month',
            'Amount',
        ),
        map_keys=_vendor_keys,
    ),
)


def transform(load: Load, raw: str, load_date: str) -> list[list[str]]:
    """Unpivot an Anaplan grid export (page line, header, rows) into one row per month, skipping zeros."""
    lines = list(csv.reader(io.StringIO(raw)))
    pages, header, body = lines[0], lines[1], lines[2:]

    if EXPECTED_VERSION not in pages or SUBSIDIARY not in pages:
        raise DataFormatError(
            f'{load.name}: export pages are {pages}, expected {EXPECTED_VERSION!r} and {SUBSIDIARY!r}',
            service='anaplan',
        )
    n = len(load.source_keys)
    months = header[n:]
    if tuple(header[:n]) != load.source_keys or not months or not all(map(MONTH_HEADER.match, months)):
        raise DataFormatError(f'{load.name}: unexpected export header {header}', service='anaplan')

    rows = []
    for line_no, record in enumerate(body, start=3):
        if len(record) != len(header):
            raise DataFormatError(
                f'{load.name}: line {line_no} has {len(record)} columns, expected {len(header)}', service='anaplan'
            )
        keys = load.map_keys(record[:n])
        for month, value in zip(months, record[n:]):
            if value.strip() and float(value) != 0:
                rows.append([load_date, SUBSIDIARY, *keys, month, value])
    return rows


def to_csv(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator='\n')
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue()


def wait_for_import(pigment, import_id: str, poll_seconds: float = 5, timeout_seconds: float = 600) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while True:
        with pigment_errors:
            status = pigment.get_import_status(import_id)
        if status['importStatus'] == 'Failed':
            raise OperationFailedError(f'import {import_id} failed', service='pigment', payload=status)
        if status['importStatus'] != 'InProgress':
            return status
        if time.monotonic() > deadline:
            raise OperationTimeoutError(
                f'import {import_id} still in progress after {timeout_seconds}s', service='pigment', payload=status
            )
        time.sleep(poll_seconds)


def main(load: bool = False) -> None:
    """Export, reshape and write CSVs to output/. Push to Pigment only when load is True."""
    anaplan = anaplan_client_from_env()
    pigment = pigment_client_from_env() if load else None
    load_date = date.today().isoformat()
    OUTPUT_DIR.mkdir(exist_ok=True)

    for load in LOADS:
        with anaplan_errors:
            raw = anaplan.export_and_download(load.anaplan_export_id).decode('utf-8-sig')
        rows = transform(load, raw, load_date)
        payload = to_csv(load.target_header, rows)
        path = OUTPUT_DIR / f'{load.name}_{load_date}.csv'
        path.write_text(payload)
        total = sum(float(r[-1]) for r in rows)
        print(f'{load.name}: {len(raw.splitlines()) - 2} Anaplan rows -> {len(rows)} Pigment rows, total {total:,.2f}')
        print(f'  wrote {path}')

        if pigment is None:
            print('  dry run: not loaded to Pigment')
            continue
        with pigment_errors:
            import_id = pigment.import_csv(load.pigment_import_config_id, payload)
        status = wait_for_import(pigment, import_id)
        print(f"  Pigment import {import_id}: {status['importStatus']}")


if __name__ == '__main__':
    main()
