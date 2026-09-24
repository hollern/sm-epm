import pytest

from sm_epm.lib.errors import RequestError
from sm_epm.lib.pigment import data as pigment_data


class FakePigment:
    def __init__(self):
        self.calls = []

    def export_view(self, view_id, **kwargs):
        self.calls.append(('view', view_id, kwargs))
        return '﻿Month,Amount\n2026-01,10\n'

    def _raw(self, kind, block_id, options):
        self.calls.append((kind, block_id, options))
        return 'Month,Amount\n2026-01,10\n'

    def export_list(self, block_id, **options):
        return self._raw('list', block_id, options)

    def export_metric(self, block_id, **options):
        return self._raw('metric', block_id, options)

    def export_table(self, block_id, **options):
        return self._raw('table', block_id, options)


def test_view_df_strips_bom_and_asks_for_comma_iso():
    client = FakePigment()
    df = pigment_data.view_df('v1', client=client)
    assert list(df.columns) == ['Month', 'Amount']
    assert client.calls == [('view', 'v1', {'date_format': 'Iso8601', 'field_delimiter': 'Comma'})]


def test_raw_exports_send_format_defaults_plus_options():
    client = FakePigment()
    df = pigment_data.metric_df('m1', client=client, options={'scenarios': ['s1']})
    assert df['Amount'].tolist() == [10]
    assert client.calls == [('metric', 'm1', pigment_data.RAW_EXPORT_FORMAT | {'scenarios': ['s1']})]


def test_read_kwargs_reach_read_csv():
    df = pigment_data.list_df('l1', client=FakePigment(), dtype=str)
    assert df['Amount'].tolist() == ['10']


@pytest.mark.parametrize(
    ('block_type', 'kind'),
    [('DimensionList', 'list'), ('TransactionList', 'list'), ('Metric', 'metric'), ('Table', 'table')],
)
def test_block_df_picks_export_from_block_type(block_type, kind):
    client = FakePigment()
    pigment_data.block_df('b1', block_type, client=client)
    assert client.calls[0][0] == kind


def test_block_df_rejects_unknown_type():
    with pytest.raises(RequestError, match='no raw export'):
        pigment_data.block_df('b1', 'Board', client=FakePigment())
