# Anaplan to Pigment dimension mapping

This doc records which Anaplan list maps to which Pigment dimension, and how their items match. Item mappings that have to be set by hand live in Python, in `src/sm_epm/lib/mappings.py`. Loads call `map_item(...)`, which raises `ConfigurationError` if an item is unmapped or marked as not migrated.

## Dimensions

| Anaplan list | Pigment dimension (`2. General Data Hub`) | How items match | Checked |
|---|---|---|---|
| Reporting Version | `Reporting Version` (`174f600a-f58e-40c5-9070-c3983654c870`) | **Manual:** `REPORTING_VERSIONS` in `lib/mappings.py` | 2026-09-29 |
| Subsidiary S2 | `Subsidiary S2` (`1b72d5d1-eeee-4c3a-96e9-1904f5df2598`) | By name. `Code` matches too. | 2026-09-29, all items |
| Department L3 (and its BP subsets) | `Department L3` | By name | 2026-09-24, opex export items only |
| P&L GL Account (and its BP subsets) | `P&L GL Account L3` (`161419d7-9a9f-4c17-8886-2297659302a9`) | By `Code` property. Anaplan GL names are `<code> - <name>`. Pigment's `Type` property is COR, HC or Non-HC, and blank for revenue (4xxxxx) | 2026-09-29, the FY26-27 export: all match except `601021 - Gratuity Expense (India)` |
| Time (months, for example `Jan 26`) | `Month` | By name | 2026-09-24, opex export items only |
| `s.Vendor.NetSuite Created Vendor` | Split into `P&L GL Account L3` + `Vendor (NetSuite)` | See [the opex load doc](anaplan-to-pigment-opex-load.md) | Not yet. The Pigment dimension had 0 items |

## Reporting Version

| Anaplan | Pigment |
|---|---|
| Actual | Actual |
| 2026 Plan | 2026 Plan |
| Q3'26 Outlook | Q3'26 Outlook |
| Forecast | Current Forecast |
| Q2'26 Outlook | Not migrated (`None`) |

- **Decision:** Anaplan `Forecast` maps to Pigment `Current Forecast`, and `Q2'26 Outlook` isn't migrated.
- **Why:** user direction.
- **Date:** 2026-09-29.
- **Pigment's items:** Current Forecast was created in Pigment on 2026-09-29, so every mapped item exists. The full list is 2026 Plan, Actual, Budget Forecast, Current Forecast, Q3'26 Outlook and WFP Test. `Budget Forecast` and `WFP Test` have no Anaplan source.
- **Per-load scope** is separate from this mapping. A load can exclude a mapped version; for example, the P&L account values load excludes Actual.

## Subsidiary S2

All 73 Anaplan leaf items match Pigment's `Subsidiary S2` by name and by code, so no manual mapping is needed.
- **Anaplan only:** the parents `Total Company`, `US`, `International` and `New Subsidiary`. Loads must exclude them.
- **Pigment only:** `Not Provided` (code `NP`).
- Pigment's `Subsidiary S1` is the parent level.

## Adding a mapping

- If a dimension's item names differ between the two systems, add a `dict[str, str | None]` to `lib/mappings.py`, with `None` for items that aren't migrated. Then call `map_item(MAPPING, item, dimension=...)` in the load.
- If the items match by name or code, add a row to the Dimensions table above and don't add a dict.
