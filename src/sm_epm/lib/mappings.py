"""Manual Anaplan -> Pigment item mappings, for dimensions whose item names differ between the two systems.

Dimensions whose items match by name need no entry here. See docs/anaplan-pigment-dimension-mapping.md
for which Anaplan list goes to which Pigment dimension, and how their items match.
"""

from __future__ import annotations

from collections.abc import Mapping

from sm_epm.lib.errors import ConfigurationError

# Anaplan "Reporting Version" -> Pigment "Reporting Version" (2. General Data Hub).
# None means the version isn't migrated, so a load that sends it fails.
REPORTING_VERSIONS: dict[str, str | None] = {
    'Actual': 'Actual',
    '2026 Plan': '2026 Plan',
    "Q3'26 Outlook": "Q3'26 Outlook",
    'Forecast': 'Current Forecast',
    "Q2'26 Outlook": None,
}


def map_item(mapping: Mapping[str, str | None], anaplan_item: str, *, dimension: str) -> str:
    """Return the Pigment item for ``anaplan_item``. Raises ConfigurationError if it's unmapped or not migrated."""
    if anaplan_item not in mapping:
        raise ConfigurationError(f'{dimension}: no Pigment mapping for Anaplan item {anaplan_item!r}', service='pigment')
    pigment_item = mapping[anaplan_item]
    if pigment_item is None:
        raise ConfigurationError(f'{dimension}: Anaplan item {anaplan_item!r} is not migrated', service='pigment')
    return pigment_item
