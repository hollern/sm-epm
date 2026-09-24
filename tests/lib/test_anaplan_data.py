from types import SimpleNamespace

import pandas as pd
import pytest

from sm_epm.lib.anaplan import data as anaplan_data
from sm_epm.lib.errors import DataFormatError, NotFoundError


def dims(*names):
    return [SimpleNamespace(name=n) for n in names]


class FakeTransactional:
    def get_view_info(self, view_id):
        return SimpleNamespace(rows=dims('GL Account'), columns=dims('Time'), pages=dims('Versions', 'Line Items'))

    def get_view_data(self, view_id, pages=None, max_rows=None):
        self.pages = pages
        return {
            'pages': ['Forecast', 'Total Expense'],
            'columnCoordinates': [['Jan 26'], ['Feb 26']],
            'rows': [
                {'rowCoordinates': ['601015 - Overtime'], 'cells': ['-814.77', '0']},
                {'rowCoordinates': ['603010 - Spot Bonuses'], 'cells': ['', '75000']},
            ],
        }

    def get_list_items(self, list_id, return_raw=False):
        return [
            {'id': 1, 'name': 'US', 'code': '110', 'properties': {'Region': 'NA'}, 'subsets': {'Active': True}},
            {'id': 2, 'name': 'UK', 'code': '120', 'properties': {'Region': 'EMEA'}, 'subsets': {'Active': False}},
        ]


class FakeClient:
    def __init__(self, export=None, content=b''):
        self.tr = FakeTransactional()
        self._export = export
        self._content = content

    def get_exports(self):
        return [self._export] if self._export else []

    def export_and_download(self, export_id):
        return self._content


def test_view_df_indexes_by_dimensions_and_converts_numbers():
    df = anaplan_data.view_df(1, client=FakeClient())
    assert df.index.name == 'GL Account'
    assert df.columns.name == 'Time'
    assert df.loc['601015 - Overtime', 'Jan 26'] == -814.77
    assert pd.isna(df.loc['603010 - Spot Bonuses', 'Jan 26'])
    assert df.attrs['pages'] == {'Versions': 'Forecast', 'Line Items': 'Total Expense'}


def test_view_df_long_has_one_row_per_cell():
    df = anaplan_data.view_df(1, client=FakeClient(), long=True)
    assert list(df.columns) == ['GL Account', 'Time', 'value']
    assert len(df) == 4
    assert df['value'].isna().sum() == 1  # the blank cell is kept as NaN
    assert df.attrs['pages']['Versions'] == 'Forecast'


def test_view_df_passes_page_overrides():
    client = FakeClient()
    anaplan_data.view_df(1, client=client, pages=[(10, 20)])
    assert client.tr.pages == [(10, 20)]


def test_export_df_skips_grid_page_line():
    export = SimpleNamespace(id=7, layout='GRID_CURRENT_PAGE', format='text/csv', encoding='UTF-8')
    content = '﻿Forecast,110 - SurveyMonkey Inc.\nDepartment,Jan 26\n1120 - Client Success,5\n'.encode()
    df = anaplan_data.export_df(7, client=FakeClient(export, content))
    assert list(df.columns) == ['Department', 'Jan 26']
    assert df.iloc[0, 1] == 5
    assert df.attrs['pages'] == ['Forecast', '110 - SurveyMonkey Inc.']


def test_export_df_tabular_tab_delimited():
    export = SimpleNamespace(id=7, layout='TABULAR_MULTI_COLUMN', format='text/plain', encoding=None)
    df = anaplan_data.export_df(7, client=FakeClient(export, b'A\tB\n1\t2\n'))
    assert df.to_dict('records') == [{'A': 1, 'B': 2}]


def test_export_df_unknown_export():
    with pytest.raises(NotFoundError, match='no export 7'):
        anaplan_data.export_df(7, client=FakeClient())


def test_list_items_df_flattens_properties():
    df = anaplan_data.list_items_df(1, client=FakeClient())
    assert list(df.columns) == ['id', 'name', 'code', 'Region', 'subsets.Active']
    assert df['Region'].tolist() == ['NA', 'EMEA']


def test_export_df_unsupported_format():
    export = SimpleNamespace(id=7, layout='TABULAR_MULTI_COLUMN', format='application/zip', encoding=None)
    with pytest.raises(DataFormatError, match='unsupported format'):
        anaplan_data.export_df(7, client=FakeClient(export, b''))


def test_export_df_empty_file_is_a_data_format_error():
    export = SimpleNamespace(id=7, layout='TABULAR_MULTI_COLUMN', format='text/csv', encoding=None)
    with pytest.raises(DataFormatError, match='could not parse'):
        anaplan_data.export_df(7, client=FakeClient(export, b''))
