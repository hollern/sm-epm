import pytest

from sm_epm.lib.errors import DataFormatError, OperationFailedError, OperationTimeoutError
from sm_epm.scripts.anaplan_to_pigment.opex_planning_load import LOADS, to_csv, transform, wait_for_import

NON_VENDOR, VENDOR = LOADS

BP_RAW = (
    'Forecast,110 - SurveyMonkey Inc.,Total Expense\n'
    's.Department.BP OPEX Planning,s.P&L GL Account.BP Opex Planning,s.P&L GL Account.BP Opex Planning: Code,Jan 26,Feb 26\n'
    '1120 - Client Success,601015 - Overtime,601015,-814.77,0\n'
    '1130 - Customer Advocacy,603010 - Spot Bonuses,603010,,75000\n'
)

VENDOR_RAW = (
    'Forecast,Amount,110 - SurveyMonkey Inc.\n'
    'Department L3,s.Vendor.NetSuite Created Vendor,s.Vendor.NetSuite Created Vendor: Code,'
    's.Vendor.NetSuite Created Vendor: Name,Jan 26,Feb 26\n'
    '1120 - Client Success,Acme Corp,620110|1194294,#784,0,4568.75\n'
)


def test_transform_non_vendor_unpivots_and_skips_zero_and_blank():
    assert transform(NON_VENDOR, BP_RAW, '2026-09-24') == [
        ['2026-09-24', '110 - SurveyMonkey Inc.', '1120 - Client Success', '601015 - Overtime', '601015', 'Jan 26', '-814.77'],
        ['2026-09-24', '110 - SurveyMonkey Inc.', '1130 - Customer Advocacy', '603010 - Spot Bonuses', '603010', 'Feb 26', '75000'],
    ]


def test_transform_vendor_splits_code_into_gl_account_and_vendor_id():
    assert transform(VENDOR, VENDOR_RAW, '2026-09-24') == [
        ['2026-09-24', '110 - SurveyMonkey Inc.', '1120 - Client Success', '620110', 'Acme Corp', '1194294', 'Feb 26', '4568.75'],
    ]


def test_rows_match_target_header_width():
    for load, raw in ((NON_VENDOR, BP_RAW), (VENDOR, VENDOR_RAW)):
        assert all(len(r) == len(load.target_header) for r in transform(load, raw, '2026-09-24'))


def test_transform_rejects_wrong_version_page():
    with pytest.raises(DataFormatError, match='export pages'):
        transform(NON_VENDOR, BP_RAW.replace('Forecast', 'Actual', 1), '2026-09-24')


def test_transform_rejects_changed_header():
    with pytest.raises(DataFormatError, match='unexpected export header'):
        transform(NON_VENDOR, BP_RAW.replace('s.Department.BP OPEX Planning', 'Department'), '2026-09-24')


@pytest.mark.parametrize('code', ['1194294', '|1194294', '620110|'])
def test_transform_rejects_malformed_vendor_code(code):
    with pytest.raises(DataFormatError, match='vendor code'):
        transform(VENDOR, VENDOR_RAW.replace('620110|1194294', code), '2026-09-24')


def test_transform_rejects_ragged_row():
    with pytest.raises(DataFormatError, match='line 3'):
        transform(NON_VENDOR, BP_RAW.replace(',-814.77,0', ',-814.77'), '2026-09-24')


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
