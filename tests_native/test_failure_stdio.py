"""Failure reports over MCP stdio: code locations, never school data."""

import json
from html import escape

import anyio
import pytest
from aiohttp import web
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client

from librus_mcp.cli import main
from tests_native.errors import closed
from tests_native.test_native_stdio import server_process
from tests_native.wire import Wire

SECRET = "ZZSECRETZZ"
ALIAS = "kowalska"
TOOLTIP = escape(f"Data: 2026-09-24<br>Waga: 2<br>Uwaga {SECRET}", quote=True)
PAGE = f"""<html><body><table class="stretch decorated"><thead><tr>
<th>Oceny bieżące</th><th title="Ocena śródroczna z pierwszego okresu">Midterm</th>
<th>Oceny bieżące</th><th title="Ocena roczna">Annual</th>
</tr></thead><tbody><tr><td></td><td>Subject {SECRET}</td>
<td><span class="grade-box"><a title="{TOOLTIP}">4+</a></span></td>
<td>-</td><td>-</td><td>5</td></tr></tbody></table></body></html>"""


class BrokenTooltipWire(Wire):
    async def _response(self, request):
        if request.path == "/przegladaj_oceny/uczen":
            self.calls.append((request.method, request.path, None))
            if request.method == "POST":
                await request.post()
            return web.Response(text=PAGE, content_type="text/html")
        return await super()._response(request)


@pytest.mark.asyncio
@pytest.mark.parametrize("diagnose", [False, True])
async def test_a_parse_failure_names_its_site_without_school_data(tmp_path, diagnose):
    stderr_path = tmp_path / "stderr.txt"
    async with BrokenTooltipWire().serve() as wire:
        process = server_process(wire.origin, [(ALIAS, "71")])
        if diagnose:
            process.env["LIBRUS_MCP_DIAGNOSE_FAILURES"] = "1"
        with anyio.fail_after(30), stderr_path.open("w") as errlog:
            async with stdio_client(process, errlog=errlog) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    result = await session.call_tool("get_grades", {"account_alias": ALIAS})
    assert result.is_error
    assert closed(result.structured_content) == {"error": {"code": "PARSE"}}
    where = result.structured_content["error"]["where"]
    assert where[-1].startswith("markup:tooltip_fields:")
    assert where[-2].startswith("grade_records:_numeric:")
    payload = result.model_dump_json()
    assert SECRET not in payload and ALIAS not in payload
    stderr = stderr_path.read_text(encoding="utf-8")
    assert "librus-mcp: get_grades failed: PARSE at markup:tooltip_fields:" in stderr
    assert SECRET not in stderr and ALIAS not in stderr
    assert ("failure structure" in stderr) is diagnose
    if diagnose:
        assert "[[Data], [Waga], NO-COLON(len=" in stderr


def test_inspect_page_needs_no_configuration(tmp_path, monkeypatch, capsys):
    for name in ("LIBRUS_CONFIG", "LIBRUS_ACCOUNTS", "LIBRUS_USERNAME", "LIBRUS_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "missing"))
    page = tmp_path / "page.html"
    page.write_text(PAGE, encoding="utf-8")
    with pytest.raises(SystemExit) as failed:
        main(["inspect-page", "grades", str(page)])
    assert failed.value.code == 1
    output = capsys.readouterr().out
    assert "FAILED parse" in output and "at markup:tooltip_fields:" in output
    assert SECRET not in output
    page.write_text(PAGE.replace(f"&lt;br&gt;Uwaga {SECRET}", ""), encoding="utf-8")
    with pytest.raises(SystemExit) as parsed:
        main(["inspect-page", "grades", str(page)])
    assert parsed.value.code == 0
    assert "OK numeric=1" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_an_unknown_tool_name_is_never_echoed_to_stderr(capsys):
    from librus_mcp.config import AppConfig
    from librus_mcp.server import create_server

    config = AppConfig.model_validate(
        {
            "accounts": [
                {
                    "alias": ALIAS,
                    "username": "login",
                    "password": "fixture-only",  # pragma: allowlist secret - fixture only
                }
            ],
            "context_key": "00" * 32,
        }
    )
    result = await create_server(config).call_tool(f"get_grades_{ALIAS}\nlibrus-mcp: forged", {})
    assert closed(result.structured_content) == {"error": {"code": "INVALID_INPUT"}}
    stderr = capsys.readouterr().err
    assert stderr.count("\n") == 1
    assert ALIAS not in stderr and "forged" not in stderr
    assert stderr.startswith("librus-mcp: unknown tool failed: INVALID_INPUT")


def _wire_server(origin, tmp_path):
    from librus_python_api import ConnectionSettings

    from librus_mcp.config import AppConfig
    from librus_mcp.server import create_server

    config = AppConfig.model_validate(
        {
            "accounts": [
                {
                    "alias": ALIAS,
                    "username": "71",
                    "password": "not-a-real-password",  # pragma: allowlist secret - loopback only
                }
            ],
            "context_key": "00" * 32,
            "state_dir": str(tmp_path / "state"),
            "download_dir": str(tmp_path / "downloads"),
        }
    )
    connection = ConnectionSettings(
        synergia_origin=origin,
        api_origin=origin,
        download_origin=origin,
        messages_origin=origin,
    )
    return create_server(config, connection=connection)


@pytest.mark.asyncio
async def test_check_tools_reports_a_schema_mismatch_without_values(tmp_path, monkeypatch):
    from librus_mcp import server as module
    from librus_mcp.check_tools import check_tools

    lines: list[str] = []
    async with Wire().serve() as wire:
        wire.points = True
        tools = ("get_grades", "get_grades_window", "get_final_grades")
        with anyio.fail_after(30):
            assert await check_tools(
                _wire_server(wire.origin, tmp_path), [ALIAS], tools, lines.append
            )
        assert [line.split(": ")[-1] for line in lines[1:]] == [
            "OK, 4 items",
            "OK, 4 items",
            "OK, 2 items",
        ]
        # A host holding the 2.3 catalog: no point record type.
        listed = module.NativeServer.list_tools

        async def stale(self):
            tools = await listed(self)
            for tool in tools:
                text = json.dumps(tool.output_schema).replace('"numeric", "point"', '"numeric"')
                tool.output_schema = json.loads(text)
            return tools

        monkeypatch.setattr(module.NativeServer, "list_tools", stale)
        lines.clear()
        with anyio.fail_after(30):
            assert not await check_tools(
                _wire_server(wire.origin, tmp_path), [ALIAS], ("get_grades",), lines.append
            )
    (report,) = lines[1:]
    assert report.startswith("login 1 get_grades: SCHEMA MISMATCH at items/")
    assert '/record_type: enum ["numeric", "descriptive"], value type str' in report
    assert ALIAS not in "\n".join(lines) and "Point Subject" not in "\n".join(lines)
