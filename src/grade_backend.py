"""Consumer-owned final-grade selection contract, with no optional imports."""

from typing import Protocol

from src.scraping import FinalGrade


class FinalGradesBackend(Protocol):
    async def final_grades(self, alias: str) -> list[FinalGrade]: ...
