import dataclasses

import pytest

from src.identity_backend import StudentProfile
from src.librus_client import LibrusManager


@pytest.mark.asyncio
async def test_identity_backend_selection_preserves_legacy_serialization(monkeypatch):
    profile = StudentProfile("Fixture Student", "1 TEST", 12, "Fixture Tutor", "Fixture School", 7)

    class Backend:
        async def student_information(self, alias: str) -> StudentProfile:
            assert alias == "fixture"
            return profile

    monkeypatch.setattr(LibrusManager, "_require_account", lambda alias: None)
    previous = LibrusManager._identity_backend
    try:
        LibrusManager.set_identity_backend(Backend())
        result = await LibrusManager.fetch_student_information("fixture")
        assert dataclasses.asdict(result) == {
            "name": "Fixture Student",
            "class_name": "1 TEST",
            "number": 12,
            "tutor": "Fixture Tutor",
            "school": "Fixture School",
            "lucky_number": 7,
        }
    finally:
        LibrusManager.set_identity_backend(previous)
