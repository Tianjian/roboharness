"""Provenance binding for approval artefacts.

A proof pack is only trustworthy if a reviewer can tell *what code produced it*
and *whether the pixels still match what was hashed*. Without that binding a
report is an unattributed document: it may be the right evidence, from the
wrong commit, edited afterwards.

This module records a small, deterministic provenance block and can re-verify
it. It is intentionally dependency-free (stdlib only) so it works in any
environment that can run the CLI.

Schema (``roboharness_provenance/v1``)::

    {
      "schema_version": "roboharness_provenance/v1",
      "created_at": "2026-11-25T05:00:00+00:00",
      "package": {"name": "roboharness", "version": "0.3.1"},
      "python": "3.12.3",
      "git": {"sha": "6fccea3...", "branch": "main", "dirty": false},
      "artifacts": [
        {"path": "lift/front_rgb.png", "sha256": "…", "bytes": 53988},
        …
      ]
    }

``git`` is ``None`` when the call is not inside a git work tree (for example a
zitted artefact unpacked on a review machine).
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from roboharness._utils import save_json

PROVENANCE_SCHEMA_VERSION = "roboharness_provenance/v1"

_GIT_TIMEOUT_S = 10.0


class ProvenanceError(ValueError):
    """Raised when a provenance block is missing required structure."""


@dataclass(frozen=True)
class ArtifactDigest:
    """One hashed artifact entry."""

    path: str
    sha256: str
    bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "bytes": self.bytes}


def hash_file(path: str | Path, *, chunk_size: int = 1 << 20) -> str:
    """Return the hex sha256 of a file, streaming it in chunks."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_git(args: list[str], cwd: Path) -> str | None:
    """Run a git command and return stripped stdout, or None on any failure."""

    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def collect_git_metadata(root: str | Path) -> dict[str, Any] | None:
    """Return ``{sha, branch, dirty}`` for the work tree containing ``root``.

    Returns ``None`` when ``root`` is not inside a git work tree, or when git is
    unavailable. A provenance block that silently claims a commit it cannot
    prove would be worse than an explicit ``None``.
    """

    root_path = Path(root).resolve()
    sha = _run_git(["rev-parse", "HEAD"], root_path)
    if not sha:
        return None
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], root_path) or ""
    status = _run_git(["status", "--porcelain"], root_path)
    return {
        "sha": sha,
        "branch": branch,
        "dirty": bool(status),
    }


def collect_provenance(
    root: str | Path,
    artifacts: Iterable[str | Path] = (),
    *,
    package_version: str | None = None,
) -> dict[str, Any]:
    """Build a provenance block for ``root`` and an optional artifact list.

    Args:
        root: Directory the evidence belongs to. Relative artifact paths are
            recorded relative to this directory.
        artifacts: Files to hash (typically the images cited by the pack).
            Unreadable entries are skipped rather than raising, but skipping is
            recorded so a reviewer is never silently given fewer hashes.
        package_version: Override the reported package version.

    Returns:
        A JSON-serialisable dict matching ``PROVENANCE_SCHEMA_VERSION``.
    """

    root_path = Path(root).resolve()

    if package_version is None:
        from roboharness import __version__ as package_version

    resolved: list[Path] = []
    missing: list[str] = []
    for item in artifacts:
        candidate = Path(item)
        if not candidate.is_absolute():
            candidate = root_path / candidate
        if candidate.is_file():
            resolved.append(candidate)
        else:
            missing.append(str(item))

    digests: list[ArtifactDigest] = []
    for path in sorted(resolved):
        try:
            relative = path.resolve().relative_to(root_path)
        except ValueError:
            relative = Path(path.name)
        digests.append(
            ArtifactDigest(
                path=str(relative),
                sha256=hash_file(path),
                bytes=path.stat().st_size,
            )
        )

    provenance: dict[str, Any] = {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "package": {"name": "roboharness", "version": package_version},
        "python": platform.python_version(),
        "git": collect_git_metadata(root_path),
        "artifacts": [digest.to_dict() for digest in digests],
    }
    if missing:
        provenance["unhashed"] = sorted(missing)
    return provenance


def verify_provenance(
    provenance: Mapping[str, Any],
    root: str | Path,
) -> list[str]:
    """Re-verify a provenance block against the files on disk.

    Returns a list of human-readable problems; an empty list means every
    recorded artifact still matches its hash.
    """

    problems: list[str] = []

    schema_version = provenance.get("schema_version")
    if schema_version != PROVENANCE_SCHEMA_VERSION:
        problems.append(
            f"unsupported provenance schema_version: {schema_version!r} "
            f"(expected {PROVENANCE_SCHEMA_VERSION!r})"
        )

    if "created_at" not in provenance:
        problems.append("provenance is missing 'created_at'")

    git = provenance.get("git")
    if git is not None and not isinstance(git, Mapping):
        problems.append("provenance 'git' must be an object or null")

    artifacts = provenance.get("artifacts")
    if not isinstance(artifacts, list):
        problems.append("provenance 'artifacts' must be a list")
        return problems

    root_path = Path(root)
    for entry in artifacts:
        if not isinstance(entry, Mapping):
            problems.append(f"artifact entry is not an object: {entry!r}")
            continue
        raw_path = entry.get("path")
        recorded = entry.get("sha256")
        if not isinstance(raw_path, str) or not isinstance(recorded, str):
            problems.append(f"artifact entry missing path/sha256: {entry!r}")
            continue
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = root_path / candidate
        if not candidate.is_file():
            problems.append(f"artifact missing: {raw_path}")
            continue
        actual = hash_file(candidate)
        if actual != recorded:
            problems.append(
                f"artifact hash mismatch: {raw_path} (recorded {recorded[:12]}…, "
                f"actual {actual[:12]}…)"
            )

    return problems


def attach_provenance(
    payload: Mapping[str, Any],
    provenance: Mapping[str, Any],
    *,
    key: str = "provenance",
) -> dict[str, Any]:
    """Return a copy of ``payload`` with a provenance block attached."""

    if key in payload:
        raise ProvenanceError(f"payload already contains a {key!r} block")
    merged = dict(payload)
    merged[key] = dict(provenance)
    return merged


def require_provenance(payload: Mapping[str, Any], *, key: str = "provenance") -> dict[str, Any]:
    """Return the provenance block from ``payload`` or raise ``ProvenanceError``."""

    provenance = payload.get(key)
    if not isinstance(provenance, Mapping):
        raise ProvenanceError(
            f"artefact has no {key!r} block; re-run with provenance enabled "
            "so the evidence can be attributed to a commit"
        )
    return dict(provenance)


def write_provenance(provenance: Mapping[str, Any], path: str | Path) -> Path:
    """Write a provenance block to JSON."""

    output_path = Path(path)
    save_json(dict(provenance), output_path)
    return output_path


__all__ = [
    "PROVENANCE_SCHEMA_VERSION",
    "ArtifactDigest",
    "ProvenanceError",
    "attach_provenance",
    "collect_git_metadata",
    "collect_provenance",
    "hash_file",
    "require_provenance",
    "verify_provenance",
    "write_provenance",
]
