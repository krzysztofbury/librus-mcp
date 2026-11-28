"""`librus-mcp check-tools` covers every safe read tool and refuses the rest (#89)."""

import re
from datetime import date

import anyio
import pytest
from aiohttp import web
from jsonschema import Draft202012Validator
from librus_python_api import MessagingBackend
from librus_python_api.config import ENDPOINTS, SideEffect

from librus_mcp.check_tools import CATALOG_TOOLS, CHECKS, MODERN_ONLY, REFUSED, check_tools
from librus_mcp.config import AppConfig
from librus_mcp.server import create_server
from tests_native.test_config import config_data
from tests_native.test_failure_stdio import ALIAS, SECRET, BrokenTooltipWire, _wire_server
from tests_native.wire import STUDENT_GROUP, Wire

PROFILES = [
    None,
    {"notifications": False, "attachments": False},
    {"send_message": True},
]
# Why: a Sunday, the year's last and first day and a leap day are week edge cases.
DAYS = [date(2026, 11, 8), date(2026, 12, 31), date(2027, 1, 1), date(2028, 2, 29)]
# Why: these routes consume events, mark read or send; every `{id}` on them is numeric.
EFFECTS = frozenset({SideEffect.CONSUME_EVENTS, SideEffect.MARK_READ, SideEffect.SEND_MESSAGE})
EFFECT_ROUTES = [
    (
        endpoint.method,
        re.compile(re.sub(r"\\\{[a-z_]+\\\}", "[0-9]+", re.escape(endpoint.path)) + "/?"),
    )
    for endpoint in ENDPOINTS.values()
    if endpoint.side_effect in EFFECTS
]


@pytest.mark.asyncio
@pytest.mark.parametrize("features", PROFILES)
async def test_every_catalog_tool_is_either_checked_or_refused_with_a_reason(features):
    data = config_data() | ({} if features is None else {"features": features})
    tools = await create_server(AppConfig.model_validate(data)).list_tools()
    for tool in tools:
        kinds = [tool.name in CHECKS, tool.name in CATALOG_TOOLS, tool.name in REFUSED]
        assert kinds.count(True) == 1, tool.name
        if tool.name not in CHECKS:
            continue
        for day in DAYS:
            arguments = {"account_alias": "fixture"} | CHECKS[tool.name](day)
            Draft202012Validator(tool.input_schema).validate(arguments)
        required = set(tool.input_schema.get("required", ())) - {"account_alias"}
        assert required <= set(CHECKS[tool.name](DAYS[0])), tool.name


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requested",
    [("get_message_content",), ("get_new_notifications",), ("get_grades", "get_agenda_detail")],
)
async def test_a_tool_the_check_cannot_call_is_refused_before_any_read(tmp_path, requested):
    lines: list[str] = []
    async with Wire().serve() as wire:
        with anyio.fail_after(30):
            assert not await check_tools(
                _wire_server(wire.origin, tmp_path),
                [(ALIAS, MessagingBackend.MODERN)],
                requested,
                lines.append,
            )
        assert wire.calls == []
    refused = [name for name in requested if name in REFUSED]
    assert lines[1:] == [f"{name}: not checked, {REFUSED[name]}" for name in refused]


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["modern", "legacy"])
async def test_the_default_run_reads_every_safe_tool_without_effects(tmp_path, backend):
    lines: list[str] = []
    async with Wire().serve() as wire:
        server = _wire_server(wire.origin, tmp_path, backend=backend)
        with anyio.fail_after(90):
            valid = await check_tools(
                server,
                [(ALIAS, MessagingBackend(backend))],
                None,
                lines.append,
                today=lambda: date(2026, 9, 24),
            )
        assert valid, lines
        report = dict(line.split(": ", 1) for line in lines[1:])
        assert report.pop("catalog list_accounts").startswith("OK")
        listed = {name.removeprefix("login 1 ") for name in report}
        # Why: default features have sending off, so get_send_history is not listed.
        assert listed == set(CHECKS) - {"get_send_history"}
        for name, outcome in report.items():
            tool = name.removeprefix("login 1 ")
            if backend == "legacy" and tool in MODERN_ONLY:
                assert outcome == "not applicable, modern messaging only"
            else:
                assert outcome.startswith("OK"), (name, outcome)
        effects = [
            (method, path)
            for method, path, _ in wire.calls
            for effect_method, route in EFFECT_ROUTES
            if method == effect_method and route.fullmatch(path)
        ]
        assert effects == []
        assert any(route.fullmatch("/wiadomosci/1/5/123") for _, route in EFFECT_ROUTES)
        assert not any(route.fullmatch("/api/inbox/messages/senders") for _, route in EFFECT_ROUTES)
        assert ALIAS not in "\n".join(lines)
    status = await check_tools(
        _wire_server("http://localhost:9", tmp_path, backend=backend),
        [(ALIAS, MessagingBackend(backend))],
        ("get_notification_status",),
        lines.append,
    )
    assert status and lines[-1].startswith("login 1 get_notification_status: OK")


@pytest.mark.asyncio
async def test_a_student_login_reports_parent_only_justifications_as_unavailable(tmp_path):
    lines: list[str] = []
    async with Wire().serve() as wire:
        wire.account_group = STUDENT_GROUP
        with anyio.fail_after(30):
            assert await check_tools(
                _wire_server(wire.origin, tmp_path),
                [(ALIAS, MessagingBackend.MODERN)],
                ("get_justifications", "get_grades"),
                lines.append,
            )
        assert not any(path == "/eusprawiedliwienia" for _, path, _ in wire.calls)
    assert (
        lines[1] == "login 1 get_justifications: unavailable on this login (UNSUPPORTED_CAPABILITY)"
    )
    assert lines[2].startswith("login 1 get_grades: OK")


class ArchiveLoadingWire(Wire):
    status = 200

    async def _response(self, request):
        if request.path == "/archiwum":
            self.calls.append((request.method, request.path, None))
            if self.status != 200:
                return web.Response(status=self.status)
            # Why: Librus showed this notice live (2026-11-20) while filling the archive.
            return web.Response(
                text='<html><body><div class="warning-box information">'
                '<div class="warning-content">Opcja chwilowo niedostępna. Aktualnie '
                "trwa proces zasilania archiwum danymi z poprzedniego roku szkolnego. "
                "Po zakończeniu procesu zasilania opcja zostanie ponownie "
                "udostępniona.</div></div></body></html>",
                content_type="text/html",
            )
        return await super()._response(request)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,passed,line",
    [
        (200, True, "unavailable on this login (TEMPORARILY_UNAVAILABLE)"),
        # Why: since 2.10.0, Synergia being down is a failed check again, as before 2.9.1.
        (503, False, "tool error MAINTENANCE"),
    ],
)
async def test_only_a_view_unavailable_for_now_passes_as_unavailable(
    tmp_path, status, passed, line
):
    lines: list[str] = []
    wire = ArchiveLoadingWire()
    wire.status = status
    async with wire.serve():
        with anyio.fail_after(30):
            assert (
                await check_tools(
                    _wire_server(wire.origin, tmp_path),
                    [(ALIAS, MessagingBackend.MODERN)],
                    ("get_school_year_archive",),
                    lines.append,
                )
                is passed
            )
    assert lines[1].startswith(f"login 1 get_school_year_archive: {line}")


@pytest.mark.asyncio
async def test_a_page_failure_names_where_in_the_page_without_school_data(tmp_path):
    lines: list[str] = []
    wire = BrokenTooltipWire()
    async with wire.serve():
        with anyio.fail_after(30):
            assert not await check_tools(
                _wire_server(wire.origin, tmp_path),
                [(ALIAS, MessagingBackend.MODERN)],
                ("get_grades",),
                lines.append,
            )
    assert lines[1].startswith("login 1 get_grades: tool error PARSE at markup:tooltip_fields:")
    assert lines[1].endswith(
        "; page table.stretch.decorated[1] > tbody[1] > tr[1] > td[3] > span.grade-box[1] > a[1]"
    )
    assert all(SECRET not in line for line in lines)
