from __future__ import annotations

import logging
import multiprocessing as mp
import os
from dataclasses import dataclass
from multiprocessing.connection import Connection

from .config import ExtractionConfig
from .geometry import BBox
from .worker import worker_main

logger = logging.getLogger(__name__)

# Windows (and macOS) default to "spawn", which re-imports `ifc_extractor`
# in the child rather than forking - required for this to work reliably
# from a Jupyter kernel. Setting it explicitly keeps behavior consistent
# across platforms instead of depending on the interpreter's default.
_MP_CONTEXT = mp.get_context("spawn")

# How often to poll for a message when waiting on the worker, and (when
# nothing arrives) how often to log a "still working" heartbeat. A silent
# phase that goes on for minutes with no output is indistinguishable from
# a genuine hang from the notebook, especially now that the placement
# pre-filter eagerly triangulates every anchor's own group up front before
# any per-anchor progress line prints - so this exists purely for
# visibility, independent of (and much shorter than) the actual timeouts.
_HEARTBEAT_SECONDS = 5.0


@dataclass
class SkippedAnchor:
    model_name: str
    guid: str
    reason: str


@dataclass
class SkippedElement:
    """A non-anchor element (e.g. a wall or space used only for the
    proximity search, or an anchor's own decomposition part) whose
    geometry couldn't be resolved within the timeout. It's dropped from
    consideration - as if it had no representation at all - rather than
    failing whatever anchor needed it.
    """

    model_name: str
    guid: str


class _WorkerStalled(Exception):
    """Raised when the worker process goes silent for too long, or dies
    outright, while `_ModelWorker` is waiting on it. `reason` is a
    human-readable phrase for the log message (e.g. "timed out after
    240s" or "the worker process died unexpectedly").
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ProgressTracker:
    """Tracks which (model, anchor) pairs have already been processed, so
    re-running the pipeline skips completed work. Backed by a plain text
    file of `f"{model_name}__{anchor_guid}"` lines, matching the original
    notebook's format.
    """

    def __init__(self, progress_file: str) -> None:
        self._progress_file = progress_file
        self._processed: set[str] = set()
        if os.path.exists(progress_file):
            with open(progress_file, "r") as f:
                self._processed = set(f.read().splitlines())

    def is_done(self, key: str) -> bool:
        return key in self._processed

    def mark_done(self, key: str) -> None:
        self._processed.add(key)
        with open(self._progress_file, "a") as f:
            f.write(key + "\n")


class _ModelWorker:
    """Owns the worker process for one input file.

    A single slow (or genuinely hung) element's geometry shouldn't force
    retriangulating the whole model: this class keeps a running
    `_known_bboxes` cache, fed continuously by ("attempt", guid) / ("bbox",
    guid, box) progress messages from the worker (see `worker.py`), and
    reseeds it into every freshly spawned process. A restart therefore
    only ever repeats work the dead worker hadn't reported back yet.
    """

    def __init__(
        self,
        input_ifc: str,
        model_name: str,
        config: ExtractionConfig,
        skipped_elements: list[SkippedElement],
    ) -> None:
        self._input_ifc = input_ifc
        self._model_name = model_name
        self._config = config
        self._skipped_elements = skipped_elements
        self._known_bboxes: dict[str, BBox | None] = {}
        self._in_flight_guid: str | None = None
        self._in_finalize_phase = False
        self._process, self._conn = self._spawn()

    def _spawn(self) -> tuple[mp.process.BaseProcess, Connection]:
        parent_conn, child_conn = _MP_CONTEXT.Pipe()
        process = _MP_CONTEXT.Process(
            target=worker_main,
            args=(child_conn, self._input_ifc, self._model_name, self._config, dict(self._known_bboxes)),
            daemon=True,
        )
        process.start()
        self._in_flight_guid = None
        self._in_finalize_phase = False
        return process, parent_conn

    def _restart(self) -> None:
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=5)
            if self._process.is_alive():
                # terminate() (SIGTERM) didn't take within a reasonable
                # window - fall back to an unconditional kill (SIGKILL) so
                # this can never block forever, defeating the whole point
                # of the timeout.
                self._process.kill()
                self._process.join()
        self._process, self._conn = self._spawn()

    def _drop_stuck_element(self, guid: str, reason: str, next_step: str) -> None:
        """Record `guid` as skipped and blacklist it (as if it had no
        geometry) so no future worker - in this run - ever attempts it
        again."""
        logger.warning(
            "%s while resolving geometry for %s - dropping it and %s.",
            reason,
            guid,
            next_step,
        )
        self._skipped_elements.append(SkippedElement(self._model_name, guid))
        self._known_bboxes[guid] = None

    def _log_heartbeat(self, elapsed: float) -> None:
        if self._in_finalize_phase:
            logger.info(
                "Still working - finalizing an anchor's extraction (proximity search / write), %.0fs so far...",
                elapsed,
            )
        elif self._in_flight_guid is not None:
            logger.info(
                "Still working - resolving geometry for %s, %.0fs so far...", self._in_flight_guid, elapsed
            )
        else:
            logger.info("Still working - opening/indexing %s, %.0fs so far...", self._model_name, elapsed)

    def _pump(self, timeout: float | None, finalize_timeout: float | None) -> tuple:
        """Wait for the next terminal (non-progress) message.

        Both timeouts are *stall* timeouts: they reset every time the
        worker reports progress, so a model that's simply large - and
        steadily working through it - is never punished, only a worker
        that's gone silent for that long on a single element. `None`
        disables the relevant one and waits indefinitely for it.

        `timeout` covers resolving element geometry (the phase that can
        call into IfcOpenShell's triangulation, which is what's actually
        known to hang); `finalize_timeout` takes over once the worker
        reports it has moved on to the proximity search and write-to-disk
        step for an anchor (see the "finalizing" message in `worker.py`),
        which never triangulates anything.

        Polls in short (`_HEARTBEAT_SECONDS`) increments rather than
        waiting the full timeout in one call, logging a heartbeat each time
        nothing arrives - purely for visibility, so a long-but-healthy wait
        (a single slow element, or just a lot of them) never looks
        indistinguishable from a hang. This doesn't change when the
        timeout itself fires, just how often we check in.
        """
        current_timeout = timeout
        elapsed = 0.0
        while True:
            if current_timeout is not None and elapsed >= current_timeout:
                raise _WorkerStalled(f"Timed out after {current_timeout:.0f}s")

            wait = _HEARTBEAT_SECONDS if current_timeout is None else min(_HEARTBEAT_SECONDS, current_timeout - elapsed)

            if not self._conn.poll(wait):
                elapsed += wait
                self._log_heartbeat(elapsed)
                continue

            elapsed = 0.0
            try:
                message = self._conn.recv()
            except (EOFError, OSError) as exc:
                raise _WorkerStalled("The worker process died unexpectedly") from exc

            kind = message[0]

            if kind == "attempt":
                self._in_flight_guid = message[1]
                self._in_finalize_phase = False
                current_timeout = timeout
                continue
            if kind == "bbox":
                _, guid, box = message
                self._known_bboxes[guid] = box
                self._in_flight_guid = None
                current_timeout = timeout
                continue
            if kind == "finalizing":
                self._in_flight_guid = None
                self._in_finalize_phase = True
                current_timeout = finalize_timeout
                continue
            if kind == "missing_anchors":
                for guid in message[1]:
                    logger.warning(
                        "Requested anchor %s not found in %s - skipping", guid, self._model_name
                    )
                continue

            return message

    def ready(self) -> list[str]:
        """Wait for the worker to open the file and index its candidate
        and anchor elements, restarting past any single element whose
        geometry stalls for longer than the configured timeout."""
        timeout = self._config.anchor_timeout_seconds
        while True:
            try:
                message = self._pump(timeout, timeout)
            except _WorkerStalled as exc:
                stuck_guid = self._in_flight_guid
                if stuck_guid is None:
                    raise RuntimeError(
                        f"{exc.reason} opening/indexing {self._model_name} - no element was in flight"
                    ) from exc

                self._drop_stuck_element(stuck_guid, exc.reason, "resuming indexing")
                self._restart()
                continue

            kind = message[0]
            if kind == "fatal":
                raise RuntimeError(f"Failed to open {self._model_name}: {message[1]}")
            return message[1]

    def process_anchor(self, guid: str) -> tuple[int, str] | None:
        """Process one anchor, returning its (extracted element count,
        output file path), or None if it (or an element it needed) had to
        be skipped."""
        self._conn.send(guid)
        timeout = self._config.anchor_timeout_seconds
        finalize_timeout = self._config.finalize_timeout_seconds

        while True:
            try:
                message = self._pump(timeout, finalize_timeout)
            except _WorkerStalled as exc:
                stuck_guid = self._in_flight_guid

                if stuck_guid is not None and stuck_guid != guid:
                    # A part of this anchor's own decomposition group (not
                    # necessarily the anchor itself) stalled - drop just
                    # that element, already seeded, and retry the anchor.
                    self._drop_stuck_element(stuck_guid, exc.reason, f"retrying {guid}")
                    self._restart()
                    self.ready()  # resync; already seeded, so this is near-instant
                    self._conn.send(guid)
                    continue

                phase = (
                    "finalizing it (proximity search / write)"
                    if self._in_finalize_phase
                    else "resolving its own geometry"
                )
                logger.warning("%s while %s for %s - skipping it and moving on.", exc.reason, phase, guid)
                self._restart()
                self.ready()  # resync for whatever anchor is requested next
                return None

            kind = message[0]
            if kind == "error":
                raise RuntimeError(f"Failed to process {guid} in {self._model_name}: {message[2]}")
            _, _, extracted_count, output_file = message
            return extracted_count, output_file

    def stop(self) -> None:
        if not self._process.is_alive():
            return
        try:
            self._conn.send("stop")
        except (BrokenPipeError, OSError):
            pass
        self._process.join(timeout=5)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=5)
            if self._process.is_alive():
                self._process.kill()
                self._process.join()


def process_ifc(
    input_ifc: str,
    model_name: str,
    config: ExtractionConfig,
    progress: ProgressTracker,
    skipped_anchors: list[SkippedAnchor] | None = None,
    skipped_elements: list[SkippedElement] | None = None,
) -> None:
    logger.info("Processing: %s", model_name)

    if skipped_anchors is None:
        skipped_anchors = []
    if skipped_elements is None:
        skipped_elements = []

    anchor_label = "requested anchor" if config.anchor_guids else config.anchor_type

    worker = _ModelWorker(input_ifc, model_name, config, skipped_elements)
    try:
        anchor_guids = worker.ready()
        logger.info("Total %s: %d", anchor_label, len(anchor_guids))

        for index, guid in enumerate(anchor_guids):
            logger.info("Processing %s %d/%d", anchor_label, index + 1, len(anchor_guids))

            process_key = f"{model_name}__{guid}"
            if progress.is_done(process_key):
                logger.info("Already processed")
                continue

            result = worker.process_anchor(guid)
            if result is None:
                skipped_anchors.append(SkippedAnchor(model_name, guid, "timeout"))
                continue

            extracted_count, output_file = result
            logger.info("Total extracted: %d", extracted_count)
            logger.info("Saved: %s", output_file)

            progress.mark_done(process_key)
    finally:
        worker.stop()


def run_pipeline(config: ExtractionConfig) -> None:
    os.makedirs(config.output_folder, exist_ok=True)
    progress_file = os.path.join(config.output_folder, "processed.txt")
    progress = ProgressTracker(progress_file)

    skipped_anchors: list[SkippedAnchor] = []
    skipped_elements: list[SkippedElement] = []

    for filename in config.ifc_queue:
        input_ifc = os.path.join(config.input_folder, filename)
        model_name = os.path.splitext(filename)[0]
        process_ifc(input_ifc, model_name, config, progress, skipped_anchors, skipped_elements)

    logger.info("ALL FILES FINISHED.")

    if skipped_elements:
        logger.warning(
            "Dropped %d element(s) whose geometry exceeded the timeout "
            "(excluded from consideration, not fatal):",
            len(skipped_elements),
        )
        for item in skipped_elements:
            logger.warning("  %s__%s", item.model_name, item.guid)

    anchor_label = "requested anchor" if config.anchor_guids else config.anchor_type

    if skipped_anchors:
        logger.warning(
            "Skipped %d %s(s) that exceeded the timeout:",
            len(skipped_anchors),
            anchor_label,
        )
        for item in skipped_anchors:
            logger.warning("  %s__%s", item.model_name, item.guid)
    else:
        logger.info("No %s(s) were skipped.", anchor_label)
