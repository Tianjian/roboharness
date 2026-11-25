#!/usr/bin/env python3
"""Render the grasp loop to an image sequence so the demo can show motion.

Replays exactly the same scripted actions the harness runs (`fixture` +
`build_grasp_phases`), stepping MuJoCo directly and capturing every N steps with
a free 3/4 camera. `--defect open_gripper` keeps the fingers open through grasp
and lift, matching docs/demo/fault_demo.py.

Usage:
    MUJOCO_GL=egl python docs/demo/render_anim.py --out docs/demo/anim/pass --every 20
    MUJOCO_GL=egl python docs/demo/render_anim.py \
        --out docs/demo/anim/fault --every 20 --defect open_gripper
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "examples" / "demos" / "mujoco"))

import fixture  # noqa: E402
import mujoco  # noqa: E402


def _cube_height(data: mujoco.MjData) -> float | None:
    """Z of the manipulated body, if the fixture names it ``cube``."""
    try:
        body_id = mujoco.mj_name2id(data.model, mujoco.mjtObj.mjOBJ_BODY, "cube")
    except Exception:  # pragma: no cover - defensive
        return None
    if body_id < 0:
        return None
    return float(data.xpos[body_id][2] * 1000.0)


def build_phases(defect: str) -> dict[str, list[np.ndarray]]:
    phases = fixture.build_grasp_phases()
    if defect == "open_gripper":
        left_open, right_open = 0.015, -0.015
        for phase in ("grasp", "lift"):
            for action in phases[phase]:
                action[1] = left_open
                action[2] = right_open
    return phases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--every", type=int, default=10, help="capture every N sim steps")
    parser.add_argument("--defect", choices=["none", "open_gripper"], default="none")
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=540)
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists():
        for stale in out.glob("frame_*.png"):
            stale.unlink()
    out.mkdir(parents=True, exist_ok=True)

    # MuJoCo's offscreen framebuffer defaults to 640x480; the fixture does not
    # raise it, so inject the size before compiling.
    import re

    xml = re.sub(
        r"<mujoco\b[^>]*>",
        lambda m: (
            m.group(0)
            + f'<visual><global offwidth="{args.width}" offheight="{args.height}"/></visual>'
        ),
        fixture.GRASP_MJCF,
        count=1,
    )
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)

    renderer = mujoco.Renderer(model, height=args.height, width=args.width)
    camera = mujoco.MjvCamera()
    camera.type = mujoco.mjtCamera.mjCAMERA_FREE
    # Framing chosen by inspection: keeps the fully-raised gripper in frame at
    # the start while still filling ~1/3 of the frame with the gripper + cube.
    camera.lookat[:] = (0.0, 0.0, 0.34)
    camera.distance = 0.85
    camera.azimuth = 138.0
    camera.elevation = -16.0

    phases = build_phases(args.defect)
    order = ["plan", "pre_grasp", "approach", "grasp", "lift"]

    phase_ranges: list[dict[str, object]] = []
    step = 0
    frame = 0
    for name in order:
        actions = phases[name]
        start = step
        for action in actions:
            np.copyto(data.ctrl, np.asarray(action, dtype=np.float64))
            mujoco.mj_step(model, data)
            step += 1
            if step % args.every == 0:
                renderer.update_scene(data, camera=camera)
                pixels = renderer.render()
                from PIL import Image

                Image.fromarray(pixels).save(out / f"frame_{frame:04d}.png")
                frame += 1
        phase_ranges.append({"phase": name, "start": start, "end": step})

    # Final frame so the last instant is always visible.
    renderer.update_scene(data, camera=camera)
    from PIL import Image

    Image.fromarray(renderer.render()).save(out / f"frame_{frame:04d}.png")
    frames = frame + 1

    meta = {
        "defect": args.defect,
        "steps": step,
        "frames": frames,
        "every": args.every,
        "size": [args.width, args.height],
        "phase_ranges": phase_ranges,
        "final_cube_height_mm": _cube_height(data),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"{args.defect}: {frames} frames, {step} steps -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
