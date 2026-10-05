"""Bounded MCP presentation paging, never upstream traversal or snapshot storage."""

import hashlib
import json
from collections.abc import Sequence
from typing import TypeVar

from librus_python_api.exceptions import ErrorKind, LibrusError
from pydantic import TypeAdapter

from librus_mcp.read_schemas import PresentationCursor, WindowPagination

T = TypeVar("T")


def validate_window_cursor(
    cursor: PresentationCursor | None,
    context: str,
    query: tuple[str, ...],
) -> str:
    digest = hashlib.sha256(json.dumps(query, separators=(",", ":")).encode()).hexdigest()
    if cursor is not None and (cursor.context != context or cursor.query != digest):
        raise LibrusError(ErrorKind.INVALID_INPUT)
    return digest


def window_page(
    items: Sequence[T],
    *,
    context: str,
    query: tuple[str, ...],
    cursor: PresentationCursor | None,
    limit: int,
) -> tuple[tuple[T, ...], WindowPagination]:
    # Whole native collections are already bounded. Presentation cursors bind the
    # selected query and full source, not timestamps/generations that change on read.
    adapter: TypeAdapter[Sequence[T]] = TypeAdapter(Sequence[T])
    source = hashlib.sha256(adapter.dump_json(items)).hexdigest()
    query_digest = validate_window_cursor(cursor, context, query)
    offset = 0
    if cursor is not None:
        if cursor.context != context or cursor.query != query_digest:
            raise LibrusError(ErrorKind.INVALID_INPUT)
        if cursor.source != source or cursor.offset >= len(items):
            raise LibrusError(ErrorKind.STALE_CURSOR)
        offset = cursor.offset
    selected = tuple(items[offset : offset + limit])
    end = offset + len(selected)
    next_cursor = (
        None
        if end >= len(items)
        else PresentationCursor(
            context=context,
            query=query_digest,
            source=source,
            offset=end,
        )
    )
    return selected, WindowPagination(
        next_cursor=next_cursor,
        truncated=next_cursor is not None,
        reason="item_limit" if next_cursor else None,
    )
