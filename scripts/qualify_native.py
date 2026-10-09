"""Explicit, bounded ordinary-read qualification over real native MCP stdio.

Never emits credentials, aliases, IDs, returned text or wire payloads. Never
opens durable state, sends, consumes read-once events or opens received bodies.
Older credential files need no modification: absent context keys are generated
only for this disposable, nonpersistent qualification service, not deployment.
"""

import argparse
import asyncio
import json
import logging
import os
import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import anyio
from librus_python_api import RequestBudget
from mcp.client import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.mcpserver import Context
from mcp.types import ToolAnnotations

from librus_mcp import __version__
from librus_mcp.config import AppConfig, read_config_file
from librus_mcp.runtime import Runtime
from librus_mcp.server import create_server

MAX_REQUESTS = 160
MAX_SECONDS = 360.0
MAX_BYTES = 16 * 1024 * 1024
STOP_CODES = frozenset(
    {
        "CREDENTIALS_REJECTED",
        "ACCOUNT_ACTION_REQUIRED",
        "ACCESS_DENIED",
        "SESSION_EXPIRED",
        "THROTTLED",
        "MAINTENANCE",
        "CONNECTION",
        "TIMEOUT",
        "LIMIT",
        "CLOSED",
        "INTERNAL_ERROR",
    }
)


def qualification_config(path: Path) -> AppConfig:
    data = read_config_file(path)
    # Scope selection is explicit to this read-only qualification process. It
    # neither edits the original file nor starts a fresh durable notification store.
    return AppConfig.model_validate(
        {
            "accounts": data.get("accounts"),
            "context_key": data.get("context_key") or secrets.token_hex(32),
            "features": {"notifications": False, "attachments": False, "send_message": False},
        }
    )


def serve(config: AppConfig) -> None:
    logging.disable(logging.CRITICAL)
    budget = RequestBudget(
        max_requests=MAX_REQUESTS,
        timeout_seconds=MAX_SECONDS,
        max_response_bytes=MAX_BYTES,
    )
    server = create_server(config, budget=budget)

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
    async def qualification_identity(
        account_alias: str, ctx: Context[Runtime, Any]
    ) -> dict[str, bool]:
        await ctx.request_context.lifespan_context.account(account_alias).identity(budget=budget)
        return {"identity_verified": True}

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
    async def qualification_budget() -> dict[str, int]:
        return {"requests": budget.requests_dispatched, "response_bytes": budget.response_bytes}

    server.run(transport="stdio")


def cases(phase: str = "academic") -> list[tuple[str, dict[str, Any]]]:
    if phase == "v21":
        today = datetime.now(ZoneInfo("Europe/Warsaw")).date()
        return [
            ("get_grades", {"limit": 50}),
            (
                "get_grades_window",
                {
                    "date_from": (today - timedelta(days=30)).isoformat(),
                    "date_to": today.isoformat(),
                    "limit": 50,
                },
            ),
            ("get_school_year_archive", {"limit": 5}),
            ("get_class_free_days", {"limit": 5}),
            ("get_teacher_subjects", {"limit": 5}),
            ("get_message_unread_counts", {}),
            ("get_message_correspondents", {"folder": "received", "limit": 5}),
            ("get_message_correspondents", {"folder": "sent", "limit": 5}),
            ("get_messages", {"folder": "received", "limit": 5, "max_pages": 1, "page_size": 5}),
            ("get_messages", {"folder": "sent", "limit": 5, "max_pages": 1, "page_size": 5}),
            (
                "get_messages",
                {
                    "folder": "received",
                    "archived": True,
                    "limit": 5,
                    "max_pages": 1,
                    "page_size": 5,
                },
            ),
            (
                "get_messages",
                {"folder": "sent", "archived": True, "limit": 5, "max_pages": 1, "page_size": 5},
            ),
            (
                "get_messages",
                {
                    "folder": "received",
                    "unread_only": True,
                    "limit": 5,
                    "max_pages": 1,
                    "page_size": 5,
                },
            ),
        ]
    if phase == "communication":
        return [
            ("get_messages", {"folder": "received", "limit": 5, "max_pages": 1}),
            ("get_messages", {"folder": "sent", "limit": 5, "max_pages": 1}),
            ("get_recipient_types", {}),
        ]
    today = datetime.now(ZoneInfo("Europe/Warsaw")).date()
    if phase == "homework_history":
        return [
            (
                "get_homework",
                {
                    "date_from": (today - timedelta(days=28)).isoformat(),
                    "date_to": today.isoformat(),
                },
            )
        ]
    monday = today - timedelta(days=today.weekday())
    dates = {"date_from": (today - timedelta(days=7)).isoformat(), "date_to": today.isoformat()}
    return [
        ("get_student_information", {}),
        ("get_final_grades", {}),
        ("get_grades", {}),
        ("get_attendance", {}),
        ("get_grades_window", dates | {"limit": 10}),
        ("get_attendance_window", dates | {"limit": 10}),
        ("get_attendance_frequency", {}),
        ("get_subject_frequency", dates),
        ("get_timetable", {"monday": monday.isoformat()}),
        ("get_announcements", {}),
        ("get_agenda", {"year": today.year, "month": today.month}),
        ("get_homework", {}),
        ("get_completed_lessons", dates | {"limit": 10, "max_pages": 1}),
    ]


async def call(
    session: ClientSession,
    records: list[dict[str, Any]],
    index: int,
    name: str,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any] | None, bool]:
    result = await session.call_tool(name, arguments)
    value = result.structured_content
    if result.is_error:
        code = value.get("error", {}).get("code", "INTERNAL_ERROR") if value else "INTERNAL_ERROR"
        # A failed upstream response is never echoed, including raw ToolError text.
        records.append({"account_index": index, "tool": name, "status": code})
        return None, code in STOP_CODES
    records.append(
        {
            "account_index": index,
            "tool": name,
            "status": "passed",
            "coverage": "empty" if value is not None and value.get("items") == [] else "populated",
        }
    )
    if arguments.get("folder") in {"received", "sent"}:
        records[-1]["folder"] = arguments["folder"]
    for flag in ("archived", "unread_only"):
        if flag in arguments:
            records[-1][flag] = arguments[flag]
    if "correspondent" in arguments:
        records[-1]["filtered"] = True
    if "cursor" in arguments:
        records[-1]["continuation"] = True
    if value is not None and isinstance(value.get("items"), list):
        records[-1]["item_count"] = len(value["items"])
        if name in {"get_grades", "get_grades_window"}:
            records[-1]["formative_count"] = sum(
                item.get("record_type") == "formative" for item in value["items"]
            )
    return value, False


async def v21_continuation(
    session: ClientSession,
    records: list[dict[str, Any]],
    index: int,
    name: str,
    arguments: dict[str, Any],
    value: dict[str, Any],
) -> bool:
    """One continuation and one bound filter per discovery, with no body opens."""
    cursor = value.get("pagination", {}).get("next_cursor")
    if cursor is not None:
        _, stop = await call(session, records, index, name, arguments | {"cursor": cursor})
        if stop:
            return False
    if name == "get_message_correspondents" and value.get("items"):
        _, stop = await call(
            session,
            records,
            index,
            "get_messages",
            {
                "account_alias": arguments["account_alias"],
                "folder": arguments["folder"],
                "correspondent": value["items"][0]["reference"],
                "limit": 5,
                "max_pages": 1,
                "page_size": 5,
            },
        )
        if stop:
            return False
    return True


def detail_cases(results: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    selected = []
    for parent, child, argument in (
        ("get_agenda", "get_agenda_detail", "event_ref"),
        ("get_homework", "get_homework_detail", "homework_ref"),
    ):
        reference = next(
            (
                item.get("reference")
                for item in results.get(parent, {}).get("items", [])
                if item.get("reference") is not None
            ),
            None,
        )
        if reference is not None:
            selected.append((child, {argument: reference}))
    identifier = next(
        (
            item.get("detail_id")
            for item in results.get("get_attendance", {}).get("items", [])
            if item.get("detail_id") is not None
        ),
        None,
    )
    if identifier is not None:
        selected.append(("get_attendance_detail", {"attendance_id": identifier}))
    return selected


async def communication_details(
    session: ClientSession,
    records: list[dict[str, Any]],
    index: int,
    base: dict[str, str],
    results: dict[str, dict[str, Any]],
) -> bool:
    sent = results.get("get_messages", {})
    reference = next(
        (
            item.get("reference")
            for item in sent.get("items", [])
            if item.get("reference", {}).get("folder") == "sent"
        ),
        None,
    )
    if reference is not None:
        _, stop = await call(
            session, records, index, "get_message_content", base | {"message_ref": reference}
        )
        if stop:
            return False
    else:
        records.append(
            {
                "account_index": index,
                "tool": "get_message_content",
                "status": "unexercised_no_sent_reference",
            }
        )
    types = results.get("get_recipient_types", {})
    selected = next(
        (
            item["reference"]
            for item in types.get("items", [])
            if item["lookup_supported"] and item["available"] is not False
        ),
        None,
    )
    if selected is None:
        records.append(
            {
                "account_index": index,
                "tool": "get_recipients",
                "status": "unexercised_no_supported_type",
            }
        )
        return True
    choices, stop = await call(
        session, records, index, "get_recipient_choices", base | {"recipient_type": selected}
    )
    if stop:
        return False
    if selected["backend"] == "modern" and records[-1]["status"] == "UNSUPPORTED_CAPABILITY":
        # The catalog deliberately retains a legacy-only choice operation. Its
        # explicit unsupported result is expected here, not a successful lookup.
        records[-1]["status"] = "expected_unsupported"
    if choices and choices.get("items"):
        choice = next((item["reference"] for item in choices["items"] if item["available"]), None)
        if choice is not None:
            selected = selected | choice
    _, stop = await call(
        session, records, index, "get_recipients", base | {"recipient_type": selected}
    )
    return not stop


async def account_checks(
    session: ClientSession,
    config: AppConfig,
    records: list[dict[str, Any]],
    first_tool: str | None = None,
    phase: str = "academic",
) -> bool:
    for index, account in enumerate(config.accounts, start=1):
        base = {"account_alias": account.alias}
        _, stop = await call(session, records, index, "qualification_identity", base)
        if stop:
            return False
        results = {}
        selected = cases(phase)
        if index == 1 and first_tool is not None:
            start = next(offset for offset, item in enumerate(selected) if item[0] == first_tool)
            for name, _ in selected[:start]:
                records.append({"account_index": index, "tool": name, "status": "not_repeated"})
            selected = selected[start:]
            # A fresh native context cannot reuse an old detail reference. Read
            # attendance once to obtain a current reference for the detail check.
            if not any(name == "get_attendance" for name, _ in selected):
                selected.insert(0, ("get_attendance", {}))
        for name, arguments in selected:
            value, stop = await call(session, records, index, name, base | arguments)
            if stop:
                return False
            if value is not None:
                results[name] = value
                if phase == "v21" and not await v21_continuation(
                    session, records, index, name, base | arguments, value
                ):
                    return False
        if phase == "v21":
            continue
        if phase == "communication":
            if not await communication_details(session, records, index, base, results):
                return False
            continue
        details = detail_cases(results)
        for name, arguments in details:
            _, stop = await call(session, records, index, name, base | arguments)
            if stop:
                return False
        exercised = {name for name, _ in details}
        required_details = (
            {"get_homework_detail"}
            if phase == "homework_history"
            else {
                "get_agenda_detail",
                "get_homework_detail",
                "get_attendance_detail",
            }
        )
        for name in required_details - exercised:
            records.append(
                {"account_index": index, "tool": name, "status": "unexercised_no_reference"}
            )
    return True


async def qualify(
    path: Path,
    config: AppConfig,
    records: list[dict[str, Any]],
    first_tool: str | None = None,
    phase: str = "academic",
) -> dict[str, Any]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("LIBRUS_")}
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).resolve()), "--live", "--serve", "--config", str(path)],
        env=environment,
    )
    with open(os.devnull, "w") as errors, anyio.fail_after(MAX_SECONDS + 15):
        async with stdio_client(server, errlog=errors) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                aliases = await session.call_tool("list_accounts", {})
                if aliases.is_error or len(aliases.structured_content.get("items", [])) != len(
                    config.accounts
                ):
                    raise RuntimeError("account configuration mismatch")
                completed = await account_checks(session, config, records, first_tool, phase)
                totals = (await session.call_tool("qualification_budget", {})).structured_content
    return {"mcp_version": __version__, "completed": completed, "checks": records, "budget": totals}


def failure_summary(error: Exception) -> list[dict[str, Any]]:
    pending: list[BaseException] = [error]
    leaves = []
    for _ in range(32):
        if not pending:
            break
        current = pending.pop()
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions[:8])
            continue
        frames = []
        traceback = current.__traceback__
        for _ in range(32):
            if traceback is None:
                break
            frames.append(
                {
                    "file": Path(traceback.tb_frame.f_code.co_filename).name,
                    "line": traceback.tb_lineno,
                }
            )
            traceback = traceback.tb_next
        leaves.append({"type": type(current).__name__, "frames": frames[-3:]})
    return leaves


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="explicitly authorize ordinary reads")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--phase",
        choices=["academic", "communication", "homework_history", "v21"],
        default="academic",
    )
    parser.add_argument(
        "--first-account-from",
        choices=[name for name, _ in cases()],
        help="resume the first account without repeating earlier reads; these are not marked passed",
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; authentication changes last-login baselines")
    if args.phase != "academic" and args.first_account_from:
        parser.error("only academic checks support resuming at an academic tool")
    records: list[dict[str, Any]] = []
    try:
        path = args.config.expanduser().absolute()
        config = qualification_config(path)
        if args.serve:
            serve(config)
            return
        report = asyncio.run(qualify(path, config, records, args.first_account_from, args.phase))
    except Exception as error:  # noqa: BLE001 - one redacted boundary for local credentials/SDK errors
        print(
            json.dumps(
                {
                    "status": "qualification_failed",
                    "checks": records,
                    "failures": failure_summary(error),
                }
            )
        )
        raise SystemExit(1) from None
    print(json.dumps(report, separators=(",", ":")))
    if not report["completed"] or any(
        record["status"]
        not in {
            "passed",
            "unexercised_no_reference",
            "unexercised_no_sent_reference",
            "unexercised_no_supported_type",
            "expected_unsupported",
            "not_repeated",
        }
        for record in report["checks"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
