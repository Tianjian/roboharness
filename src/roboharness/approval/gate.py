"""Approval gate: turn an approval artefact into a process exit code.

The trust loop ends in a JSON decision (``approval_report.json`` or a case
``proof_pack.json``). Until that decision can refuse a merge, the loop is
advisory: an agent can break behaviour and CI still passes.

This module is the mechanical bridge. It reads an artefact, derives the
four-value verdict from the product contract, and maps it to an exit code:

===============  ======  ================================================
verdict          exit    meaning
===============  ======  ================================================
PASS             0       no material change, evidence complete
FAIL             1       a hard contract rule was violated
AMBIGUOUS        2       a human must look (surfaced case, review needed,
                         or a migration pending baseline blessing)
CONTRACT_INVALID 3       the decision itself cannot be trusted (missing or
                         malformed artefact, broken provenance)
===============  ======  ================================================

The mapping is deliberately conservative: anything that makes the *decision*
untrustworthy outranks anything about the behaviour, and any surfaced case
means the run is not a clean pass.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roboharness._utils import load_json as _load_json
from roboharness.approval.provenance import (
    ProvenanceError,
    require_provenance,
    verify_provenance,
)

PASS = "PASS"
FAIL = "FAIL"
AMBIGUOUS = "AMBIGUOUS"
CONTRACT_INVALID = "CONTRACT_INVALID"

VERDICTS: tuple[str, ...] = (PASS, FAIL, AMBIGUOUS, CONTRACT_INVALID)

EXIT_CODES: dict[str, int] = {
    PASS: 0,
    FAIL: 1,
    AMBIGUOUS: 2,
    CONTRACT_INVALID: 3,
}

APPROVAL_REPORT_NAME = "approval_report.json"
PROOF_PACK_NAME = "proof_pack.json"

# Verdict spellings other surfaces use. "DEGRADED" is the assertion engine's
# middle verdict; it is not a clean pass, so it maps to a human review.
_VERDICT_ALIASES: dict[str, str] = {
    "PASS": PASS,
    "PASSED": PASS,
    "OK": PASS,
    "FAIL": FAIL,
    "FAILED": FAIL,
    "DEGRADED": AMBIGUOUS,
    "AMBIGUOUS": AMBIGUOUS,
    "NEEDS_REVIEW": AMBIGUOUS,
    "NEEDS_HUMAN": AMBIGUOUS,
    "CONTRACT_INVALID": CONTRACT_INVALID,
    "INVALID": CONTRACT_INVALID,
}


class GateInputError(ValueError):
    """Raised when no decidable approval artefact can be located."""


@dataclass(frozen=True)
class GateDecision:
    """A decided gate outcome, suitable for CI and for JSON output."""

    verdict: str
    exit_code: int
    reason: str
    source: str | None = None
    surfaced_cases: tuple[str, ...] = ()
    needs_human: bool = False
    needs_baseline_blessing: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "roboharness_gate/v1",
            "verdict": self.verdict,
            "exit_code": self.exit_code,
            "reason": self.reason,
            "source": self.source,
            "surfaced_cases": list(self.surfaced_cases),
            "needs_human": self.needs_human,
            "needs_baseline_blessing": self.needs_baseline_blessing,
        }


def normalize_verdict(value: Any) -> str:
    """Map a raw verdict string onto one of the four contract verdicts."""

    if not isinstance(value, str):
        return CONTRACT_INVALID
    return _VERDICT_ALIASES.get(value.strip().upper(), CONTRACT_INVALID)


def resolve_approval_artefact(path: str | Path) -> Path:
    """Resolve ``path`` to a single approval artefact.

    Accepts the artefact itself, a case directory containing one, or a run
    directory containing exactly one nested case that has one.
    """

    candidate = Path(path)
    if candidate.is_file():
        return candidate
    if not candidate.exists():
        raise GateInputError(f"path does not exist: {candidate}")
    if not candidate.is_dir():
        raise GateInputError(f"path is neither a file nor a directory: {candidate}")

    direct = candidate / APPROVAL_REPORT_NAME
    if direct.is_file():
        return direct
    direct_pack = candidate / PROOF_PACK_NAME
    if direct_pack.is_file():
        return direct_pack

    nested = sorted(candidate.glob(f"*/{APPROVAL_REPORT_NAME}"))
    if len(nested) == 1:
        return nested[0]
    if len(nested) > 1:
        raise GateInputError(
            f"{candidate} contains {len(nested)} approval reports; pass one explicitly"
        )

    raise GateInputError(f"no {APPROVAL_REPORT_NAME} or {PROOF_PACK_NAME} found under {candidate}")


def _surfaced_case_ids(document: Mapping[str, Any]) -> tuple[str, ...]:
    raw = document.get("surfaced_cases")
    if not isinstance(raw, list):
        return ()
    ids: list[str] = []
    for entry in raw:
        if isinstance(entry, Mapping):
            case_id = entry.get("case_id") or entry.get("id")
            if case_id:
                ids.append(str(case_id))
        elif isinstance(entry, str):
            ids.append(entry)
    return tuple(ids)


def _user_action(document: Mapping[str, Any]) -> Mapping[str, Any]:
    action = document.get("user_action")
    return action if isinstance(action, Mapping) else {}


def decide(
    document: Mapping[str, Any],
    *,
    source: str | None = None,
    require_provenance_binding: bool = False,
    evidence_root: str | Path | None = None,
) -> GateDecision:
    """Derive a :class:`GateDecision` from a loaded approval artefact.

    Args:
        document: Parsed ``approval_report.json`` or ``proof_pack.json``.
        source: Human-readable path recorded in the decision.
        require_provenance_binding: Treat a missing or broken provenance block
            as ``CONTRACT_INVALID``. Without it the gate still decides the
            behaviour verdict, but the decision is not attributed to a commit.
        evidence_root: Directory artifact hashes are resolved against. Defaults
            to the directory of ``source`` when it is a path.
    """

    raw_verdict = document.get("overall_verdict", document.get("verdict"))
    verdict = normalize_verdict(raw_verdict)
    surfaced = _surfaced_case_ids(document)
    action = _user_action(document)
    needs_review = bool(action.get("needs_review"))
    needs_blessing = bool(action.get("needs_baseline_blessing"))

    if raw_verdict is None:
        return GateDecision(
            verdict=CONTRACT_INVALID,
            exit_code=EXIT_CODES[CONTRACT_INVALID],
            reason="artefact has neither 'overall_verdict' nor 'verdict'",
            source=source,
            surfaced_cases=surfaced,
            needs_human=needs_review,
            needs_baseline_blessing=needs_blessing,
        )

    if verdict == CONTRACT_INVALID:
        return GateDecision(
            verdict=CONTRACT_INVALID,
            exit_code=EXIT_CODES[CONTRACT_INVALID],
            reason=f"unrecognised verdict {raw_verdict!r}",
            source=source,
            surfaced_cases=surfaced,
            needs_human=needs_review,
            needs_baseline_blessing=needs_blessing,
        )

    if require_provenance_binding:
        root = Path(evidence_root) if evidence_root is not None else None
        if root is None and source is not None:
            root = Path(source).resolve().parent
        try:
            provenance = require_provenance(document)
        except ProvenanceError as exc:
            return GateDecision(
                verdict=CONTRACT_INVALID,
                exit_code=EXIT_CODES[CONTRACT_INVALID],
                reason=str(exc),
                source=source,
                surfaced_cases=surfaced,
                needs_human=needs_review,
                needs_baseline_blessing=needs_blessing,
            )
        problems = verify_provenance(provenance, root or Path())
        if problems:
            detail = "; ".join(problems[:5])
            more = "" if len(problems) <= 5 else f" (+{len(problems) - 5} more)"
            return GateDecision(
                verdict=CONTRACT_INVALID,
                exit_code=EXIT_CODES[CONTRACT_INVALID],
                reason=f"provenance verification failed: {detail}{more}",
                source=source,
                surfaced_cases=surfaced,
                needs_human=needs_review,
                needs_baseline_blessing=needs_blessing,
            )

        # An artefact the pack asked to bind but could not read is the more
        # specific problem, so report it before the generic emptiness check.
        unhashed = provenance.get("unhashed")
        if isinstance(unhashed, list) and unhashed:
            listed = ", ".join(str(item) for item in unhashed[:5])
            more = "" if len(unhashed) <= 5 else f" (+{len(unhashed) - 5} more)"
            return GateDecision(
                verdict=CONTRACT_INVALID,
                exit_code=EXIT_CODES[CONTRACT_INVALID],
                reason=f"provenance could not hash {len(unhashed)} artifact(s): {listed}{more}",
                source=source,
                surfaced_cases=surfaced,
                needs_human=needs_review,
                needs_baseline_blessing=needs_blessing,
            )

        # A provenance block with no hashed artifacts attributes nothing: it
        # would let an evidence-free pack pass the "is this from my commit?"
        # check vacuously. Reject it rather than rubber-stamp it.
        artifacts = provenance.get("artifacts")
        if not artifacts:
            return GateDecision(
                verdict=CONTRACT_INVALID,
                exit_code=EXIT_CODES[CONTRACT_INVALID],
                reason=(
                    "provenance records no hashed artifacts; a pack with no bound "
                    "evidence cannot be verified"
                ),
                source=source,
                surfaced_cases=surfaced,
                needs_human=needs_review,
                needs_baseline_blessing=needs_blessing,
            )

    if verdict == FAIL:
        return GateDecision(
            verdict=FAIL,
            exit_code=EXIT_CODES[FAIL],
            reason="a hard contract rule was violated",
            source=source,
            surfaced_cases=surfaced,
            needs_human=needs_review,
            needs_baseline_blessing=needs_blessing,
        )

    # A PASS is only clean if nothing was surfaced and nobody has to look.
    reasons: list[str] = []
    if needs_blessing:
        reasons.append("migration result awaits explicit baseline blessing")
    if needs_review:
        reasons.append("artefact asks for human review")
    if surfaced:
        reasons.append(f"{len(surfaced)} case(s) surfaced for review")

    if reasons:
        return GateDecision(
            verdict=AMBIGUOUS,
            exit_code=EXIT_CODES[AMBIGUOUS],
            reason="; ".join(reasons),
            source=source,
            surfaced_cases=surfaced,
            needs_human=needs_review,
            needs_baseline_blessing=needs_blessing,
        )

    return GateDecision(
        verdict=PASS,
        exit_code=EXIT_CODES[PASS],
        reason="no material change surfaced; evidence complete",
        source=source,
        surfaced_cases=surfaced,
        needs_human=False,
        needs_baseline_blessing=False,
    )


def gate(
    path: str | Path,
    *,
    require_provenance_binding: bool = False,
    evidence_root: str | Path | None = None,
) -> GateDecision:
    """Locate, load, and decide the gate outcome for ``path``.

    Args:
        path: Approval artefact, case directory, or run directory.
        require_provenance_binding: Verify the provenance block and fail closed.
        evidence_root: Directory artifact hashes resolve against. Defaults to
            the artefact's directory, which is wrong when the decision file was
            copied away from the evidence it describes.
    """

    artefact = resolve_approval_artefact(path)
    document = _load_json(artefact)
    if not isinstance(document, Mapping):
        raise GateInputError(f"approval artefact is not a JSON object: {artefact}")
    return decide(
        document,
        source=str(artefact),
        require_provenance_binding=require_provenance_binding,
        evidence_root=evidence_root,
    )


__all__ = [
    "AMBIGUOUS",
    "APPROVAL_REPORT_NAME",
    "CONTRACT_INVALID",
    "EXIT_CODES",
    "FAIL",
    "PASS",
    "PROOF_PACK_NAME",
    "VERDICTS",
    "GateDecision",
    "GateInputError",
    "decide",
    "gate",
    "normalize_verdict",
    "resolve_approval_artefact",
]
