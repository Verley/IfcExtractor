# IFC Extractor

Given a reference IFC model, extracts one small IFC file per "anchor"
element (by default every `IfcStair`), containing that anchor plus any
nearby element of interest (walls, railings, slabs, spaces, ...). Useful for
producing focused per-element IFC extracts for review — e.g. checking a
single staircase and everything physically near it, without opening the
full model.

Run from [ifc-extractor.ipynb](ifc-extractor.ipynb) — that notebook is the
only way to run this tool.

## Features

- **Configurable anchor type** — extract around `IfcStair` (default),
  `IfcRamp`, or any other IFC entity type present in the model.
- **Configurable proximity distance** — how far (in meters) to search for
  nearby elements around each anchor.
- **Configurable nearby element types** — choose which element types
  (walls, members, railings, slabs, stair flights, spaces, ...) count as
  "nearby" and get included in each extract.
- **Configurable cleaning options** — optionally strip materials, styles,
  or owner history from the output.
- **Live progress log** — extraction progress (per file, per anchor,
  elements found) prints as it happens.
- **Resumable runs** — a `processed.txt` file is written to the output
  folder; re-running the same input/output pair skips anchors already
  extracted.

## Running

Requires Python 3.11 and the dependencies in `requirements.txt`.

```powershell
pip install -r requirements.txt
```

Open [ifc-extractor.ipynb](ifc-extractor.ipynb) and run its cells in order:

1. Imports `ExtractionConfig`, `CleaningOptions`, `run_pipeline`.
2. **CONFIGURATION** — edit `config` with your `input_folder`,
   `output_folder`, `ifc_queue` (the `.ifc` file names to process),
   `anchor_type`, `target_types`, `proximity_distance`, and `cleaning`
   options.
3. `run_pipeline(config)` — runs the extraction; progress prints below the
   cell as it goes.

### Example

Given:

```
C:\Models\Input\
  Building-A.ifc
  Building-B.ifc
```

Setting `input_folder` to `C:\Models\Input`, `output_folder` to
`C:\Models\Output`, `ifc_queue` to `["Building-A.ifc", "Building-B.ifc"]`,
`anchor_type` to `"IfcStair"`, and `proximity_distance` to `0.5`:

```python
from ifc_extractor import ExtractionConfig, CleaningOptions, run_pipeline

config = ExtractionConfig(
    input_folder=r"C:\Models\Input",
    output_folder=r"C:\Models\Output",
    ifc_queue=["Building-A.ifc", "Building-B.ifc"],
    anchor_type="IfcStair",
    target_types=["IfcWall", "IfcRailing", "IfcSlab"],
    proximity_distance=0.5,
    cleaning=CleaningOptions(remove_owner_history=True),
)
run_pipeline(config)
```

produces one file per staircase found in each model, e.g.:

```
C:\Models\Output\
  Building-A_stair_1h6dJPWa14QhkSAK3g0f8k.ifc
  Building-A_stair_2p9fLQr823JhmVYT9d1m0z.ifc
  Building-B_stair_3xQqQ6rMj9DEHb0wcqx09c.ifc
  processed.txt
```

Each output file contains one staircase (its flight and landing) plus every
wall, railing, and slab within 0.5 m of it, with owner history stripped,
following the source model's schema otherwise unchanged.

Re-running the same input/output folders skips staircases already listed in
`processed.txt` and only processes new or previously-failed anchors — useful
for resuming after an interrupted run or after dropping new files into the
input folder.

## Troubleshooting

- **Errors during extraction** — the run stops and raises, but any anchors
  already written before the error stay on disk and are marked done in
  `processed.txt`.
- **Verifying output visually** — open the extracted file next to the
  original in a viewer such as BIM Vision. Automated tests cover geometry
  correctness, but a visual side-by-side is the final check for anything
  subtle.

## Tests

```powershell
pip install -r requirements-dev.txt
python -m pytest tests/
```

## License

This project is licensed under the [MIT License](LICENSE).

It depends on [IfcOpenShell](https://ifcopenshell.org/), licensed under the
**GNU Lesser General Public License v3.0 or later (LGPL-3.0+)**, used here
as an unmodified library via `pip`.
