"""Opt-in local experiment with the separately installed native library.

The production dependency and default backend remain unchanged. The caller owns
the service lifecycle and must share one service across all native identity tools.
No cookie transfer, shadow reads, or legacy fallback on failure is performed.
"""

from librus_python_api import Availability, LibrusService
from librus_python_api.exceptions import ErrorKind, LibrusError, UnsupportedCapabilityError
from mcp.server.mcpserver.exceptions import ToolError

from src.identity_backend import StudentProfile


class NativeIdentityBackend:
    def __init__(self, service: LibrusService) -> None:
        self._service = service

    async def student_information(self, alias: str) -> StudentProfile:
        failure: ErrorKind | None = None
        try:
            information = await self._service.account(alias).student_information()
            lucky = information.lucky_number
            if lucky.availability != Availability.AVAILABLE or lucky.number is None:
                # The legacy schema requires a value, but there is no evidenced
                # legacy unavailable marker to invent for this backend.
                raise UnsupportedCapabilityError(ErrorKind.UNSUPPORTED_CAPABILITY)
            return StudentProfile(
                information.name,
                information.class_name,
                information.register_number,
                information.tutor,
                information.school,
                lucky.number,
            )
        except LibrusError as error:
            failure = error.kind
        # Outside the handler: upstream data cannot leak through exception chains.
        assert failure is not None
        raise ToolError(f"Librus identity failed: {failure.value}")
