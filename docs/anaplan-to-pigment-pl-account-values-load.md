# Anaplan to Pigment P&L account values load

The script `src/sm_epm/scripts/anaplan_to_pigment/pl_account_values_load.py` loads Anaplan P&L account values into Pigment's **`4. OpEx & COGS`** application as Manual Input OpEx. It makes two imports, in this order:

1. **`INP - Planning Method by Account`** (`ca06b2bc-b843-40fb-8b83-175b9d237a4e`) is set to `Manual Input` for every Department L3 × P&L GL Account L3 × Reporting Version that gets a value in step 2.
2. **`CALC - Consolidated OpEx`** (`7136d600-35ec-413d-99e1-dcfa5db12161`) gets the monthly values by Reporting Version × Subsidiary S2 × Department L3 × P&L GL Account L3 × Month.

**Status:** first full load completed on 2026-09-30 and verified by reading both metrics back. The open items are tagged `TODO(...)` in the script and listed below.

- **Dry run** (writes `output/pl_account_values_planning_method_<date>.csv` and `output/pl_account_values_consolidated_opex_<date>.csv`): run the file directly. It reads from Pigment too (read-only), to get the GL types.
- **Real load:** `from sm_epm.scripts.anaplan_to_pigment.pl_account_values_load import main; main(load=True)`.
- **When Anaplan is slow:** pass `run_export=False` to download the file from the export's latest completed run instead of starting a new one. Check the export's task history first (`client.get_task_summaries(116000000017)`), so you know how recent that run is.

## Source

- **Model:** FP&A Production (the default `ANAPLAN_MODEL_ID`). Running an export doesn't change model data.
- **Module:** `CALC: P&L Account Values by BOD` (`102000000101`). The line item is `Amount`, which is `'CALC: P&L Account Values (GAAP)'.Amount`, so the values are GAAP.
- **Module dimensions:** Department L3 (150 items), Subsidiary S2 (77 items in the view, including the parents `Total Company`, `US`, `International` and `New Subsidiary`), P&L GL Account (315 items, flat list), Reporting Version (Forecast, Q3'26 Outlook, Q2'26 Outlook, Actual and 2026 Plan), and Time (Jan 23 to Dec 28, plus quarters, FYs and All Periods).
- **Export:** `FY26-27 EXPORT` (`116000000017`), `GRID_CURRENT_PAGE`, CSV.
  - Line 1 is the page selection, `Amount`.
  - Line 2 is the **version header**: 3 blank row-column headers, then the Reporting Version of each data column.
  - Line 3 is the **month header**: 3 blank row-column headers, then the month of each data column.
  - The data columns are Reporting Version × Month: Forecast, Q3'26 Outlook and 2026 Plan, each Jan 26 to Dec 27, so 72 columns.
  - Each row is Subsidiary S2, Department L3 and P&L GL Account, **by name only**. There are no code columns.

## Targets

| Metric | Import configuration | Dimensions | Payload columns |
|---|---|---|---|
| `INP - Planning Method by Account` | `ANAPLAN -> Planning Method` (`ad139bb8-391d-4729-af28-39172ec593dc`) | Department L3 × P&L GL Account L3 × Reporting Version (**no Subsidiary**) | `Department L3`, `P&L GL Account L3`, `Reporting Version`, `Planning Method` (always `Manual Input`) |
| `CALC - Consolidated OpEx` | `ANAPLAN -> Consolidated Opex` (`ab867889-f47c-4d87-87ce-9413c6f1da5f`) | Month × Department L3 × P&L GL Account L3 × Reporting Version × Subsidiary S2 | `Reporting Version`, `Subsidiary S2`, `Department L3`, `P&L GL Account L3`, `Month`, `Amount` |

- `P&L GL Account L3` is the 6-digit GL code. Pigment's metric exports show the GL by code.
- `Reporting Version` is mapped through `lib.mappings.REPORTING_VERSIONS`, so Forecast becomes `Current Forecast`. See [the dimension mapping doc](anaplan-pigment-dimension-mapping.md).
- `Manual Input` is an item of Pigment's `Planning Methods` dimension. The other items are Run Rate, % of Revenue, Per Head and % Uplift.

## Decisions

### Scope per version: month window and GL types
`VERSION_SCOPES` sets what each Anaplan version loads. Months outside a version's window are skipped. GL types come from the `Type` property of Pigment's `P&L GL Account L3` (`161419d7-9a9f-4c17-8886-2297659302a9`, `2. General Data Hub`).

| Anaplan version → Pigment version | Months | GL types |
|---|---|---|
| 2026 Plan → 2026 Plan | Jan 26 to Dec 26 | COR, HC, Non-HC |
| Q3'26 Outlook → Q3'26 Outlook | Jul 26 to Dec 26 | COR, HC, Non-HC |
| Forecast → Current Forecast | Sep 26 to Dec 26 | COR, Non-HC |

**Why:** user direction. Q3'26 Outlook and 2026 Plan are historic versions used only for reporting, so they carry HC through this Manual Input method. Current Forecast leaves HC out.
**Date:** 2026-09-29

### Revenue GLs are skipped
Revenue GLs (4xxxxx) have no Type in Pigment. They're skipped, and they're tagged `TODO(revenue)` because they need to go to a different Pigment metric that hasn't been decided yet. A GL with no Type outside 4xxxxx stops the run, and so does a GL with a Type other than COR, HC or Non-HC.
**Why:** user direction. Revenue doesn't belong in an OpEx metric: loading it made every version's total negative.
**Date:** 2026-09-29

### One planning method flag per Department × GL × Version
The planning method metric has no Subsidiary dimension, so the flag is set for each Department × GL × Version that gets a value in Consolidated OpEx from **any** subsidiary. Existing methods for those intersections are overwritten, but only in the three target versions. That follows from what's sent: no rows go out for other versions.
**Why:** user direction.
**Date:** 2026-09-29

### Import straight into `CALC - Consolidated OpEx`
Despite the `CALC` prefix, the metric accepts input. The user confirmed it, and the sample load on 2026-09-29 showed it. There's no separate Manual Input metric, unlike the other planning methods, which each have their own `CALC - Expenses by GL and <method> Planning Method` block.
**Date:** 2026-09-29

### Subsidiary scope comes from the data
No subsidiary list is maintained. Every leaf subsidiary in the export is in scope, including the elimination and stat-to-GAAP subsidiaries. A subsidiary loads whenever it has a non-zero value inside a version's `VERSION_SCOPES` (its month window and GL types). The export's saved filter in Anaplan decides which subsidiaries appear at all, and `ROLLUP_SUBSIDIARIES` only guards against parents. In the 2026-09-29 dry run, 828, 965, 995 and `Mercury Bidco LLC` had no values in scope, so 11 subsidiaries loaded.
**Why:** user direction.
**Date:** 2026-09-29

### Import configurations are required
Pigment's API has no way to write data without an import configuration. The three write endpoints (`import/push/csv`, `import/push/looker` and `import/trigger`) all take a `configurationId`. There's no endpoint that creates a configuration or writes metric cells directly. So each target metric needs a configuration created once in the Pigment UI, and the script reuses it on every run.
**Source:** Pigment's API spec, `https://pigment.app/api/swagger/external-api.swagger.json`, checked 2026-09-29.
**Date:** 2026-09-29

### Skip zeros
Zero and blank cells aren't sent, to keep the load sparse.
**Why:** user direction.
**Date:** 2026-09-29

### Exclude Actual
`EXCLUDED_VERSIONS = {'Actual'}` skips Actual's columns if the export ever includes them. `REPORTING_VERSIONS` keeps `Actual → Actual`, because other loads may still need it.
**Why:** user direction.
**Date:** 2026-09-29

### Take the GL code from the GL name
Pigment matches GL accounts on Code, but the export only has names. Every GL name is `<6-digit code> - <name>`, so the script uses the prefix.
**Why:** it's reliable on the current data: all 149 GLs match, and no code maps to two names. It avoids changing the export.
**Date:** 2026-09-29

### Check GLs against Pigment only when a row loads something
A GL that's missing from Pigment's `P&L GL Account L3` stops the run, but only when its row has a non-zero value inside a load window.
**Why:** `601021 - Gratuity Expense (India)` exists in Anaplan but not in Pigment. Its values are only in Jun to Aug 26, outside every window. Checking every row would block the load for no reason.
**Date:** 2026-09-29

### Check row order by name pattern
The row columns have blank headers, so the header can't confirm their order. Instead, each row must have a department matching `^(\d{4}|XXXX) - ` and a GL matching `^\d{6} - `. Subsidiary prefixes are 3 digits, so if the columns are swapped, a check fails.
**Why:** it follows the same fail-loudly approach as the opex load.
**Date:** 2026-09-29

### Other checks
- **Page line:** it must contain `Amount`.
- **Headers:** both header lines must have blank row-column headers and be the same width. Every data column needs a non-blank version and a month, and no (version, month) pair may repeat.
- **Versions, checked before any rows are read:**
  - Every version not in `EXCLUDED_VERSIONS` needs a `VERSION_SCOPES` entry and a mapping.
  - Every month in its window must be in the export.
  - An unmapped or not-migrated version (for example Q2'26 Outlook) stops the run.
- **Rows:** ragged rows, rollup subsidiaries and duplicate rows are rejected.

**Date:** 2026-09-29

### Shared Pigment import helpers moved to `lib/`
`to_csv` and `wait_for_import` now live in `sm_epm.lib.pigment.imports`. Both this load and the opex load import them from there.
**Why:** this is the second script that needs them, and the project convention puts reusable code in `lib/`.
**Date:** 2026-09-29

## Learnings

- **Dry run on 2026-09-29:** 4,430 Anaplan rows became 32,403 Consolidated OpEx rows and 2,190 planning method rows.

  | Version | Rows | COR | HC | Non-HC | Total |
  |---|---|---|---|---|---|
  | 2026 Plan | 21,005 | 35.1M | 152.5M | 135.9M | 323,489,677.64 |
  | Q3'26 Outlook | 9,990 | 17.1M | 65.1M | 65.9M | 148,065,787.12 |
  | Current Forecast | 1,408 | 11.3M | none | 54.4M | 65,711,361.67 |

- **What the load would overwrite, as of 2026-09-29:**
  - **Planning methods:** 6 existing methods get overwritten: 3 `% Uplift`, 2 `Run Rate` and 1 `Per Head`, all in 2026 Plan or Q3'26 Outlook.
  - **Consolidated OpEx:** 1,067 existing cells get overwritten. The metric held 26,099 cells in total.
- **Pigment dimensions:** every department, GL code and subsidiary in the payload exists in Pigment. The only export GL missing from Pigment is `601021`, and none of its values fall inside the load windows.
- **The export covers every P&L GL, revenue included.** Before GL scoping, revenue netted each version negative. That's why 2026 looked lopsided against 2027 in earlier dry runs.
- **The subsidiaries in the export** are 110, 130, 140, 150, 160, 220, 240, 250, 255, 410, 430, 440 and 460. It also includes `828 - Netherlands Stat to GAAP Adjustment`, `965 - Europe Elim`, `995 - International Elim` and `Mercury Bidco LLC`.
- **First full load on 2026-09-30:**
  - It ran from the latest completed export, using `run_export=False`. The payload was identical to the approved 2026-09-29 dry run: the same 32,403 OpEx rows and 2,190 planning method rows, no value changes, and a total of 537,266,826.43.
  - Pigment imports `420eb1b3-04df-46bb-bc21-4667966ed7b9` (planning method) and `28d07ed7-fc3f-435b-82f0-20f2294fe7cc` (Consolidated OpEx) both finished `Completed`. This was the first import with the API key, which confirms it has import access.
  - Read-back: all 2,190 intersections are `Manual Input`, and all 32,403 cells match exactly. Afterwards the metrics held 2,210 and 57,483 values. Pigment's version totals are larger than this load's, because the metrics also hold intersections that other planning methods and GLs fill.
- **Verify a load against the raw metric, not a saved view.** Both saved views on `INP - Planning Method by Account` exported empty on 2026-09-30, even though all 2,190 loaded values were there. The views use a page selection (Reporting Version, and sometimes Department) that the load didn't write to. Read the metric back with `export_metric` / `metric_df` instead.
- **Anaplan export timeouts create duplicate tasks (2026-09-30).** After the model sat dormant overnight, `export_and_download` timed out while starting the export. The SDK retried the start request, and each retry queued another export task: the task history showed several `IN_PROGRESS` and `NOT_STARTED` tasks from our attempts. Anaplan runs actions on a model one at a time, so retrying only lengthens the queue. Check `get_task_summaries` / `get_task_status` instead. If a run has completed, download its file with `run_export=False`. The export tasks are read-only, so leftover ones are harmless.
- **Sample load on 2026-09-29:** the user uploaded `output/sample_planning_method.csv` (8 rows) and `output/sample_consolidated_opex.csv` (17 rows) through the Pigment UI while creating the import configurations. All 8 methods became `Manual Input`, and all 17 values matched exactly. The files are real dry-run rows, so the full load rewrites the same values. This confirmed the name-based matching for Department L3, Reporting Version and Subsidiary S2, code-based matching for P&L GL Account L3, `Sep 26`-style months, and negative and unrounded values. It didn't exercise the API key, because the upload used the user's own login.
- **How to create a sample for an import configuration:** pick a few intersections from the dry-run CSVs that cover each version, GL type and more than one subsidiary. Take all their rows from both CSVs, so the two samples line up. Setting up a configuration imports the uploaded file, so use real rows only.
- **Anaplan writes float noise**, for example `214328.30999999997`. Values pass through unchanged.
- **Export metadata `rowCount` is unreliable here too.** For the Forecast-only version of the export, it reported 2,484,484 rows, but the file had 4,142.
- The export is about 2.3 MB and takes under a minute.

## Open items

1. **Revenue:** decide which Pigment metric the 4xxxxx GLs load into (`TODO(revenue)`).
2. **Float noise:** decide whether to round values like `214328.30999999997`. The import config accepts them as they are.
3. **Stale values:** zeros are skipped, so wherever Anaplan now has 0 but Pigment has an old value, that value stays. Check whether each import config replaces or overwrites.
4. **`601021 - Gratuity Expense (India)`:** it isn't in Pigment's `P&L GL Account L3`. Add it before its values fall inside a load window, or the run will stop.
