"""Populated multi-page HTML fixtures for optimized pagination paths."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.librus_client import LibrusManager


def _message_row(message_id: str, index: int) -> str:
    attachment = '<img src="/assets/attachment.png"/>' if index % 2 else ""
    unread_style = ' style="font-weight: bold"' if index % 2 else ""
    return f"""
    <tr class="line{index % 2}">
      <td><input type="checkbox"/></td>
      <td>{attachment}</td>
      <td><a href="/wiadomosci/odebrane/pokaz/{message_id}">Teacher {index}</a></td>
      <td{unread_style}>Message {message_id}</td>
      <td>2026-01-{index + 1:02d}</td>
      <td><a href="#">delete</a></td>
    </tr>
    """


def _message_page(page: int, message_ids: list[str]) -> str:
    rows = "".join(
        _message_row(message_id, page * 10 + index) for index, message_id in enumerate(message_ids)
    )
    return f"""
    <html><body>
      <div class="pagination"><span>{page + 1} z 3</span></div>
      <table class="decorated stretch"><tbody>{rows}</tbody></table>
    </body></html>
    """


def _lesson_row(page: int, index: int) -> str:
    lesson_id = page * 10 + index
    return f"""
    <tr class="line{index % 2}">
      <td class="center small">2026-02-{lesson_id + 1:02d}</td>
      <td class="tiny">Mon.</td>
      <td>{lesson_id + 1}</td>
      <td>Subject {lesson_id}, Teacher {lesson_id}</td>
      <td>Topic {lesson_id}</td>
      <td>Z</td>
      <td><p class="box"><a onclick="otworz_w_nowym_oknie('/attendance/detail/{lesson_id}')">ob</a></p></td>
    </tr>
    """


def _lesson_page(page: int, count: int) -> str:
    rows = "".join(_lesson_row(page, index) for index in range(count))
    return f"""
    <html><body>
      <div class="pagination"><span>{page + 1} z 3</span></div>
      <table class="decorated"><tbody>{rows}</tbody></table>
    </body></html>
    """


@pytest.fixture
def populated_message_pages() -> dict[int, str]:
    return {
        0: _message_page(0, ["100", "101"]),
        1: _message_page(1, ["200", "201"]),
        2: _message_page(2, ["300"]),
    }


@pytest.fixture
def populated_lesson_pages() -> dict[int, str]:
    return {0: _lesson_page(0, 2), 1: _lesson_page(1, 2), 2: _lesson_page(2, 1)}


@pytest.mark.asyncio
async def test_received_messages_parse_every_fixture_page_once(populated_message_pages):
    client = SimpleNamespace(MESSAGE_URL="https://synergia.librus.pl/messages")
    client.get = MagicMock(return_value=SimpleNamespace(text=populated_message_pages[0]))
    posted_pages: list[int] = []

    def post(url, data):
        assert url == client.MESSAGE_URL
        page = int(data["numer_strony105"])
        posted_pages.append(page)
        return SimpleNamespace(text=populated_message_pages[page])

    client.post = post

    def execute(alias, function, *args, **kwargs):
        assert alias == "test_student"
        return function(client, *args, **kwargs)

    with patch.object(LibrusManager, "_execute", AsyncMock(side_effect=execute)):
        result = await LibrusManager.fetch_all_messages("test_student")

    assert [message.href for message in result["messages"]] == ["100", "101", "200", "201", "300"]
    assert result["pages_fetched"] == 3
    assert result["truncated"] is False
    client.get.assert_called_once_with(client.MESSAGE_URL)
    assert posted_pages == [1, 2]


@pytest.mark.asyncio
async def test_completed_lessons_parse_every_fixture_page_once(populated_lesson_pages):
    client = SimpleNamespace(COMPLETED_LESSONS_URL="https://synergia.librus.pl/completed-lessons")
    posted_pages: list[int] = []

    def post(url, data):
        assert url == client.COMPLETED_LESSONS_URL
        page = int(data["numer_strony1001"])
        posted_pages.append(page)
        return SimpleNamespace(text=populated_lesson_pages[page])

    client.post = post

    def execute(alias, function, *args, **kwargs):
        assert alias == "test_student"
        return function(client, *args, **kwargs)

    with patch.object(LibrusManager, "_execute", AsyncMock(side_effect=execute)):
        result = await LibrusManager.fetch_completed_lessons(
            "test_student", "2026-02-01", "2026-02-28"
        )

    assert [lesson.subject for lesson in result] == [
        "Subject 0",
        "Subject 1",
        "Subject 10",
        "Subject 11",
        "Subject 20",
    ]
    assert [lesson.topic for lesson in result] == [
        "Topic 0",
        "Topic 1",
        "Topic 10",
        "Topic 11",
        "Topic 20",
    ]
    assert posted_pages == [0, 1, 2]
