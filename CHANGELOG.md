# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- Added `roboharness gate`, which turns an `approval_report.json` or
  `proof_pack.json` into a process exit code (`PASS=0`, `FAIL=1`,
  `AMBIGUOUS=2`, `CONTRACT_INVALID=3`). The trust loop previously ended in a
  JSON decision that nothing could enforce in CI, so an agent could break
  behaviour while the pipeline stayed green.
- Added provenance binding in `roboharness.approval.provenance` (git sha,
  branch, dirty flag, package version, timestamp, and a sha256 per cited
  image). `proof-pack --provenance` writes the block; `gate --require-provenance`
  verifies it and fails closed when it is missing, vacuous, or no longer
  matches the pixels.

### Fixed

- Checkpoint capture no longer fails open. A checkpoint that produced zero
  images used to report success (`state.json` only, debug-level log), so the
  quickstart printed "Captures saved" with no screenshots. The wrapper now
  records `capture_failed` and `capture_errors` in `metadata.json`, warns with
  an actionable hint, and raises when built with `strict_capture=True`.
- `TaskProtocol` now rejects duplicate phase names. Duplicates registered two
  checkpoints against one snapshot slot, so a rollback could restore the wrong
  state while the evidence pack labelled it as another phase.
- `ruff format --check .` failed on eight Markdown files once ruff started
  formatting embedded code (ruff >= 0.15). Lint/format are now scoped to Python
  and `ruff` is pinned in CI and pre-commit (0.14.0), so the gate no longer
  drifts with the tool version.
- Declared the `mcp` extra; `roboharness.mcp.server` imported a package that no
  extra installed.
- `WbcIkController` told users to install `[demo]`; Pinocchio/Pink live in
  `[wbc]`.
- `CITATION.cff` drifted from the package: version `0.1.1` and a
  `MiaoDX/RobotHarness` URL that does not exist. Also corrected the CaP-X first
  author (Letian Fu, not "Max Fu").
- `dev` installs `gymnasium[classic-control]` so the zero-change quickstart can
  actually render instead of silently producing no images.
- Test environment: an unparseable `ALL_PROXY` (e.g. a bare `socks://` scheme)
  is dropped for the test session instead of breaking every Hugging Face
  download with an unrelated httpx error.

## [0.3.0] - 2026-04-20

### Added

- Added a shared paired-evidence contract in `roboharness.approval.evidence`,
  including bounded path resolution plus reusable lightbox/image helpers for
  approval surfaces.
- Added a second concrete consumer of that contract with
  `examples/g1_cross_framework_report.py`, backed by the committed
  `assets/g1/X36_Y28_Z13/` Meshcat-vs-MuJoCo proof bundle.
- Added a seeded MuJoCo approval corpus covering `good`, `bad`, and `ambiguous`
  review outcomes to lock the surfaced-case trust boundary.
- Added a script-level regression test proving `examples/mujoco_grasp.py`
  exits cleanly and writes `contract_compile_error.json` when contract
  compilation fails before execution.

### Changed

- Refactored the MuJoCo unattended-approval wedge to use the shared evidence
  contract instead of keeping paired-evidence logic local to the example.
- Expanded the MuJoCo proof surface with temporal evidence strips and
  click-to-zoom lightbox support for ambiguous or detail-heavy review cases.
- Added reviewed contract preset selection plus constrained prompt-assisted
  preset selection to `examples/mujoco_grasp.py`, while keeping unsupported
  open-ended authoring fail-closed.
- Rewrote the README front door around the unattended approval wedge, with a
  clearer split between package-first integration and the repo-only MuJoCo demo.

## [0.2.2] - 2026-04-15

### Fixed

- Fixed generated MuJoCo grasp reports so embedded Meshcat scenes resolve from the
  report output root instead of shipping dead iframes.
- Contained wide report tables and the Meshcat viewer on small screens so the report
  no longer forces horizontal scrolling on mobile or split-screen layouts.
- Cleared pass-state artifact metadata so successful runs show `Root cause: none` and
  `Rerun hint: No rerun required` instead of failure-only hints.

### Added

- Added regression tests covering Meshcat embed paths, responsive report containment,
  and pass-state metadata consistency.
- Added a repo-local mirror of the MuJoCo grasp report design audit under
  `docs/designs/`.
