"""Call read tools through a real MCP client session and check what hosts see.

Hosts validate each result against the tool's published output schema and
reject it with `Invalid structured content returned by tool ...`, a message
that quotes school data. This check performs the same validation and reports
only the result path, the schema rule and the value's type.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from jsonschema.exceptions import ValidationError  # type: ignore[import-untyped]
from librus_python_api import MessagingBackend
from mcp import Client

from librus_mcp import __version__
from librus_mcp.server import VERSIONS, NativeServer

Arguments = Callable[[date], dict[str, Any]]


def _none(_: date) -> dict[str, Any]:
    return {}


def _week(today: date) -> dict[str, Any]:
    # Any day selects its week; the tool uses the Monday.
    return {"monday": today.isoformat()}


def _month(today: date) -> dict[str, Any]:
    return {"year": today.year, "month": today.month}


def _lessons(today: date) -> dict[str, Any]:
    return {
        "date_from": (today - timedelta(days=6)).isoformat(),
        "date_to": today.isoformat(),
        "max_pages": 1,
    }


def _one_page(_: date) -> dict[str, Any]:
    return {"max_pages": 1}


# Every tool callable with the login alone, plus arguments derived from today,
# whose calls neither consume, mark read, write files nor send. Selecting a
# view, week or month changes what Librus remembers, as the tools do.
CHECKS: Mapping[str, Arguments] = {
    "get_student_information": _none,
    "get_final_grades": _none,
    "get_grades": _none,
    "get_grades_window": _none,
    "get_attendance": _none,
    "get_attendance_window": _none,
    "get_attendance_frequency": _none,
    "get_subject_frequency": _none,
    "get_timetable": _week,
    "get_announcements": _none,
    "get_agenda": _month,
    "get_homework": _none,
    "get_completed_lessons": _lessons,
    "get_school_year_archive": _none,
    "get_class_free_days": _none,
    "get_justifications": _none,
    "get_messages": _one_page,
    "get_recipient_types": _none,
    "get_message_correspondents": _none,
    "get_teacher_subjects": _none,
    "get_message_unread_counts": _none,
    "get_notification_status": _none,
    "get_send_history": _none,
}
DEFAULT_TOOLS = tuple(CHECKS)
# Called once, without a login.
CATALOG_TOOLS = ("list_accounts",)
MODERN_ONLY = frozenset(
    {"get_message_correspondents", "get_teacher_subjects", "get_message_unread_counts"}
)
# Tools the check never calls, and why.
REFUSED: Mapping[str, str] = {
    "get_attendance_detail": "needs attendance_id from get_attendance",
    "get_agenda_detail": "needs event_ref from get_agenda",
    "get_homework_detail": "needs homework_ref from get_homework",
    "get_message_content": "needs message_ref and may mark a message read",
    "get_recipient_choices": "needs recipient_type from get_recipient_types",
    "get_recipients": "needs recipient_type from get_recipient_types",
    "download_attachment": "needs attachment_ref and writes a file",
    "get_new_notifications": "stages a notification batch and may consume calendar events",
    "acknowledge_notifications": "acknowledges a notification batch",
    "preview_message": "needs a message and records a preview",
    "send_message": "sends a message",
    "get_send_outcome": "needs confirmation_token from preview_message",
}
# The login cannot use the tool; that is not a schema failure.
UNAVAILABLE = frozenset({"VIEW_DISABLED", "MODULE_UNAVAILABLE"})
# Parent-only modules: a student login gets UNSUPPORTED_CAPABILITY before any request.
PARENT_ONLY = frozenset({"get_justifications"})


def warsaw_today() -> date:
    return datetime.now(ZoneInfo("Europe/Warsaw")).date()


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
    accounts: Sequence[tuple[str, MessagingBackend]],
    tools: Sequence[str] | None,
    write: Callable[[str], None],
    *,
    today: Callable[[], date] = warsaw_today,
) -> bool:
    """Call each tool for each login; True when every result is valid.

    `tools` None means every checkable tool in the catalog. Calls are real
    reads: they change the views Librus remembers exactly as the tools do. A
    requested tool that the check cannot call is refused before any call.
    Logins are named by position, never by alias.
    """
    write(
        f"librus-mcp {__version__} (api {VERSIONS['api']}): results are checked "
        "against the published schemas; no school data is printed"
    )
    valid = True
    async with Client(server) as client:
        listed = {tool.name for tool in (await client.list_tools()).tools}
        if tools is None:
            selected = [tool for tool in (*CATALOG_TOOLS, *DEFAULT_TOOLS) if tool in listed]
        else:
            selected = list(dict.fromkeys(tools))
            for tool in selected:
                if tool not in listed:
                    write(f"{tool}: not in the catalog")
                    valid = False
                elif tool in REFUSED:
                    write(f"{tool}: not checked, {REFUSED[tool]}")
                    valid = False
                elif tool not in CHECKS and tool not in CATALOG_TOOLS:
                    write(f"{tool}: not checked, no known safe arguments")
                    valid = False
            if not valid:
                return False
        day = today()
        for tool in selected:
            if tool in CATALOG_TOOLS:
                valid &= await _check(client, f"catalog {tool}", tool, {}, write)
        for position, (alias, backend) in enumerate(accounts, start=1):
            for tool in selected:
                if tool in CATALOG_TOOLS:
                    continue
                label = f"login {position} {tool}"
                if tool in MODERN_ONLY and backend is not MessagingBackend.MODERN:
                    write(f"{label}: not applicable, modern messaging only")
                    continue
                arguments = {"account_alias": alias} | CHECKS[tool](day)
                valid &= await _check(client, label, tool, arguments, write)
    return valid


async def _check(
    client: Client,
    label: str,
    tool: str,
    arguments: dict[str, Any],
    write: Callable[[str], None],
) -> bool:
    try:
        result = await client.call_tool(tool, arguments)
    except RuntimeError as error:
        cause = error.__cause__
        if isinstance(cause, ValidationError):
            write(f"{label}: SCHEMA MISMATCH {_mismatch(cause)}")
        else:
            write(f"{label}: client error {type(error).__name__}")
        return False
    except Exception as error:  # noqa: BLE001 - reported by type; messages may hold data
        write(f"{label}: client error {type(error).__name__}")
        return False
    content = result.structured_content or {}
    if result.is_error:
        detail = content.get("error", {})
        code = detail.get("code")
        if code in UNAVAILABLE or (code == "UNSUPPORTED_CAPABILITY" and tool in PARENT_ONLY):
            write(f"{label}: unavailable on this login ({code})")
            return True
        where = " < ".join(reversed(detail.get("where", [])))
        write(f"{label}: tool error {code}" + (f" at {where}" if where else ""))
        return False
    items = content.get("items") if isinstance(content, dict) else None
    count = f", {len(items)} items" if isinstance(items, list) else ""
    write(f"{label}: OK{count}")
    return True
