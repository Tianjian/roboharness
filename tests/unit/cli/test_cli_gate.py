"""CLI tests for the approval gate verb."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from roboharness.cli import main

if TYPE_CHECKING:
    import pytest


def _write_report(tmp_path: Path, verdict: str, **overrides: object) -> Path:
    document = {
        "schema_version": "roboharness_report/v1",
        "overall_verdict": verdict,
        "surfaced_cases": [],
        "user_action": {"needs_review": False, "needs_baseline_blessing": False},
        **overrides,
    }
    path = tmp_path / "approval_report.json"
    path.write_text(json.dumps(document))
    return path


class TestGateCommand:
    def test_pass_returns_zero(self, tmp_path: Path) -> None:
        assert main(["gate", str(_write_report(tmp_path, "PASS"))]) == 0

    def test_fail_returns_one(self, tmp_path: Path) -> None:
        assert main(["gate", str(_write_report(tmp_path, "FAIL"))]) == 1

    def test_surfaced_case_returns_two(self, tmp_path: Path) -> None:
        report = _write_report(
            tmp_path,
            "PASS",
            surfaced_cases=[{"case_id": "trial_001", "status": "CHANGED"}],
        )
        assert main(["gate", str(report)]) == 2

    def test_missing_artefact_returns_contract_invalid(self, tmp_path: Path) -> None:
        assert main(["gate", str(tmp_path / "nope")]) == 3

    def test_json_format_emits_decision(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["gate", str(_write_report(tmp_path, "PASS")), "--format", "json"])
        payload = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert payload["verdict"] == "PASS"
        assert payload["exit_code"] == 0
        assert payload["schema_version"] == "roboharness_gate/v1"

    def test_require_provenance_without_block_returns_contract_invalid(
        self, tmp_path: Path
    ) -> None:
        report = _write_report(tmp_path, "PASS")
        assert main(["gate", str(report), "--require-provenance"]) == 3

    def test_human_output_mentions_verdict(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["gate", str(_write_report(tmp_path, "FAIL"))])
        out = capsys.readouterr().out
        assert "Gate: FAIL" in out
        assert "reason:" in out
