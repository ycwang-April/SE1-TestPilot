"""Readable run names; artifact schemas and workflow state stay unchanged."""

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

RUN_TIMEZONE = timezone(timedelta(hours=8))
RUN_PATTERN = re.compile(
    r"(?P<project>[a-z0-9][a-z0-9_-]*)-(?P<mode>deepseek|demo)-"
    r"(?P<backend>docker|local)-(?P<timestamp>\d{8}-\d{6})-(?P<id>[a-f0-9]{8})"
)


def project_slug(name: str) -> str:
    """Bounded ASCII filename component, never a path or Windows device name."""
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9_-]+", "-", normalized.lower()).strip("-_")[:48].rstrip("-_")
    devices = {"con", "prn", "aux", "nul"} | {
        f"{prefix}{n}" for prefix in ("com", "lpt") for n in range(1, 10)
    }
    return "project" if not slug or slug in devices else slug


def _reserve(parent: Path, stem: str, short_id: str | None = None) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    for _ in range(100):
        directory = parent / f"{stem}-{short_id or uuid4().hex[:8]}"
        try:
            directory.mkdir()  # Atomic reservation: never reuse another run's directory.
            return directory
        except FileExistsError:
            short_id = None
    raise FileExistsError("Unable to reserve a unique run directory")


def create_run_directory(
    output: Path, project: str, demo: bool, backend: str, *, started_at: datetime | None = None
) -> Path:
    if backend not in ("docker", "local"):
        raise ValueError("Unsupported run backend")
    started_at = started_at or datetime.now(RUN_TIMEZONE)
    timestamp = started_at.astimezone(RUN_TIMEZONE).strftime("%Y%m%d-%H%M%S")
    mode = "demo" if demo else "deepseek"
    return _reserve(output.resolve(), f"{project_slug(project)}-{mode}-{backend}-{timestamp}")


def finalize_backend(directory: Path, backend: str) -> Path:
    """Relabel a completed run using the observed backend, without rewriting artifacts."""
    directory = directory.resolve()
    match = RUN_PATTERN.fullmatch(directory.name)
    if not match or backend not in ("docker", "local") or match["backend"] == backend:
        return directory
    stem = f"{match['project']}-{match['mode']}-{backend}-{match['timestamp']}"
    destination = _reserve(directory.parent, stem, match["id"])
    # Both resolved directories must remain siblings inside the original output directory.
    if destination.resolve().parent != directory.parent:
        raise ValueError("Run destination must stay inside the output directory")
    for artifact in directory.iterdir():
        artifact.rename(destination / artifact.name)
    directory.rmdir()
    return destination


def run_time_and_id(directory: Path) -> tuple[str, str]:
    """Read start time from either new names or legacy UTC names; never infer from mtime."""
    match = RUN_PATTERN.fullmatch(directory.name)
    legacy = re.fullmatch(r"(\d{8}T\d{6}Z)-([a-f0-9]{8})", directory.name)
    try:
        if match:
            started = datetime.strptime(match["timestamp"], "%Y%m%d-%H%M%S").replace(
                tzinfo=RUN_TIMEZONE
            )
            short_id = match["id"]
        elif legacy:
            started = datetime.strptime(legacy[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            short_id = legacy[2]
        else:
            return "Unknown", "—"
        return started.astimezone(RUN_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S UTC+08:00"), short_id
    except ValueError:
        return "Unknown", "—"
