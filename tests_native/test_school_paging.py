"""#117: a large agenda month or homework range is paged by size, not refused."""

import json
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from jsonschema.validators import validator_for
from librus_python_api import (
    Agenda,
    AgendaDay,
    AgendaEvent,
    Homework,
    HomeworkItem,
    Identity,
    Observation,
    Person,
    SchoolReference,
)
from mcp.server.mcpserver import Context

from tests_native.errors import closed
from tests_native.published_schema import STRICT_FORMATS

CONTEXT = "c" * 64
# A quote costs 2 bytes in structuredContent and 4 in the escaped text copy,
# so about 200 KB of this text is over the 512 KiB result cap when returned whole.
LONG = 'a"' * 2500


def observation() -> Observation:
    return Observation(
        account="fixture",
        observed_at=datetime(2026, 9, 24, 8, tzinfo=UTC),
        session_generation=1,
        source="fixture",
    )


def identity() -> Identity:
    return Identity(owner=Person(id="1"), student=Person(id="2"), observation=observation())


def agenda_event(index: int, text: str) -> AgendaEvent:
    return AgendaEvent(
        day=date(2026, 9, 1 + index // 2),
        title=f"Event {index}",
        subject=None,
        text=f"{index}{text}",
        lesson_number=None,
        at_time=None,
        metadata_text="",
        metadata=(),
        metadata_notes=(),
        reference=SchoolReference(kind="agenda", identifier=str(index), account="fixture"),
    )


def homework_item(index: int, topic: str) -> HomeworkItem:
    return HomeworkItem(
        subject="Fixture Subject",
        teacher="Fixture Teacher",
        topic=f"{index}{topic}",
        category="Assignment",
        assigned_on=date(2026, 9, 24),
        due_on=date(2026, 9, 25),
        submission_status=None,
        marked_done_at=None,
        reference=SchoolReference(kind="homework", identifier=str(index), account="fixture"),
    )


class StubClient:
    """The API account client with its reads stubbed; counts each read."""

    def __init__(self) -> None:
        self.context = SimpleNamespace(identifier=CONTEXT)
        self.events: list[AgendaEvent] = []
        self.homework: list[HomeworkItem] = []
        self.reads = 0

    async def agenda(self, year: int, month: int, *, budget: object) -> Agenda:
        self.reads += 1
        days: dict[date, list[AgendaEvent]] = {}
        for event in self.events:
            days.setdefault(event.day, []).append(event)
        return Agenda(
            identity=identity(),
            year=year,
            month=month,
            days=tuple(AgendaDay(day=day, events=tuple(events)) for day, events in days.items()),
            observation=observation(),
        )

    async def homework_range(self, request, *, budget: object) -> Homework:
        self.reads += 1
        return Homework(
            identity=identity(),
            start=request.start,
            end=request.end,
            items=tuple(self.homework),
            observation=observation(),
        )


def server_with(client: StubClient):
    from librus_mcp.config import AppConfig
    from librus_mcp.server import create_server

    config = AppConfig.model_validate(
        {
            "accounts": [
                {
                    "alias": "fixture",
                    "username": "login",
                    "password": "fixture-only",  # pragma: allowlist secret - fixture only
                }
            ],
            "context_key": bytes(range(32)).hex(),
        }
    )
    server = create_server(config)
    runtime = SimpleNamespace(account=lambda alias: client, budget=None)
    context = Context(request_context=SimpleNamespace(lifespan_context=runtime), mcp_server=server)
    return server, context


async def read_all(server, context, name, arguments, field):
    """Follow next_cursor to the end; return the field of every item and each page's reason."""
    tools = {tool.name: tool for tool in await server.list_tools()}
    schema = tools[name].output_schema
    validator = validator_for(schema)(schema, format_checker=STRICT_FORMATS)
    values, reasons, cursor = [], [], None
    while True:
        result = await server.call_tool(
            name, arguments | ({"cursor": cursor} if cursor else {}), context
        )
        assert not result.is_error, result.structured_content
        assert len(result.model_dump_json(by_alias=True).encode()) <= 512 * 1024
        validator.validate(result.structured_content)
        assert json.loads(result.content[0].text) == result.structured_content
        page = result.structured_content
        assert page["items"]
        values += [item[field] for item in page["items"]]
        reasons.append(page["pagination"]["reason"])
        cursor = page["pagination"]["next_cursor"]
        if cursor is None:
            assert page["pagination"]["truncated"] is False
            return values, reasons, page
        assert page["pagination"]["truncated"] is True


TOOLS = (
    pytest.param(
        "get_agenda",
        {"account_alias": "fixture", "year": 2026, "month": 9},
        ({"month": 10}, {"year": 2025}),
        "events",
        agenda_event,
        "text",
        id="agenda",
    ),
    pytest.param(
        "get_homework",
        {"account_alias": "fixture", "date_from": "2026-09-01", "date_to": "2026-09-30"},
        ({"date_to": "2026-09-29"}, {"date_from": "2026-09-02"}),
        "homework",
        homework_item,
        "topic",
        id="homework",
    ),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "query", "other", "attribute", "make", "field"), TOOLS)
async def test_a_large_result_is_returned_page_by_page(name, query, other, attribute, make, field):
    client = StubClient()
    # 40 items of 5 KB: about 200 KB of school text in one month or range.
    setattr(client, attribute, [make(index, LONG) for index in range(40)])
    server, context = server_with(client)
    values, reasons, _ = await read_all(server, context, name, query, field)
    assert values == [f"{index}{LONG}" for index in range(40)]
    assert reasons[-1] is None and set(reasons[:-1]) == {"size_limit"} and len(reasons) >= 2

    # A cursor is bound to its month or range and is checked before any read.
    first = await server.call_tool(name, query, context)
    cursor = first.structured_content["pagination"]["next_cursor"]
    reads = client.reads
    for change in other:
        moved = await server.call_tool(name, query | change | {"cursor": cursor}, context)
        assert moved.is_error and closed(moved.structured_content) == {
            "error": {"code": "INVALID_INPUT"}
        }
    assert client.reads == reads
    # A changed month or range is stale, not a page of the new collection.
    setattr(client, attribute, getattr(client, attribute)[1:])
    stale = await server.call_tool(name, query | {"cursor": cursor}, context)
    assert stale.is_error and closed(stale.structured_content) == {
        "error": {"code": "STALE_CURSOR"}
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "query", "other", "attribute", "make", "field"), TOOLS)
async def test_a_small_result_is_one_page_and_limit_pages_by_count(
    name, query, other, attribute, make, field
):
    client = StubClient()
    setattr(client, attribute, [make(index, " short") for index in range(3)])
    server, context = server_with(client)
    values, reasons, page = await read_all(server, context, name, query, field)
    assert values == [f"{index} short" for index in range(3)]
    assert reasons == [None]
    assert page["pagination"] == {
        "next_cursor": None,
        "truncated": False,
        "reason": None,
        "consistency": "best_effort",
    }
    values, reasons, _ = await read_all(server, context, name, query | {"limit": 2}, field)
    assert values == [f"{index} short" for index in range(3)]
    assert reasons == ["item_limit", None]
    # An empty month or range is one empty page.
    setattr(client, attribute, [])
    empty = await server.call_tool(name, query, context)
    assert not empty.is_error
    assert empty.structured_content["items"] == []
    assert empty.structured_content["pagination"]["next_cursor"] is None
