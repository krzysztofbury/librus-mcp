"""Bounded MCP presentation paging, never upstream traversal or snapshot storage."""

import hashlib
import json
from collections.abc import Sequence
from typing import Literal, TypeVar

from librus_python_api.exceptions import ErrorKind, LibrusError
from pydantic import TypeAdapter

from librus_mcp.schemas import PresentationCursor, SizedWindowPagination, WindowPagination

T = TypeVar("T")

# The server rejects a whole CallToolResult above this size with LIMIT.
MAX_RESULT_BYTES = 512 * 1024
# Identity, observation, pagination and the result envelope, in both copies.
_ENVELOPE_RESERVE = 16 * 1024


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
    source, query_digest, offset = _start(items, context, query, cursor)
    selected = tuple(items[offset : offset + limit])
    next_cursor = _next(items, context, query_digest, source, offset + len(selected))
    return selected, WindowPagination(
        next_cursor=next_cursor,
        truncated=next_cursor is not None,
        reason="item_limit" if next_cursor else None,
    )


def sized_page(
    items: Sequence[T],
    *,
    context: str,
    query: tuple[str, ...],
    cursor: PresentationCursor | None,
    limit: int,
    max_bytes: int | None = None,
) -> tuple[tuple[T, ...], SizedWindowPagination]:
    """Like `window_page`, but a page also ends before it outgrows the result cap.

    An item costs its JSON in `structuredContent` plus that JSON again as an
    escaped string in the text block. The first item of a page is always
    returned, so a long collection never blocks its later items. An item larger
    than the whole budget on its own still fails at the server's cap as LIMIT
    and its cursor stops there; `max_bytes` defaults to that cap less a reserve.
    """
    if max_bytes is None:
        max_bytes = MAX_RESULT_BYTES - _ENVELOPE_RESERVE
    # 3: encode each item once, for both the source digest and its size.
    adapter: TypeAdapter[Sequence[T]] = TypeAdapter(Sequence[T])
    encodings = [adapter.dump_json([item])[1:-1] for item in items]
    source = hashlib.sha256(b"[" + b",".join(encodings) + b"]").hexdigest()
    source, query_digest, offset = _start(items, context, query, cursor, source=source)
    selected: list[T] = []
    used = 0
    reason: Literal["item_limit", "size_limit"] | None = None
    for item, encoded in zip(items[offset:], encodings[offset:], strict=True):
        if len(selected) == limit:
            reason = "item_limit"
            break
        cost = len(encoded) + len(json.dumps(encoded.decode(), ensure_ascii=False).encode("utf-8"))
        if selected and used + cost > max_bytes:
            reason = "size_limit"
            break
        selected.append(item)
        used += cost
    next_cursor = _next(items, context, query_digest, source, offset + len(selected))
    return tuple(selected), SizedWindowPagination(
        next_cursor=next_cursor,
        truncated=next_cursor is not None,
        reason=reason if next_cursor else None,
    )


def _start(
    items: Sequence[T],
    context: str,
    query: tuple[str, ...],
    cursor: PresentationCursor | None,
    *,
    source: str | None = None,
) -> tuple[str, str, int]:
    # Whole native collections are already bounded. Presentation cursors bind the
    # selected query and full source, not timestamps/generations that change on read.
    if source is None:
        adapter: TypeAdapter[Sequence[T]] = TypeAdapter(Sequence[T])
        source = hashlib.sha256(adapter.dump_json(items)).hexdigest()
    query_digest = validate_window_cursor(cursor, context, query)
    offset = 0
    if cursor is not None:
        if cursor.source != source or cursor.offset >= len(items):
            raise LibrusError(ErrorKind.STALE_CURSOR)
        offset = cursor.offset
    return source, query_digest, offset


def _next(
    items: Sequence[T], context: str, query: str, source: str, end: int
) -> PresentationCursor | None:
    if end >= len(items):
        return None
    return PresentationCursor(context=context, query=query, source=source, offset=end)
