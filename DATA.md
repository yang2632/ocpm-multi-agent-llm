# Data: BPI Challenge 2017 OCEL 2.0

The thesis evaluation uses the **Business Process Intelligence Challenge 2017** event log, converted to **OCEL 2.0** format.

## Source

- **Original CSV / XES**: 4TU.ResearchData
  - DOI: `10.4121/uuid:5f3067df-f10b-45da-b98b-86ae4c7a310b`
  - URL: <https://data.4tu.nl/datasets/5f3067df-f10b-45da-b98b-86ae4c7a310b>
- **Description**: Loan-application process from a Dutch financial institution (January 2016 – February 2017).
- **Citation**:
  > Van Dongen, B.F. (Boudewijn) (2017). BPI Challenge 2017. 4TU.ResearchData. Dataset.

## What we use

After conversion to OCEL 2.0:

- **Events**: 1,202,267
- **Object types**: 4 (`Application`, `Offer`, `Workflow`, `Case_R`)
- **Objects**: 106,162 total
  - Application: 31,509
  - Offer: 42,995
  - Workflow: 31,509
  - Case_R: 149
- **Activities**: 26
- **E2O relations**: 2,404,534
- **O2O relations**: 74,504
- **Time span**: ~397 days

## How to obtain the data

1. Download the original BPI 2017 challenge data from 4TU.ResearchData (link above).
2. Convert to OCEL 2.0. We used the standard conversion provided by `pm4py`. A minimal example:

```python
import pm4py
log = pm4py.read_xes("BPI_Challenge_2017.xes")
# Convert to OCEL using application + offer as object types
ocel = pm4py.convert.convert_log_to_ocel(
    log,
    activity_column="concept:name",
    timestamp_column="time:timestamp",
    object_types=["Application", "Offer", "Workflow", "Case_R"],
)
pm4py.write_ocel2(ocel, "data/bpi2017_ocel2.json")
```

3. Place the converted log under `data/bpi2017_ocel2.json` (or set `DATA_PATH` in `.env`).

## Why we don't redistribute the data here

- File size (~680 MB) exceeds GitHub's recommended repository size.
- The original dataset is publicly archived under permissive academic-research terms; redistributing a derived copy here would duplicate that archive without adding value.
- The conversion script (above) is fully deterministic, so any reader can reproduce our exact OCEL 2.0 file from the original 4TU archive.

## License of the underlying data

The BPI 2017 event log is published under 4TU.ResearchData terms. Please consult the dataset page for details.
