"""Regression fixtures for behavior supplied by the pinned timetable parser."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from librus_apix.timetable import get_timetable


def test_split_group_timetable_cell_preserves_every_group():
    fixture = Path(__file__).with_name("fixtures") / "timetable_split_groups.html"
    client = SimpleNamespace(TIMETABLE_URL="https://synergia.librus.pl/timetable")
    client.post = MagicMock(return_value=SimpleNamespace(text=fixture.read_text()))

    timetable = get_timetable(client, datetime(2026, 9, 21))

    monday_lesson = timetable[0][0]
    assert monday_lesson.subject == "English / German"
    assert monday_lesson.teacher_and_classroom == "Teacher One, 101 / Teacher Two, 202"
    client.post.assert_called_once_with(
        client.TIMETABLE_URL,
        data={"tydzien": "2026-09-21_2026-09-27"},
    )
