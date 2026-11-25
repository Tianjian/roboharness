"""Tests for provenance capture and verification."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from roboharness.approval.provenance import (
    PROVENANCE_SCHEMA_VERSION,
    ProvenanceError,
    attach_provenance,
    collect_git_metadata,
    collect_provenance,
    hash_file,
    require_provenance,
    verify_provenance,
    write_provenance,
)


class TestHashFile:
    def test_matches_hashlib(self, tmp_path: Path) -> None:
        target = tmp_path / "blob.bin"
        payload = b"roboharness-evidence" * 1000
        target.write_bytes(payload)
        assert hash_file(target) == hashlib.sha256(payload).hexdigest()

    def test_empty_file(self, tmp_path: Path) -> None:
        target = tmp_path / "empty.bin"
        target.write_bytes(b"")
        assert hash_file(target) == hashlib.sha256(b"").hexdigest()


class TestCollectGitMetadata:
    def test_returns_none_outside_git_repo(self, tmp_path: Path) -> None:
        # A bare temp dir is not a work tree unless the caller is inside one and
        # tmp_path happens to be nested -- resolve() makes that explicit.
        assert collect_git_metadata(tmp_path) is None

    def test_reads_this_repository(self) -> None:
        metadata = collect_git_metadata(Path())
        if metadata is None:  # pragma: no cover - exported tree without git
            pytest.skip("not inside a git work tree")
        assert len(metadata["sha"]) == 40
        assert isinstance(metadata["dirty"], bool)
        assert isinstance(metadata["branch"], str)


class TestCollectProvenance:
    def test_records_package_python_and_artifacts(self, tmp_path: Path) -> None:
        image = tmp_path / "lift" / "front_rgb.png"
        image.parent.mkdir()
        image.write_bytes(b"\x89PNG-fake")
        provenance = collect_provenance(tmp_path, [image])

        assert provenance["schema_version"] == PROVENANCE_SCHEMA_VERSION
        assert provenance["package"]["name"] == "roboharness"
        assert provenance["package"]["version"]
        assert provenance["python"]
        assert provenance["created_at"]
        assert provenance["artifacts"] == [
            {
                "path": str(Path("lift") / "front_rgb.png"),
                "sha256": hash_file(image),
                "bytes": image.stat().st_size,
            }
        ]
        assert "unhashed" not in provenance

    def test_accepts_relative_artifacts(self, tmp_path: Path) -> None:
        image = tmp_path / "a.png"
        image.write_bytes(b"x")
        provenance = collect_provenance(tmp_path, ["a.png"])
        assert provenance["artifacts"][0]["path"] == "a.png"

    def test_missing_artifacts_are_reported_not_dropped(self, tmp_path: Path) -> None:
        provenance = collect_provenance(tmp_path, ["absent.png"])
        assert provenance["artifacts"] == []
        assert provenance["unhashed"] == ["absent.png"]

    def test_package_version_override(self, tmp_path: Path) -> None:
        provenance = collect_provenance(tmp_path, [], package_version="9.9.9")
        assert provenance["package"]["version"] == "9.9.9"


class TestVerifyProvenance:
    def _provenance(self, tmp_path: Path) -> dict:
        image = tmp_path / "front_rgb.png"
        image.write_bytes(b"pixels")
        return collect_provenance(tmp_path, [image])

    def test_clean_round_trip(self, tmp_path: Path) -> None:
        assert verify_provenance(self._provenance(tmp_path), tmp_path) == []

    def test_detects_tampered_artifact(self, tmp_path: Path) -> None:
        provenance = self._provenance(tmp_path)
        (tmp_path / "front_rgb.png").write_bytes(b"different")
        problems = verify_provenance(provenance, tmp_path)
        assert len(problems) == 1
        assert "hash mismatch" in problems[0]

    def test_detects_missing_artifact(self, tmp_path: Path) -> None:
        provenance = self._provenance(tmp_path)
        (tmp_path / "front_rgb.png").unlink()
        problems = verify_provenance(provenance, tmp_path)
        assert problems and "missing" in problems[0]

    def test_detects_bad_schema_version(self, tmp_path: Path) -> None:
        provenance = self._provenance(tmp_path)
        provenance["schema_version"] = "nope/v0"
        problems = verify_provenance(provenance, tmp_path)
        assert any("schema_version" in problem for problem in problems)

    def test_detects_missing_created_at(self, tmp_path: Path) -> None:
        provenance = self._provenance(tmp_path)
        del provenance["created_at"]
        assert any("created_at" in problem for problem in verify_provenance(provenance, tmp_path))

    def test_detects_bad_artifacts_type(self, tmp_path: Path) -> None:
        provenance = self._provenance(tmp_path)
        provenance["artifacts"] = "not-a-list"
        assert any("artifacts" in problem for problem in verify_provenance(provenance, tmp_path))

    def test_detects_bad_git_type(self, tmp_path: Path) -> None:
        provenance = self._provenance(tmp_path)
        provenance["git"] = "deadbeef"
        assert any("git" in problem for problem in verify_provenance(provenance, tmp_path))

    def test_detects_malformed_artifact_entry(self, tmp_path: Path) -> None:
        provenance = self._provenance(tmp_path)
        provenance["artifacts"] = [{"path": "x.png"}]
        problems = verify_provenance(provenance, tmp_path)
        assert any("missing path/sha256" in problem for problem in problems)


class TestAttachAndRequire:
    def test_attach_adds_block_without_mutating_input(self) -> None:
        original = {"verdict": "PASS"}
        merged = attach_provenance(original, {"schema_version": PROVENANCE_SCHEMA_VERSION})
        assert "provenance" not in original
        assert merged["provenance"]["schema_version"] == PROVENANCE_SCHEMA_VERSION

    def test_attach_rejects_duplicate_block(self) -> None:
        with pytest.raises(ProvenanceError, match="already contains"):
            attach_provenance({"provenance": {}}, {"schema_version": "x"})

    def test_require_raises_when_absent(self) -> None:
        with pytest.raises(ProvenanceError, match="no 'provenance' block"):
            require_provenance({"verdict": "PASS"})

    def test_require_returns_block(self) -> None:
        assert require_provenance({"provenance": {"a": 1}}) == {"a": 1}

    def test_write_provenance_creates_json(self, tmp_path: Path) -> None:
        out = write_provenance({"schema_version": PROVENANCE_SCHEMA_VERSION}, tmp_path / "p.json")
        assert out.is_file()
        assert PROVENANCE_SCHEMA_VERSION in out.read_text()
