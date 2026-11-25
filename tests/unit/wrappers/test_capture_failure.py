"""Checkpoint capture must not fail open.

A capture that produces zero images used to report success: the wrapper wrote
``state.json``, logged at debug level, and the quickstart printed "Captures
saved". For a harness whose whole job is visual evidence, silent success with
no pixels is the worst possible failure mode.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
import pytest

from roboharness.wrappers.gymnasium_wrapper import (
    MultiCameraCapability,
    RobotHarnessWrapper,
    _capture_frame_with_reason,
)

_FAIL_MSG = "pygame is not installed, run `pip install gymnasium[classic-control]`"


class _RenderableEnv(gym.Env):  # type: ignore[type-arg]
    """Minimal env whose ``render`` can be pointed at a value or an exception."""

    def __init__(self, render_value: Any) -> None:
        self._render_value = render_value
        self.observation_space = gym.spaces.Box(low=-1.0, high=1.0, shape=(2,))
        self.action_space = gym.spaces.Discrete(2)

    def reset(self, *, seed: int | None = None, options: dict[str, Any] | None = None):
        return np.zeros(2, dtype=np.float32), {}

    def step(self, action: Any):
        return np.zeros(2, dtype=np.float32), 0.0, False, False, {}

    def render(self) -> Any:
        if isinstance(self._render_value, Exception):
            raise self._render_value
        return self._render_value


def _make_wrapper(env: gym.Env, tmp_path: Path, **kwargs: Any) -> RobotHarnessWrapper:  # type: ignore[type-arg]
    return RobotHarnessWrapper(
        env,
        checkpoints=[{"name": "early", "step": 1}],
        output_dir=tmp_path,
        task_name="probe",
        **kwargs,
    )


def _capture(wrapper: RobotHarnessWrapper, name: str = "early") -> Path:
    wrapper._capture_checkpoint(name, np.zeros(2, dtype=np.float32), 1.0, {})
    return wrapper.output_dir / "probe" / "trial_000" / name / "metadata.json"


class TestCaptureFrameReason:
    def test_reports_exception_type_and_message(self) -> None:
        env = _RenderableEnv(RuntimeError(_FAIL_MSG))
        frame, reason = _capture_frame_with_reason(env, "default", MultiCameraCapability.NONE)
        assert frame is None
        assert reason is not None
        assert "RuntimeError" in reason
        assert "pygame" in reason

    def test_reports_when_render_returns_none(self) -> None:
        env = _RenderableEnv(None)
        frame, reason = _capture_frame_with_reason(env, "default", MultiCameraCapability.NONE)
        assert frame is None
        assert reason is not None
        assert "returned no frame" in reason

    def test_returns_frame_on_success(self) -> None:
        env = _RenderableEnv(np.zeros((8, 8, 3), dtype=np.uint8))
        frame, reason = _capture_frame_with_reason(env, "default", MultiCameraCapability.NONE)
        assert frame is not None
        assert reason is None


class TestCaptureFailOpenFixed:
    def test_metadata_marks_capture_failed(self, tmp_path: Path) -> None:
        wrapper = _make_wrapper(_RenderableEnv(RuntimeError(_FAIL_MSG)), tmp_path)
        metadata_path = _capture(wrapper)
        metadata = json.loads(metadata_path.read_text())

        assert metadata["capture_failed"] is True
        assert metadata["cameras"] == []
        assert metadata["capture_errors"]
        assert "pygame" in metadata["capture_errors"][0]

    def test_warns_instead_of_failing_silently(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        wrapper = _make_wrapper(_RenderableEnv(RuntimeError(_FAIL_MSG)), tmp_path)
        with caplog.at_level("WARNING", logger="roboharness.wrappers.gymnasium_wrapper"):
            _capture(wrapper)
        assert any("captured 0 images" in record.message for record in caplog.records)

    def test_strict_capture_raises(self, tmp_path: Path) -> None:
        wrapper = _make_wrapper(
            _RenderableEnv(RuntimeError(_FAIL_MSG)), tmp_path, strict_capture=True
        )
        with pytest.raises(RuntimeError, match="captured 0 images"):
            _capture(wrapper)

    def test_successful_capture_is_not_marked_failed(self, tmp_path: Path) -> None:
        wrapper = _make_wrapper(_RenderableEnv(np.zeros((8, 8, 3), dtype=np.uint8)), tmp_path)
        metadata_path = _capture(wrapper)
        metadata = json.loads(metadata_path.read_text())

        assert metadata["capture_failed"] is False
        assert metadata["cameras"] == ["default"]
        assert "capture_errors" not in metadata
        assert (metadata_path.parent / "default_rgb.png").is_file()
