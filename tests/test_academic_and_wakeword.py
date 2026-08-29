"""
Unit and integration tests for Hands-Free Wake-Word Engine and Academic Timetable / Assignment Manager.
"""

import pytest
import sqlite3
from unittest.mock import patch, MagicMock
from vision.perception.wake_word import WakeWordEngine
from vision.tools.academic_tools import (
    AcademicManager,
    get_college_timetable,
    add_college_assignment,
    list_college_assignments,
    mark_assignment_done,
    get_next_upcoming_class
)
from vision.cognitive.router import IntentRouter, DOMAIN_KEYWORD_MAP
from vision.tools.registry import tool_registry


def test_wake_word_engine_init():
    """Verify WakeWordEngine initializes and handles models gracefully."""
    try:
        import numpy  # noqa: F401
    except ImportError:
        pytest.skip("numpy not available on this OS.")
    engine = WakeWordEngine()
    assert engine.sample_rate == 16000
    assert engine.chunk_size == 1280
    # Test chime generation doesn't crash
    with patch("sounddevice.play"):
        engine.play_activation_chime()


def test_academic_manager_seeding(tmp_path):
    """Test AcademicManager SQLite timetable seeding and querying."""
    db_file = str(tmp_path / "test_academic.db")
    mgr = AcademicManager(db_path=db_file)

    # Verify Monday timetable (DMDW, FSD I Lab, THUB)
    mon_classes = mgr.get_schedule_for_day("Monday")
    assert len(mon_classes) >= 5
    subjects = [c["subject"] for c in mon_classes]
    assert any("DMDW" in s for s in subjects)
    assert any("FSD" in s for s in subjects)

    # Verify Mid-1 exams
    exams = mgr.get_mid_exams()
    assert len(exams) == 5
    exam_subjects = [e["subject"] for e in exams]
    assert "Computer Networks" in exam_subjects
    assert "Advanced Java" in exam_subjects


def test_academic_assignment_workflow(tmp_path):
    """Test adding, listing, and completing assignments."""
    db_file = str(tmp_path / "test_academic.db")
    mgr = AcademicManager(db_path=db_file)

    with patch("vision.core.reminder_daemon.reminder_manager.add_reminder"):
        res = mgr.add_assignment(
            subject="Web Technologies",
            title="React Portfolio",
            due_str="in 2 hours",
            description="Build responsive portfolio"
        )
        assert res["id"] is not None
        assert res["subject"] == "Web Technologies"

        # List assignments
        pending = mgr.list_assignments(status="pending")
        assert len(pending) == 1
        assert pending[0]["title"] == "React Portfolio"

        # Mark completed
        done = mgr.mark_completed("React Portfolio")
        assert done is True
        assert len(mgr.list_assignments(status="pending")) == 0


def test_academic_tool_registry():
    """Verify academic tools are registered in tool_registry."""
    tools = [
        "get_college_timetable",
        "add_college_assignment",
        "list_college_assignments",
        "mark_assignment_done",
        "get_next_upcoming_class"
    ]
    for t in tools:
        assert tool_registry._schemas.get(t) is not None, f"Tool {t} not in registry"


def test_academic_intent_routing():
    """Verify router correctly routes academic questions to academic tools."""
    router = IntentRouter()
    all_tools = list(tool_registry._schemas.values())

    routed = router.route_tools("What classes do I have today in IT Section A?", all_tools)
    tool_names = [t.get("function", {}).get("name", t.get("name")) for t in routed]
    assert "get_college_timetable" in tool_names or "get_next_upcoming_class" in tool_names

    routed_assign = router.route_tools("Add an assignment for Web Technologies due tomorrow at 5 PM", all_tools)
    assign_tool_names = [t.get("function", {}).get("name", t.get("name")) for t in routed_assign]
    assert "add_college_assignment" in assign_tool_names
