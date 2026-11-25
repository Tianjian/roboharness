#!/usr/bin/env python3
"""Fault-injection twin of examples/demos/mujoco/grasp.py.

Purpose: the shipped deterministic grasp demo reproduces the *blessed baseline
exactly*, so it only exercises the PASS branch of the trust loop (0 alarms,
0 surfaced cases). This script reuses the repo's own fixture + wedge helpers
(read-only import, repo is untouched) but keeps the gripper fingers OPEN during
the ``grasp`` and ``lift`` phases. The cube is never pinched, so the same
contract/metrics/alarm/approval pipeline must produce a FAIL with critical
alarms at the ``grasp``/``lift`` checkpoints.

Demo asset: fault-injected twin used by docs/demo/capture.py.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "examples" / "demos" / "mujoco"))

import fixture  # noqa: E402
import grasp as grasp_demo  # noqa: E402  (demo module, pulls fixture+wedge)

if TYPE_CHECKING:
    import numpy as np
import wedge  # noqa: E402

from roboharness._utils import save_json  # noqa: E402
from roboharness.backends.mujoco_meshcat import MuJoCoMeshcatBackend  # noqa: E402
from roboharness.backends.visualizer import MeshcatVisualizer  # noqa: E402
from roboharness.core.harness import Harness  # noqa: E402


def build_broken_phases() -> dict[str, list[np.ndarray]]:
    """Same motion as fixture.build_grasp_phases, but grasp/lift never close."""
    phases = fixture.build_grasp_phases()
    left_open, right_open = 0.015, -0.015
    for phase in ("grasp", "lift"):
        for action in phases[phase]:
            action[1] = left_open
            action[2] = right_open
    return phases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="./run_fault")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    baseline_report_path = wedge.BASELINE_REPORT_PATH

    contract = wedge.compile_contract(
        baseline_source=str(baseline_report_path),
        contract_path=None,
        contract_preset=wedge.DEFAULT_CONTRACT_PRESET,
        contract_prompt=None,
    )

    backend = MuJoCoMeshcatBackend(
        xml_string=fixture.GRASP_MJCF,
        cameras=fixture.MUJOCO_GRASP_CAMERAS,
        render_width=args.width,
        render_height=args.height,
    )
    meshcat_viz = MeshcatVisualizer(
        backend._model, backend._data, width=args.width, height=args.height
    )

    harness = Harness(backend, output_dir=str(output_dir), task_name=fixture.MUJOCO_GRASP_TASK)
    harness.load_protocol(fixture.build_grasp_protocol())
    harness.reset()

    phases = build_broken_phases()
    checkpoint_results: dict[str, object] = {}
    for phase_name, actions in phases.items():
        result = harness.run_to_next_checkpoint(actions)
        if result is None:
            raise RuntimeError(f"missing checkpoint {phase_name}")
        checkpoint_results[phase_name] = result
        meshcat_viz.sync()
        meshcat_viz.export_html(
            output_dir / fixture.MUJOCO_GRASP_TASK / "trial_001" / phase_name / "meshcat_scene.html"
        )
        print(
            f"checkpoint {phase_name}: {len(result.views)} views | step={result.step}"
            f" | sim_time={result.sim_time:.3f}s"
        )

    trial_dir = output_dir / fixture.MUJOCO_GRASP_TASK / "trial_001"
    baseline_report = wedge.load_blessed_baseline(baseline_report_path)
    snapshot_metrics = wedge.collect_phase_metrics(harness, backend, checkpoint_results)
    report_path = trial_dir / "autonomous_report.json"
    proof_pack = wedge.build_proof_pack(
        contract=contract,
        snapshot_metrics=snapshot_metrics,
        baseline_report=baseline_report,
        baseline_source=str(baseline_report_path),
        report_path=str(report_path),
        trial_dir=trial_dir,
        baseline_visual_root=baseline_report_path.resolve().parent / "baseline_visual",
    )

    html_path = grasp_demo.generate_html_report(
        output_dir,
        summary_html=wedge.build_summary_html(
            proof_pack.report,
            proof_pack.alarms,
            proof_pack.manifest,
            proof_pack.evidence_pairs,
            contract=proof_pack.contract,
            approval_report=proof_pack.approval_report,
        ),
        evaluation_result=proof_pack.evaluation_result,
    )
    shutil.copyfile(html_path, output_dir / wedge.CANONICAL_REPORT_NAME)

    visual_review_package = wedge.prepare_mujoco_visual_review_package(
        trial_dir=trial_dir,
        baseline_visual_root=baseline_report_path.resolve().parent / "baseline_visual",
        contract=proof_pack.contract,
        report=proof_pack.report,
        manifest=proof_pack.manifest,
    )
    wedge.write_artifact_pack(
        trial_dir=trial_dir,
        contract=proof_pack.contract,
        approval_report=proof_pack.approval_report,
        report=proof_pack.report,
        evaluation_result=proof_pack.evaluation_result,
        alarms=proof_pack.alarms,
        manifest=proof_pack.manifest,
        report_generated=True,
        visual_review_artifacts=visual_review_package.artifact_paths(trial_dir),
    )

    print("\n--- fault-injection result ---")
    print("verdict:", proof_pack.evaluation_result.verdict.value.upper())
    print("failed_phase_id:", proof_pack.manifest.failed_phase_id)
    print("failed_phase:", proof_pack.manifest.failed_phase)
    print("suspected_root_cause:", proof_pack.manifest.suspected_root_cause)
    print("primary_views:", proof_pack.manifest.primary_views)
    print("rerun_hint:", proof_pack.manifest.rerun_hint)
    print(
        "evidence_state:",
        proof_pack.approval_report["run_state"],
        "/",
        proof_pack.approval_report.get("approval_evidence_state", ""),
    )
    print("overall_verdict:", proof_pack.approval_report["overall_verdict"])
    print("run_state:", proof_pack.approval_report["run_state"])
    print("run_state_title:", proof_pack.approval_report["run_state_title"])
    print("cases_surfaced:", proof_pack.approval_report["summary"]["cases_surfaced"])
    print(
        "needs_baseline_blessing:",
        proof_pack.approval_report["user_action"]["needs_baseline_blessing"],
    )
    print("baseline_authority:", proof_pack.approval_report["baseline_authority"])
    for alarm in proof_pack.alarms:
        if alarm.status == "alarm":
            print(
                f"ALARM {alarm.code} severity={alarm.severity} "
                f"actual={alarm.actual_value} expected={alarm.expected}"
            )

    save_json(proof_pack.evaluation_result.to_dict(), output_dir / "fault_summary.json")
    return 0 if proof_pack.evaluation_result.verdict.value != "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
