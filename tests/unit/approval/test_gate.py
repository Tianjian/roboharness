"""Tests for the approval gate: verdict -> exit code."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from roboharness.approval.gate import (
    AMBIGUOUS,
    CONTRACT_INVALID,
    EXIT_CODES,
    FAIL,
    PASS,
    GateInputError,
    decide,
    gate,
    normalize_verdict,
    resolve_approval_artefact,
)
from roboharness.approval.provenance import PROVENANCE_SCHEMA_VERSION, hash_file


def _approval_report(
    verdict: str = "PASS",
    *,
    surfaced: list[dict[str, str]] | None = None,
    needs_review: bool = False,
    needs_blessing: bool = False,
) -> dict:
    return {
        "schema_version": "roboharness_report/v1",
        "overall_verdict": verdict,
        "surfaced_cases": surfaced or [],
        "user_action": {
            "needs_review": needs_review,
            "needs_baseline_blessing": needs_blessing,
            "review_case_ids": [],
        },
    }


class TestNormalizeVerdict:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("PASS", PASS),
            ("pass", PASS),
            ("PASSED", PASS),
            ("FAIL", FAIL),
            ("DEGRADED", AMBIGUOUS),
            ("AMBIGUOUS", AMBIGUOUS),
            ("NEEDS_HUMAN", AMBIGUOUS),
            ("CONTRACT_INVALID", CONTRACT_INVALID),
            ("garbage", CONTRACT_INVALID),
            (None, CONTRACT_INVALID),
            (42, CONTRACT_INVALID),
        ],
    )
    def test_mapping(self, raw: object, expected: str) -> None:
        assert normalize_verdict(raw) == expected


class TestDecide:
    def test_clean_pass_exits_zero(self) -> None:
        decision = decide(_approval_report())
        assert decision.verdict == PASS
        assert decision.exit_code == 0
        assert decision.exit_code == EXIT_CODES[PASS]

    def test_fail_exits_one(self) -> None:
        decision = decide(_approval_report("FAIL"))
        assert decision.verdict == FAIL
        assert decision.exit_code == 1

    def test_fail_wins_even_if_nothing_surfaced(self) -> None:
        decision = decide(_approval_report("FAIL", surfaced=[]))
        assert decision.verdict == FAIL

    def test_pass_with_surfaced_case_is_not_clean(self) -> None:
        decision = decide(_approval_report("PASS", surfaced=[{"case_id": "abc"}]))
        assert decision.verdict == AMBIGUOUS
        assert decision.exit_code == 2
        assert decision.surfaced_cases == ("abc",)

    def test_pass_needing_review_is_ambiguous(self) -> None:
        decision = decide(_approval_report("PASS", needs_review=True))
        assert decision.verdict == AMBIGUOUS
        assert decision.needs_human is True

    def test_migration_pass_needs_blessing(self) -> None:
        decision = decide(_approval_report("PASS", needs_blessing=True))
        assert decision.verdict == AMBIGUOUS
        assert decision.needs_baseline_blessing is True
        assert "blessing" in decision.reason

    def test_missing_verdict_is_contract_invalid(self) -> None:
        decision = decide({"schema_version": "x"})
        assert decision.verdict == CONTRACT_INVALID
        assert decision.exit_code == 3

    def test_unknown_verdict_is_contract_invalid(self) -> None:
        decision = decide({"overall_verdict": "banana"})
        assert decision.verdict == CONTRACT_INVALID

    def test_proof_pack_verdict_key_is_supported(self) -> None:
        decision = decide({"verdict": "PASS"})
        assert decision.verdict == PASS

    def test_missing_provenance_fails_closed_when_required(self) -> None:
        decision = decide(_approval_report(), require_provenance_binding=True)
        assert decision.verdict == CONTRACT_INVALID
        assert "provenance" in decision.reason

    def test_provenance_hash_mismatch_fails_closed(self, tmp_path: Path) -> None:
        image = tmp_path / "front_rgb.png"
        image.write_bytes(b"original-pixels")
        provenance = {
            "schema_version": PROVENANCE_SCHEMA_VERSION,
            "created_at": "2026-11-25T00:00:00+00:00",
            "package": {"name": "roboharness", "version": "0.3.1"},
            "git": None,
            "artifacts": [
                {"path": "front_rgb.png", "sha256": hash_file(image), "bytes": image.stat().st_size}
            ],
        }
        document = {**_approval_report(), "provenance": provenance}
        assert decide(document, evidence_root=tmp_path).verdict == PASS
        assert (
            decide(document, require_provenance_binding=True, evidence_root=tmp_path).verdict
            == PASS
        )

        image.write_bytes(b"tampered-pixels")
        tampered = decide(document, require_provenance_binding=True, evidence_root=tmp_path)
        assert tampered.verdict == CONTRACT_INVALID
        assert "hash mismatch" in tampered.reason

    def test_vacuous_provenance_is_rejected(self, tmp_path: Path) -> None:
        provenance = {
            "schema_version": PROVENANCE_SCHEMA_VERSION,
            "created_at": "2026-11-25T00:00:00+00:00",
            "git": None,
            "artifacts": [],
        }
        document = {**_approval_report(), "provenance": provenance}
        decision = decide(document, require_provenance_binding=True, evidence_root=tmp_path)
        assert decision.verdict == CONTRACT_INVALID
        assert "no hashed artifacts" in decision.reason

    def test_unhashed_artifacts_are_rejected(self, tmp_path: Path) -> None:
        provenance = {
            "schema_version": PROVENANCE_SCHEMA_VERSION,
            "created_at": "2026-11-25T00:00:00+00:00",
            "git": None,
            "artifacts": [],
            "unhashed": ["lift/front_rgb.png"],
        }
        document = {**_approval_report(), "provenance": provenance}
        decision = decide(document, require_provenance_binding=True, evidence_root=tmp_path)
        assert decision.verdict == CONTRACT_INVALID
        assert "could not hash" in decision.reason

    def test_to_dict_is_json_serialisable(self) -> None:
        payload = decide(_approval_report()).to_dict()
        assert payload["verdict"] == PASS
        assert payload["exit_code"] == 0
        json.dumps(payload)


class TestResolveArtefact:
    def test_accepts_direct_file(self, tmp_path: Path) -> None:
        report = tmp_path / "approval_report.json"
        report.write_text("{}")
        assert resolve_approval_artefact(report) == report

    def test_accepts_case_dir(self, tmp_path: Path) -> None:
        report = tmp_path / "approval_report.json"
        report.write_text("{}")
        assert resolve_approval_artefact(tmp_path) == report

    def test_accepts_single_nested_case(self, tmp_path: Path) -> None:
        nested = tmp_path / "trial_001"
        nested.mkdir()
        report = nested / "approval_report.json"
        report.write_text("{}")
        assert resolve_approval_artefact(tmp_path) == report

    def test_rejects_ambiguous_nesting(self, tmp_path: Path) -> None:
        for name in ("a", "b"):
            case = tmp_path / name
            case.mkdir()
            (case / "approval_report.json").write_text("{}")
        with pytest.raises(GateInputError, match="pass one explicitly"):
            resolve_approval_artefact(tmp_path)

    def test_rejects_missing_path(self, tmp_path: Path) -> None:
        with pytest.raises(GateInputError, match="does not exist"):
            resolve_approval_artefact(tmp_path / "nope")

    def test_rejects_dir_without_artefact(self, tmp_path: Path) -> None:
        (tmp_path / "readme.txt").write_text("hi")
        with pytest.raises(GateInputError, match=r"no approval_report\.json"):
            resolve_approval_artefact(tmp_path)


class TestGateEndToEnd:
    def test_gate_reads_report_and_decides(self, tmp_path: Path) -> None:
        report = tmp_path / "approval_report.json"
        report.write_text(json.dumps(_approval_report("FAIL")))
        decision = gate(report)
        assert decision.verdict == FAIL
        assert decision.source == str(report)

    def test_gate_rejects_non_object_json(self, tmp_path: Path) -> None:
        report = tmp_path / "approval_report.json"
        report.write_text(json.dumps([1, 2, 3]))
        with pytest.raises(GateInputError, match="not a JSON object"):
            gate(report)
