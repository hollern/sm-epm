import pytest

from sm_epm.lib.errors import ConfigurationError
from sm_epm.lib.mappings import REPORTING_VERSIONS, map_item


def test_map_item_returns_pigment_item():
    assert map_item(REPORTING_VERSIONS, 'Forecast', dimension='Reporting Version') == 'Current Forecast'
    assert map_item(REPORTING_VERSIONS, 'Actual', dimension='Reporting Version') == 'Actual'


def test_map_item_rejects_unmapped_item():
    with pytest.raises(ConfigurationError, match="no Pigment mapping for Anaplan item 'Budget'"):
        map_item(REPORTING_VERSIONS, 'Budget', dimension='Reporting Version')


def test_map_item_rejects_item_that_is_not_migrated():
    with pytest.raises(ConfigurationError, match='is not migrated'):
        map_item(REPORTING_VERSIONS, "Q2'26 Outlook", dimension='Reporting Version')
