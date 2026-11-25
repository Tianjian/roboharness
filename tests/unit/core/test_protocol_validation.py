"""Validation tests for TaskProtocol phase bookkeeping.

Duplicate phase names used to register two checkpoints against one snapshot
slot, so a rollback could restore the wrong state while the evidence pack
mislabelled it. These tests lock the fail-fast behaviour.
"""

from __future__ import annotations

import pytest

from roboharness.core.protocol import TaskPhase, TaskProtocol


class TestProtocolValidation:
    def test_accepts_unique_phases(self) -> None:
        protocol = TaskProtocol(
            name="assembly",
            phases=[TaskPhase("pick"), TaskPhase("place")],
        )
        assert protocol.phase_names() == ["pick", "place"]

    def test_rejects_duplicate_phase_names(self) -> None:
        with pytest.raises(ValueError, match="duplicate phase name"):
            TaskProtocol(
                name="assembly",
                phases=[TaskPhase("pick"), TaskPhase("pick")],
            )

    def test_duplicate_error_lists_the_offender_once(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            TaskProtocol(
                name="assembly",
                phases=[TaskPhase("pick"), TaskPhase("place"), TaskPhase("pick")],
            )
        message = str(excinfo.value)
        assert "pick" in message
        assert message.count("pick") == 1

    def test_rejects_empty_protocol_name(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            TaskProtocol(name="   ")

    def test_rejects_empty_phase_name(self) -> None:
        with pytest.raises(ValueError, match="empty name"):
            TaskProtocol(name="p", phases=[TaskPhase("")])

    def test_builtin_protocols_are_valid(self) -> None:
        from roboharness.core.protocol import BUILTIN_PROTOCOLS

        for name, protocol in BUILTIN_PROTOCOLS.items():
            assert protocol.name == name
            assert len(protocol.phase_names()) == len(set(protocol.phase_names()))

    def test_select_preserves_uniqueness(self) -> None:
        protocol = TaskProtocol(name="p", phases=[TaskPhase("a"), TaskPhase("b")])
        subset = protocol.select(["b", "a"])
        assert subset.phase_names() == ["b", "a"]
