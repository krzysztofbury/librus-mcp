"""Check structured results against published output schemas as strict hosts do."""

import re

from jsonschema import FormatChecker
from jsonschema.validators import validator_for
from mcp.client import ClientSession
from mcp.types import CallToolResult

# jsonschema skips "date-time" unless the optional rfc3339-validator is installed,
# while hosts using ajv-formats enforce RFC 3339, which requires a UTC offset.
RFC3339_DATE_TIME = re.compile(
    r"\d{4}-[01]\d-[0-3]\d[t\s](?:[0-2]\d:[0-5]\d:[0-6]\d|23:59:60)(?:\.\d+)?"
    r"(?:z|[+-]\d\d(?::?\d\d)?)",
    re.IGNORECASE,
)
STRICT_FORMATS = FormatChecker()


@STRICT_FORMATS.checks("date-time")
def rfc3339_date_time(value: object) -> bool:
    return not isinstance(value, str) or RFC3339_DATE_TIME.fullmatch(value) is not None


async def assert_matches_published_schema(
    session: ClientSession, name: str, result: CallToolResult
) -> None:
    assert not result.is_error
    tools = (await session.list_tools()).tools
    schema = next(tool.output_schema for tool in tools if tool.name == name)
    assert schema is not None
    validator = validator_for(schema)(schema, format_checker=STRICT_FORMATS)
    validator.validate(result.structured_content)
