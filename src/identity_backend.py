"""Consumer-owned identity adapter contract, independent of optional packages."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StudentProfile:
    name: str
    class_name: str
    number: int
    tutor: str
    school: str
    lucky_number: int | str


class IdentityBackend(Protocol):
    async def student_information(self, alias: str) -> StudentProfile: ...
