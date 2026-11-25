#!/usr/bin/env python3
"""Run every command the demo video shows, and save the REAL outputs.

The video must not contain invented text: each panel is rendered from this
capture file, which is produced by actually executing the commands against the
fixed branch.

Usage:
    python docs/demo/capture.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEMO = Path(__file__).resolve().parent
PY = sys.executable
ART = REPO / ".demo_artifacts"
FAULT = REPO / ".demo_fault"

ENV = {
    **os.environ,
    "PYTHONPATH": str(REPO / "src"),
    "MUJOCO_GL": "egl",
    "MPLBACKEND": "Agg",
}


def rel(path: Path) -> str:
    """Path relative to the repo root, so capture.json is portable."""
    try:
        return str(Path(path).resolve().relative_to(REPO))
    except ValueError:
        return str(path)


steps: list[dict[str, object]] = []


def run(
    command: str, *, cwd: Path = REPO, timeout: int = 900, stdout_only: bool = False
) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        shell=True,
        cwd=str(cwd),
        env=ENV,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if stdout_only:
        return completed.returncode, (completed.stdout or "").rstrip()
    return completed.returncode, ((completed.stdout or "") + (completed.stderr or "")).rstrip()


def tail(text: str, lines: int = 6) -> str:
    return "\n".join(text.rstrip().splitlines()[-lines:])


def record(step_id: str, label: str, display: str, exit_code: int, output: str) -> None:
    steps.append(
        {
            "id": step_id,
            "label": label,
            "command": display,
            "exit": exit_code,
            "output": output,
        }
    )
    print(f"[{step_id}] exit={exit_code}")
    if output:
        print(textwrap.indent(tail(output, 8), "    "))


def run_cli(step_id: str, label: str, args: str, *, display: str, cwd: Path = REPO) -> None:
    code, out = run(f"{PY} -m roboharness.cli {args}", cwd=cwd)
    record(step_id, label, display, code, out)


def screenshot(html: Path, out: Path, size: str = "1440,1100") -> bool:
    if not html.exists():
        return False
    subprocess.run(
        [
            "firefox",
            "--headless",
            f"--window-size={size}",
            f"--screenshot={out}",
            f"file://{html}",
        ],
        capture_output=True,
        timeout=240,
    )
    return out.exists()


def main() -> int:
    DEMO.mkdir(exist_ok=True)
    for stale in (ART, FAULT):
        shutil.rmtree(stale, ignore_errors=True)

    # 1) The shipped deterministic grasp demo (PASS branch).
    code, out = run(f"{PY} examples/demos/mujoco/grasp.py --report --output-dir .demo_artifacts")
    record(
        "demo",
        "Deterministic MuJoCo grasp run",
        "python examples/demos/mujoco/grasp.py --report --output-dir .demo_artifacts",
        code,
        out,
    )
    screenshot(ART / "report.html", DEMO / "shot_pass.png")

    # 2) Gate on the PASS artefact.
    approval = ART / "mujoco_grasp" / "trial_001" / "approval_report.json"
    run_cli(
        "gate_pass",
        "Gate the PASS artefact",
        f"gate {approval.relative_to(REPO)}",
        display=f"roboharness gate {approval.relative_to(REPO)}",
    )

    # 3) Fault-injected twin: fingers never close -> FAIL branch.
    code, out = run(f"{PY} {DEMO / 'fault_demo.py'} --output-dir {FAULT}")
    record(
        "fault",
        "Fault-injected twin (gripper never closes)",
        f"python docs/demo/fault_demo.py --output-dir {FAULT.relative_to(REPO)}",
        code,
        out,
    )
    screenshot(FAULT / "report.html", DEMO / "shot_fail.png")

    fault_approval = FAULT / "mujoco_grasp" / "trial_001" / "approval_report.json"
    if not fault_approval.exists():
        fault_approval = FAULT / "approval_report.json"
    run_cli(
        "gate_fail",
        "Gate the FAIL artefact",
        f"gate {rel(fault_approval)}",
        display=f"roboharness gate {rel(fault_approval)}",
    )

    # 4) Provenance: bind the real evidence, then verify.
    case = ART / "mujoco_grasp" / "trial_001"
    bound = case / "bound_report.json"
    code, out = run(f"{PY} docs/demo/bind_provenance.py {rel(case)} {rel(bound)}", cwd=REPO)
    record(
        "bind",
        "Bind provenance to the real evidence",
        f"python docs/demo/bind_provenance.py {rel(case)}",
        code,
        out,
    )

    run_cli(
        "prov_ok",
        "Gate with provenance verification",
        f"gate {bound} --require-provenance",
        display=f"roboharness gate {bound.name} --require-provenance",
        cwd=REPO,
    )

    # 5) Tamper with one bound image, then re-verify.
    code, out = run(f"{PY} docs/demo/tamper.py {rel(case)}", cwd=REPO)
    record(
        "tamper",
        "Re-export one checkpoint image",
        f"python docs/demo/tamper.py {rel(case)}",
        code,
        out,
    )

    run_cli(
        "prov_bad",
        "Gate after the pixels changed",
        f"gate {bound} --require-provenance",
        display=f"roboharness gate {bound.name} --require-provenance",
        cwd=REPO,
    )

    # 6) Capture fail-open: before/after.
    # stdout only: the probe's own report is the story; the library WARNING goes
    # to stderr and is shown by the probe itself in one line.
    code, out = run(f"{PY} docs/demo/capture_probe.py", cwd=REPO, stdout_only=True)
    record(
        "capture",
        "Zero-image checkpoint behaviour",
        "python docs/demo/capture_probe.py",
        code,
        out,
    )

    # 7) Quality gates.
    code, out = run(f'{PY} -m pytest -q -m "not slow"')
    record("pytest", "Test suite (hermetic)", 'pytest -q -m "not slow"', code, tail(out, 3))

    code, out = run(f"{PY} -m ruff check . && {PY} -m ruff format --check .")
    record("ruff", "Lint + format gate", "ruff check . && ruff format --check .", code, out)

    code, out = run(f"{PY} -m mypy src")
    record("mypy", "Type check", "mypy src", code, out)

    # Checkpoint images for the evidence montage.
    trial = ART / "mujoco_grasp" / "trial_001"
    phases = ["plan", "pre_grasp", "approach", "grasp", "lift"]
    frames = {
        "phases": phases,
        "front": [rel(trial / p / "front_rgb.png") for p in phases],
        "top": [rel(trial / p / "top_rgb.png") for p in phases],
        "ok": [str((trial / p / "front_rgb.png").is_file()) for p in phases],
    }

    git_sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO), capture_output=True, text=True
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    ).stdout.strip()

    payload = {
        "git_sha": git_sha,
        "branch": branch,
        "steps": steps,
        "frames": frames,
        "shots": {
            "pass": rel(DEMO / "shot_pass.png") if (DEMO / "shot_pass.png").exists() else None,
            "fail": rel(DEMO / "shot_fail.png") if (DEMO / "shot_fail.png").exists() else None,
        },
    }
    (DEMO / "capture.json").write_text(json.dumps(payload, indent=2))
    print(f"\nwrote {DEMO / 'capture.json'} ({len(steps)} steps)")

    unexpected = [s["id"] for s in steps if s["exit"] not in (0, 1, 2, 3)]
    if unexpected:
        print("UNEXPECTED EXIT CODES:", unexpected)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
