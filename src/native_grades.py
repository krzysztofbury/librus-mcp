"""Opt-in local final-grade adapter; never a fallback or production default."""

from librus_python_api import Availability, GradeSummaryValue, LibrusService
from librus_python_api.exceptions import ErrorKind, LibrusError
from mcp.server.mcpserver.exceptions import ToolError

from src.scraping import FinalGrade


def _legacy_value(value: GradeSummaryValue) -> str:
    # The existing consumer maps an absent optional summary column to '-'.
    # Available empty/unassigned values remain exactly as supplied by the school.
    if value.availability == Availability.UNAVAILABLE:
        return "-"
    assert value.raw is not None
    return value.raw


class NativeFinalGradesBackend:
    def __init__(self, service: LibrusService) -> None:
        self._service = service

    async def final_grades(self, alias: str) -> list[FinalGrade]:
        failure: ErrorKind | None = None
        try:
            collection = await self._service.account(alias).final_grades()
            return [
                FinalGrade(
                    item.subject,
                    _legacy_value(item.midterm),
                    _legacy_value(item.predicted_annual),
                    _legacy_value(item.annual),
                )
                for item in collection.items
            ]
        except LibrusError as error:
            failure = error.kind
        assert failure is not None
        raise ToolError(f"Librus grade summary failed: {failure.value}")
