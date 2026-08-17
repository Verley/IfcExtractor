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
- **Explicit anchor list** — set `anchor_guids` to a list of specific
  GlobalIds to process just those elements instead of every `anchor_type`
  instance in the file. Useful for reprocessing a handful of elements (a
  previously skipped stair, one flagged for review, ...) without walking
  the whole model. IDs don't need to match `anchor_type`, and an ID not
  present in a given file is logged and skipped, so the same list can span
  several files in `ifc_queue`.
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
- **Per-element timeout** — some geometry (malformed stairs have been
  observed to trigger this) makes IfcOpenShell's shape triangulation hang
  indefinitely. All geometry is resolved in a worker process that's killed
  and restarted if it stalls on any single element for longer than
  `anchor_timeout_seconds` (default 4 minutes) - a stuck candidate element
  (a wall, space, etc. considered for the proximity search) is just
  dropped from that search, while a stuck anchor itself is skipped
  entirely. Nothing already resolved is ever recomputed after a restart,
  so one bad element can't stall - or repeatedly re-stall - the whole run.
  Everything skipped is listed once the run finishes. Set
  `anchor_timeout_seconds` to `None` to disable it and wait indefinitely
  instead.
- **Separate finalize timeout** — `finalize_timeout_seconds` (same default,
  independently configurable) covers an anchor's proximity search and
  write-to-disk step once its geometry is already resolved - a step that
  never triangulates anything, so a large-but-healthy extraction (many
  nearby elements) isn't held to the same tight budget that guards against
  a hung triangulation.
- **Placement pre-filter** — before triangulating a candidate element at
  all, its cheap `ObjectPlacement` origin is checked against every known
  anchor region first; anything farther than `proximity_distance +
  placement_prefilter_margin` (10 m by default) is skipped without ever
  calling into IfcOpenShell's geometry kernel. On a large model this
  means fewer triangulation calls overall (faster) and less exposure to
  whatever specific element might hang one (safer). It's a conservative,
  margined filter, not an exact one - see `use_placement_prefilter` and
  `placement_prefilter_margin` in [config.py](ifc_extractor/config.py) for
  the correctness tradeoff and how to tune or disable it.
- **Coarse triangulation for proximity checks** — the mesh tolerance used
  to compute an element's bounding box is loosened well below any
  reasonable `proximity_distance` (this never affects the extracted
  output, which copies IFC entities directly and never triangulates
  anything at all). Complex or degenerate curved geometry that would
  otherwise be tessellated to visualization-grade precision for no benefit
  triangulates noticeably faster as a result.
- **Progress heartbeat** — if the worker goes more than 5 seconds without
  reporting anything (e.g. one very large model, or one especially slow
  element), a "Still working..." line prints saying exactly what it's
  doing and for how long, so a long-but-healthy wait is never
  indistinguishable from an actual hang.

## Running

Requires Python 3.11 and the dependencies in `requirements.txt`.

```powershell
pip install -r requirements.txt
```

Open [ifc-extractor.ipynb](ifc-extractor.ipynb) and run its cells in order:

1. Imports `ExtractionConfig`, `CleaningOptions`, `run_pipeline`.
2. **CONFIGURATION** — edit `config` with your `input_folder`,
   `output_folder`, `ifc_queue` (the `.ifc` file names to process),
   `anchor_type`, `target_types`, `proximity_distance`, `cleaning` options,
   `anchor_timeout_seconds`, `finalize_timeout_seconds`,
   `use_placement_prefilter`, `placement_prefilter_margin`, and
   (optionally) `anchor_guids` to restrict the run to specific elements.
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
- **An anchor takes too long to process** — this happens when IfcOpenShell
  gets stuck triangulating a specific element's geometry (some malformed
  stairs are known to trigger this) and never returns. All geometry -
  every candidate element considered for the proximity search, and each
  anchor's own - is resolved in a worker process that's killed and
  restarted if it stalls on any single one of them for longer than
  `anchor_timeout_seconds` (4 minutes by default):

  - A stuck **candidate** element (e.g. a wall or space checked for
    proximity to some anchor) is dropped from the proximity search - as if
    it had no geometry at all - and every anchor keeps considering
    everything else.
  - A stuck **anchor** is skipped entirely.

  Either way, nothing already resolved before the stall is ever
  recomputed, so a single bad element can't repeatedly re-stall the whole
  run (which is what a naive "restart from scratch" retry would do on a
  large model, since rebuilding the proximity index for the very first
  anchor is the most expensive step). A worker that dies outright (e.g. a
  native crash while triangulating) is detected immediately, without
  waiting out the timeout, and handled the same way. Every skip is logged
  as it happens and the full lists are printed again at the end of the
  run, e.g.:

  ```
  Timed out after 240s while resolving geometry for 0Nq...zK - dropping it and resuming indexing.
  Timed out after 240s while resolving its own geometry for 1h6dJPWa14QhkSAK3g0f8k - skipping it and moving on.
  Timed out after 240s while finalizing it (proximity search / write) for 3xQ...09c - skipping it and moving on.
  ...
  Dropped 1 element(s) whose geometry exceeded the timeout (excluded from consideration, not fatal):
    Building-A__0Nq...zK
  Skipped 2 IfcStair(s) that exceeded the timeout:
    Building-A__1h6dJPWa14QhkSAK3g0f8k
    Building-A__3xQ...09c
  ```

  Skipped anchors are *not* marked done in `processed.txt`, so re-running
  the pipeline (optionally with a higher `anchor_timeout_seconds`) will
  retry them. The log line always says which phase timed out
  ("resolving its own geometry" vs. "finalizing it (proximity search /
  write)"), so you know which of the two settings below to adjust. Lower
  `anchor_timeout_seconds` to fail fast while tuning a problem file. If
  it's the proximity search / write step timing out on an anchor with an
  unusually large extraction set rather than geometry triangulation
  itself, raise `finalize_timeout_seconds` instead - it covers that step
  specifically. Set either to `None` to disable it and wait indefinitely
  instead, at the risk of a genuine hang stalling the run.
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
