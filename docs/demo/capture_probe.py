#!/usr/bin/env python3
"""Show the zero-image checkpoint behaviour before/after the fix.

Two ways an agent silently produces no visual evidence:
  1. the env has no renderer available (here: render_mode not set), and
  2. the wrapper is asked to be strict about it.

The point of the fix is that (1) is *recorded and warned about* rather than
reported as success, and (2) exists at all.
"""

from __future__ import annotations

import json
import logging
import warnings
from pathlib import Path

import gymnasium as gym
import numpy as np

from roboharness.wrappers import RobotHarnessWrapper

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
# Gymnasium warns about render_mode on every render() call; the probe is *about*
# a missing render mode, so the warning is noise that would drown the finding.
warnings.filterwarnings("ignore", category=UserWarning, module="gymnasium")

OUT = Path("/tmp/roboharness_capture_probe")


def main() -> int:
    env = gym.make("CartPole-v1")  # no render_mode -> env.render() returns None
    wrapper = RobotHarnessWrapper(
        env,
        checkpoints=[{"name": "early", "step": 1}],
        output_dir=OUT,
        task_name="cartpole",
    )
    wrapper.reset()
    wrapper._capture_checkpoint("early", np.zeros(4, dtype=np.float32), 0.0, {})

    metadata_path = next(OUT.rglob("metadata.json"))
    metadata = json.loads(metadata_path.read_text())
    print("metadata.capture_failed =", metadata["capture_failed"])
    print("metadata.cameras       =", metadata["cameras"])
    print("metadata.capture_errors=", metadata["capture_errors"])
    print("png written            =", bool(list(metadata_path.parent.glob("*.png"))))
    print("wrapper logged         = WARNING (see stderr); state-only evidence is loud, not silent")

    strict = RobotHarnessWrapper(
        gym.make("CartPole-v1"),
        checkpoints=[{"name": "early", "step": 1}],
        output_dir=OUT / "strict",
        task_name="cartpole",
        strict_capture=True,
    )
    strict.reset()
    try:
        strict._capture_checkpoint("early", np.zeros(4, dtype=np.float32), 0.0, {})
    except RuntimeError as exc:
        head = str(exc).split(" (")[0]
        print("strict_capture=True    -> RuntimeError:")
        print(f"  {head}  ->  install a renderer or pass strict_capture=True")
    else:  # pragma: no cover - the demo asserts the guard exists
        raise SystemExit("strict_capture did not raise")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
