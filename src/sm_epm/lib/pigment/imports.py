"""Push CSV payloads through Pigment import configurations.

``to_csv`` builds the payload and ``wait_for_import`` polls an import started with
``PigmentClient.import_csv`` until it finishes. Failures raise ``sm_epm.lib.errors.EPMError`` subclasses.
"""

from __future__ import annotations

import csv
import io
import time
from collections.abc import Sequence

from pigment import PigmentClient

from sm_epm.lib.errors import OperationFailedError, OperationTimeoutError
from sm_epm.lib.pigment.errors import SERVICE, pigment_errors


def to_csv(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Comma-delimited CSV with ``\\n`` line endings, which is what our import configs expect."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator='\n')
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue()


def wait_for_import(
    pigment: PigmentClient, import_id: str, poll_seconds: float = 5, timeout_seconds: float = 600
) -> dict:
    """Poll until the import leaves ``InProgress``. Returns the final status, and raises if it failed or timed out."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        with pigment_errors:
            status = pigment.get_import_status(import_id)
        if status['importStatus'] == 'Failed':
            raise OperationFailedError(f'import {import_id} failed', service=SERVICE, payload=status)
        if status['importStatus'] != 'InProgress':
            return status
        if time.monotonic() > deadline:
            raise OperationTimeoutError(
                f'import {import_id} still in progress after {timeout_seconds}s', service=SERVICE, payload=status
            )
        time.sleep(poll_seconds)
