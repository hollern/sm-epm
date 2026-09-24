# Reading Anaplan and Pigment data into pandas

`sm_epm.lib.anaplan.data` and `sm_epm.lib.pigment.data` read data from either system straight into a DataFrame. They're read-only. Every function takes an optional `client=`, and builds one from `.env` when it's omitted. Failures raise `EPMError` subclasses (see [error-handling.md](error-handling.md)): for example an unknown ID is `NotFoundError`, and a file pandas can't parse is `DataFormatError`.

```python
from sm_epm.lib.anaplan import data as anaplan_data
from sm_epm.lib.pigment import data as pigment_data

anaplan_data.view_df(102000000076)            # module or saved view, grid layout
anaplan_data.view_df(102000000076, long=True) # one row per cell
anaplan_data.export_df(116000000013)          # run a bulk export action and read its file
anaplan_data.list_items_df(list_id)           # list items with codes, parents, properties

pigment_data.view_df(view_id)                 # saved view, as laid out
pigment_data.block_df(block['id'], block['type'])  # raw block data, from list_blocks() output
pigment_data.metric_df(metric_id, options={'scenarios': [...]})
```

Pass `dtype=str` (or any other `pd.read_csv` argument) to the CSV-based functions to keep codes such as `0012` as text.

## Decisions

### Anaplan views use the transactional JSON read, exports use bulk actions
`view_df` reads through `get_view_data` in JSON form and builds the index and columns from the view's row and column dimensions. `export_df` runs a saved export action.
**Why:** the JSON read gives the dimension coordinates of each row and column directly, so the DataFrame is labelled without parsing a grid CSV. Exports are the right tool when a saved export definition already exists or the view is over the 1,000,000-cell read limit.
**Date:** 2026-09-24

### Pigment raw exports default to comma, ISO dates, friendly headers, no BOM
`pigment_data.RAW_EXPORT_FORMAT` is sent with every List/Metric/Table export. `options=` adds or overrides fields.
**Why:** Pigment's own defaults are semicolons, technical headers such as `month_of_year_QCIMSB`, and a UTF-8 BOM on the first header.
**Date:** 2026-09-24

### Raw block exports were added to the `pigment` library
`PigmentClient.export_list`, `export_metric` and `export_table` (in `../pigment-epm`) wrap `POST /api/v1/export/{list|metric|table}/{blockId}`. They pass request body fields through as keyword arguments.
**Why:** the project rule is to add missing Pigment API coverage to the library, not call the API directly.
**Date:** 2026-09-24

## Learnings

- **Anaplan `get_view_data` JSON:** `pages` is a list of the selected page item names, `columnCoordinates` is one list per column (one entry per column dimension), and each row has `rowCoordinates` and `cells`. Every cell is a **string**, so `view_df` converts columns whose non-blank cells are all numeric. Dimension names come from a separate `get_view_info` call.
- **Anaplan views include rollups.** Module `102000000076` returns quarters and `FY` columns next to months, and parent rows (for example `Employment & Recruiting`) next to leaf GL accounts. Filter them out before summing.
- **Anaplan export formats vary per export:** `text/csv`, tab-delimited `text/plain`, or Excel (`spreadsheetml`). `GRID_CURRENT_PAGE` exports start with a page-selection line in every format. Export `116000000000` is Excel and currently has headers but no data rows.
- **Pigment block types** from `list_blocks()`: `DimensionList`, `TransactionList`, `Metric`, `Table`. Both list types use the list export endpoint.
- **Pigment raw export API** (verified 2026-09-24 with the current key): list, metric and table exports all work. A list export's first column is the list itself. Metric and table exports put dimension columns first, then values.
- Some Pigment metrics hold user-level data (for example `SEC - Raw Data Visibility`). Don't paste export contents anywhere shared.
