import pytest

from sm_epm.lib.errors import OperationFailedError, OperationTimeoutError
from sm_epm.lib.pigment.imports import to_csv, wait_for_import


def test_to_csv():
    assert to_csv(('A', 'B'), [['1', 'x,y']]) == 'A,B\n1,"x,y"\n'


class FakePigment:
    def __init__(self, statuses):
        self.statuses = iter(statuses)

    def get_import_status(self, import_id):
        return {'importStatus': next(self.statuses)}


def test_wait_for_import_polls_until_done():
    assert wait_for_import(FakePigment(['InProgress', 'Completed']), 'id', poll_seconds=0)['importStatus'] == 'Completed'


def test_wait_for_import_raises_on_failure():
    with pytest.raises(OperationFailedError, match='failed'):
        wait_for_import(FakePigment(['Failed']), 'id', poll_seconds=0)


def test_wait_for_import_times_out():
    with pytest.raises(OperationTimeoutError, match='still in progress'):
        wait_for_import(FakePigment(['InProgress'] * 3), 'id', poll_seconds=0, timeout_seconds=-1)
