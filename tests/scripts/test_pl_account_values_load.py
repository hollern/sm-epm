from dataclasses import replace

import pytest

from sm_epm.lib.errors import ConfigurationError, DataFormatError
from sm_epm.scripts.anaplan_to_pigment import pl_account_values_load as mod
from sm_epm.scripts.anaplan_to_pigment.pl_account_values_load import (
    CONSOLIDATED_OPEX,
    GL_TYPES,
    PLANNING_METHOD,
    VersionScope,
    main,
    planning_method_rows,
    transform,
)

SUB_110, SUB_240 = '110 - SurveyMonkey Inc.', '240 - SurveyMonkey UK Ltd.'
DEPT_1120, DEPT_XXXX = '1120 - Client Success', 'XXXX - No Department (L3)'
GL_601015, GL_603010 = '601015 - Overtime', '603010 - Spot Bonuses'

# Scopes for the test: Forecast Sep-Oct 26 without HC, Q3'26 Outlook Aug-Sep 26 with all types.
SCOPES = {
    'Forecast': VersionScope('Sep 26', 'Oct 26', frozenset({'COR', 'Non-HC'})),
    "Q3'26 Outlook": VersionScope('Aug 26', 'Sep 26', GL_TYPES),
}
GL_TYPE_BY_CODE = {'601015': 'Non-HC', '603010': 'Non-HC', '601010': 'HC', '400010': ''}
RAW = (
    'Amount\n'
    ",,,Forecast,Forecast,Forecast,Q3'26 Outlook,Q3'26 Outlook,Actual\n"
    ',,,Aug 26,Sep 26,Oct 26,Aug 26,Sep 26,Sep 26\n'
    f'{SUB_110},{DEPT_1120},{GL_601015},999,-256.48,0,-100,,7\n'
    f'{SUB_240},{DEPT_1120},{GL_601015},,,5,,,\n'
    f'{SUB_240},{DEPT_XXXX},{GL_603010},,214328.30999999997,,0,0,\n'
)


@pytest.fixture(autouse=True)
def scopes(monkeypatch):
    monkeypatch.setattr(mod, 'VERSION_SCOPES', dict(SCOPES))


def run(raw=RAW, gl_types=GL_TYPE_BY_CODE):
    return transform(raw, gl_types)


def test_transform_keeps_window_months_and_skips_zero_blank_and_actual():
    # Forecast Aug 26 (999) is outside its window and Actual is excluded.
    assert run(RAW) == [
        ['Current Forecast', SUB_110, DEPT_1120, '601015', 'Sep 26', '-256.48'],
        ["Q3'26 Outlook", SUB_110, DEPT_1120, '601015', 'Aug 26', '-100'],
        ['Current Forecast', SUB_240, DEPT_1120, '601015', 'Oct 26', '5'],
        ['Current Forecast', SUB_240, DEPT_XXXX, '603010', 'Sep 26', '214328.30999999997'],
    ]


def test_rows_match_target_headers():
    opex = run(RAW)
    assert all(len(r) == len(CONSOLIDATED_OPEX.header) for r in opex)
    assert all(len(r) == len(PLANNING_METHOD.header) for r in planning_method_rows(opex))


def test_planning_method_rows_are_unique_across_subsidiaries():
    # 601015 in Client Success has Current Forecast values in two subsidiaries: one Manual Input row.
    assert planning_method_rows(run(RAW)) == [
        [DEPT_1120, '601015', 'Current Forecast', 'Manual Input'],
        [DEPT_1120, '601015', "Q3'26 Outlook", 'Manual Input'],
        [DEPT_XXXX, '603010', 'Current Forecast', 'Manual Input'],
    ]


def test_transform_filters_gl_types_per_version():
    # 601015 becomes HC: Forecast leaves HC out, Q3'26 Outlook keeps it.
    rows = run(gl_types={**GL_TYPE_BY_CODE, '601015': 'HC'})
    assert [r[0] for r in rows if r[3] == '601015'] == ["Q3'26 Outlook"]


def test_transform_skips_revenue_gls():
    raw = RAW.replace(f'{DEPT_XXXX},{GL_603010}', f'{DEPT_XXXX},400010 - Subscription Revenue')
    assert '400010' not in {r[3] for r in run(raw)}


def test_transform_rejects_gl_without_type_outside_revenue():
    with pytest.raises(DataFormatError, match='GL 603010 has no Type'):
        run(gl_types={**GL_TYPE_BY_CODE, '603010': ''})


def test_transform_rejects_unknown_gl_type():
    with pytest.raises(ConfigurationError, match="unknown Type 'Capex'"):
        run(gl_types={**GL_TYPE_BY_CODE, '603010': 'Capex'})


def test_transform_rejects_gl_missing_from_pigment():
    with pytest.raises(DataFormatError, match='GL 603010 is not in Pigment'):
        run(gl_types={k: v for k, v in GL_TYPE_BY_CODE.items() if k != '603010'})


def test_transform_ignores_unknown_gl_when_row_has_nothing_to_load():
    # 603010's only values are outside the windows or zero, so it isn't looked up.
    raw = RAW.replace(',214328.30999999997,,0,0,', ',,,0,0,')
    assert '603010' not in {r[3] for r in run(raw, {k: v for k, v in GL_TYPE_BY_CODE.items() if k != '603010'})}


def test_window_months_cross_year_end():
    scope = VersionScope('Nov 26', 'Feb 27', GL_TYPES)
    assert [d.strftime('%b %y') for d in mod._window_months(scope)] == ['Nov 26', 'Dec 26', 'Jan 27', 'Feb 27']


def test_transform_rejects_window_month_missing_from_export(monkeypatch):
    monkeypatch.setitem(mod.VERSION_SCOPES, 'Forecast', VersionScope('Sep 26', 'Nov 26', GL_TYPES))
    with pytest.raises(DataFormatError, match="missing 1 months of the 'Forecast' window"):
        run(RAW)


def test_transform_rejects_version_without_window(monkeypatch):
    monkeypatch.delitem(mod.VERSION_SCOPES, "Q3'26 Outlook")
    with pytest.raises(ConfigurationError, match='no VERSION_SCOPES entry'):
        run(RAW)


def test_transform_fails_when_a_version_is_not_migrated(monkeypatch):
    monkeypatch.setitem(mod.VERSION_SCOPES, "Q2'26 Outlook", VersionScope('Aug 26', 'Sep 26', GL_TYPES))
    with pytest.raises(ConfigurationError, match='"Q2\'26 Outlook" is not migrated'):
        run(RAW.replace("Q3'26 Outlook", "Q2'26 Outlook"))


def test_transform_rejects_wrong_line_item_page():
    with pytest.raises(DataFormatError, match='export pages'):
        run(RAW.replace('Amount', 'Headcount', 1))


@pytest.mark.parametrize(
    'old, new',
    [
        (',,,Aug 26', 'Subsidiary S2,,,Aug 26'),  # named row header on the month line
        (',,,Forecast,', 'x,,,Forecast,'),  # named row header on the version line
        ('Oct 26,Aug 26', 'Q1 FY26,Aug 26'),  # non-month column
        (',Actual\n', ',\n'),  # blank version
        (',Sep 26\n', '\n'),  # version and month lines differ in width
    ],
)
def test_transform_rejects_unexpected_headers(old, new):
    with pytest.raises(DataFormatError, match='unexpected export headers'):
        run(RAW.replace(old, new, 1))


def test_transform_rejects_repeated_version_month_column():
    with pytest.raises(DataFormatError, match='repeats'):
        run(RAW.replace(',,,Aug 26,Sep 26,Oct 26', ',,,Aug 26,Aug 26,Oct 26'))


def test_transform_rejects_rollup_subsidiary():
    with pytest.raises(DataFormatError, match='rollup subsidiary'):
        run(RAW.replace(SUB_110, 'Total Company'))


@pytest.mark.parametrize('gl', ['Overtime', '6010 - Overtime', DEPT_1120])
def test_transform_rejects_gl_without_six_digit_code(gl):
    with pytest.raises(DataFormatError, match='GL account'):
        run(RAW.replace(f'{DEPT_XXXX},{GL_603010}', f'{DEPT_XXXX},{gl}'))


def test_transform_rejects_swapped_row_columns():
    with pytest.raises(DataFormatError, match='department'):
        run(RAW.replace(f'{SUB_110},{DEPT_1120}', f'{DEPT_1120},{SUB_110}'))


def test_transform_rejects_duplicate_row():
    with pytest.raises(DataFormatError, match='duplicate row'):
        run(RAW + RAW.splitlines()[3] + '\n')


def test_transform_rejects_ragged_row():
    with pytest.raises(DataFormatError, match='line 4'):
        run(RAW.replace(',-100,,7\n', ',-100,\n'))


def test_main_load_requires_import_configs(monkeypatch):
    # The check runs before any client is built, so this never reaches Anaplan or Pigment.
    monkeypatch.setattr(mod, 'TARGETS', (replace(PLANNING_METHOD, import_config_id=None), CONSOLIDATED_OPEX))
    with pytest.raises(ConfigurationError, match='import config ID'):
        main(load=True)
