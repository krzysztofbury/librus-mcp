"""Call read tools through a real MCP client session and check what hosts see.

Hosts validate each result against the tool's published output schema and
reject it with `Invalid structured content returned by tool ...`, a message
that quotes school data. This check performs the same validation and reports
only the result path, the schema rule and the value's type.
"""

import json
from collections.abc import Callable, Sequence

from jsonschema.exceptions import ValidationError  # type: ignore[import-untyped]
from mcp import Client

from librus_mcp import __version__
from librus_mcp.server import VERSIONS, NativeServer

DEFAULT_TOOLS = (
    "get_student_information",
    "get_final_grades",
    "get_grades",
    "get_grades_window",
    "get_attendance",
)


def _rule(error: ValidationError) -> str:
    path = "/".join(str(part) for part in error.absolute_path) or "(result)"
    rule = json.dumps(error.validator_value, ensure_ascii=False, default=str)
    if len(rule) > 160:
        rule = rule[:160] + "..."
    return f"at {path}: {error.validator} {rule}, value type {type(error.instance).__name__}"


def _mismatch(error: ValidationError) -> str:
    """The failed rule; for a union, the closest failure in each branch."""
    if error.validator not in ("anyOf", "oneOf") or not error.context:
        return _rule(error)
    branches: dict[object, ValidationError] = {}
    for failure in error.context:
        branch = failure.schema_path[0] if failure.schema_path else None
        current = branches.get(branch)
        if current is None or len(failure.absolute_path) > len(current.absolute_path):
            branches[branch] = failure
    return " | ".join(_mismatch(failure) for failure in list(branches.values())[:3])


async def check_tools(
    server: NativeServer,
    aliases: Sequence[str],
    tools: Sequence[str],
    write: Callable[[str], None],
) -> bool:
    """Call each tool for each login; True when every result is valid.

    Calls are real reads: they change the views Librus remembers exactly as
    the tools do. Logins are named by position, never by alias.
    """
    write(
        f"librus-mcp {__version__} (api {VERSIONS['api']}): results are checked "
        "against the published schemas; no school data is printed"
    )
    valid = True
    async with Client(server) as client:
        listed = {tool.name for tool in (await client.list_tools()).tools}
        for position, alias in enumerate(aliases, start=1):
            for tool in tools:
                label = f"login {position} {tool}"
                if tool not in listed:
                    write(f"{label}: not in the catalog")
                    valid = False
                    continue
                try:
                    result = await client.call_tool(tool, {"account_alias": alias})
                except RuntimeError as error:
                    valid = False
                    cause = error.__cause__
                    if isinstance(cause, ValidationError):
                        write(f"{label}: SCHEMA MISMATCH {_mismatch(cause)}")
                    else:
                        write(f"{label}: client error {type(error).__name__}")
                    continue
                except Exception as error:  # noqa: BLE001 - reported by type; messages may hold data
                    valid = False
                    write(f"{label}: client error {type(error).__name__}")
                    continue
                content = result.structured_content or {}
                if result.is_error:
                    valid = False
                    detail = content.get("error", {})
                    where = " < ".join(reversed(detail.get("where", [])))
                    write(
                        f"{label}: tool error {detail.get('code')}"
                        + (f" at {where}" if where else "")
                    )
                    continue
                items = content.get("items") if isinstance(content, dict) else None
                count = f", {len(items)} items" if isinstance(items, list) else ""
                write(f"{label}: OK{count}")
    return valid
