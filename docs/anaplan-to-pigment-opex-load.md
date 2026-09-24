# Anaplan to Pigment opex planning load

The script `src/sm_epm/scripts/anaplan_to_pigment/opex_planning_load.py` moves two Anaplan planning input modules into Pigment's `2. General Data Hub` transaction lists. It's run manually, not through a CLI. It's a **dry run by default** and only loads to Pigment when you call `main(load=True)`.

- **Dry run** (writes CSVs to `output/`): run the file directly, for example with Run in PyCharm.
- **Real load** (also pushes to Pigment): from a Python console, run `from sm_epm.scripts.anaplan_to_pigment.opex_planning_load import main; main(load=True)`.

The dry run stays the default when you run the file, so a real load always takes a deliberate call.

## Mapping

| Anaplan module | Anaplan export action | Pigment block | Pigment import config |
|---|---|---|---|
| INPUT: Business Partner Opex Planning (`102000000076`) | `Pigment Import: Business Partner Opex Planning` (`116000000013`) | TransactionList `Non-Vendor Planning` | `Non-Vendor Planning Load` (`5ff899cc-2d59-4437-8fdb-a0e254ca8f45`) |
| INPUT: Existing NetSuite Vendor Planning (`102000000082`) | `Pigment Import: Vendor Planning` (`116000000014`) | TransactionList `Vendor Planning` | `Vendor Planning Load` (`1bce0307-e218-49e8-8556-d9b086fdb53e`) |

The export metadata doesn't name its source module. The pairing was confirmed by matching each export's columns to the module's dimensions.

Column mapping:
- **Non-Vendor Planning:** `Load Date` = run date (ISO format), `Subsidiary`, `Department` = Anaplan department, `P&L GL Account` / `P&L GL Account Code` = Anaplan GL name / code, `Month`, `Total Expense`.
- **Vendor Planning:** `Load Date`, `Subsidiary`, `Department L3`, `P&L GL Account Code` = the part of the Anaplan vendor code before the `|`, `Vendor (NetSuite) Name` = Anaplan vendor item name, `Vendor (NetSuite) ID > Vendor ID` = the part of the code after the `|`, `Month`, `Amount`.

## Decisions

### Reuse the existing Anaplan "Pigment Import:" export actions
The script reads data through these export actions rather than through transactional view reads.
**Why:** they were purpose-built for Pigment and match the module dimensions, and running an export doesn't change model data.
**Date:** 2026-09-24

### Unpivot, and skip zero and blank values
Anaplan exports one column per month. Pigment's transaction lists take one row per month in `Month` / `Amount` form. Zero and blank cells are dropped.
**Why:** a zero-value transaction adds nothing and would roughly triple the row count.
**Date:** 2026-09-24

### Hard-code version and subsidiary, and fail loudly if they change
The script validates that the export's page line contains `Forecast` and `110 - SurveyMonkey Inc.`, that the header matches exactly, and that the month columns look like `Jan 26`. If any of these checks fails, the run stops.
**Why:** the exports are `GRID_CURRENT_PAGE`, so they contain only the page selected in the saved export definition. `110` is currently the only leaf subsidiary in `s.Subsidiary.Non-HC Planning`. The other items there, `Total Company` and `US`, are rollups.
**Date:** 2026-09-24

### Split Anaplan's combined GL Account × Vendor dimension into two Pigment dimensions
Anaplan's `s.Vendor.NetSuite Created Vendor` is a combined GL Account + Vendor dimension, coded `<GL account>|<NetSuite vendor ID>` (for example `620110|1194294`). In Pigment, GL Account and Vendor are **separate dimensions**, so the script splits the code into `P&L GL Account Code` and `Vendor (NetSuite) ID > Vendor ID`.
**Why:** this matches Pigment's dimensional design (user direction), and it keeps the GL granularity that would otherwise be lost.
**Date:** 2026-09-24
**Applies generally:** any future Anaplan load that uses a combined dimension like this should be split the same way.

## Learnings

- **An Anaplan grid export's first line is the page selection**, for example `Forecast,110 - SurveyMonkey Inc.,Total Expense`. The order differs per export. The column header is on line 2.
- **The Anaplan vendor code is `<GL account>|<NetSuite vendor ID>`**, and the `: Name` column holds an internal number like `#784`. The same vendor appears on several rows, one per GL account. After the split, each Department × GL × Vendor × Month combination is unique, with 0 duplicates on 2026-09-24.
- All 26 GL codes embedded in the vendor codes exist in Pigment's `P&L GL Account L3` `Code` property.
- **Export metadata `rowCount` isn't reliable.** For export 116000000013 it reported 7,422 rows, but the file had 902.
- **Dry run on 2026-09-24:** Non-Vendor had 902 Anaplan rows, which became 8,679 Pigment rows totalling 85,886,418.95. Vendor had 2,466 Anaplan rows, which became 18,498 Pigment rows totalling 500,031,662.02, across 24 months (Jan 26 to Dec 27). All departments, GL names and codes, and months matched items in Pigment's `Department L3`, `P&L GL Account L3` and `Month` dimensions.
- The output CSVs include vendor names, and some vendors are individual contractors. `output/` is gitignored, so don't paste its contents anywhere shared.

## Open before the first real load

1. **GL column in Pigment:** the Pigment `Vendor Planning` list and its `Vendor Planning Load` config don't yet have a GL Account property, as of 2026-09-24. Once they do, make sure the column name matches `P&L GL Account Code` in `LOADS`, or rename it there.
2. **Vendor ID:** confirm that the NetSuite vendor ID is the part of the code after the `|` (the other candidate is the `#784`-style name). Pigment's `Vendor (NetSuite)` dimension currently has **0 items**, so the vendor load will fail to match rows unless the import config creates items, or that dimension gets loaded first.
3. **Replace or append:** check whether each Pigment import config replaces or appends. If it appends, re-running the script will double the data.
4. **Formats:** confirm that the import configs expect a comma delimiter, ISO dates in `Load Date`, and the column names above. The client can't read import config details, so check them in the Pigment UI.
5. **Pigment key permissions:** confirm the Pigment API key has import permission. Only metadata and export access have been verified.
