"""Bounded presentation of native history and class-free-day reads."""

from typing import Any, Literal

from librus_python_api import ArchiveAchievement, ArchiveYear, ClassFreeDay
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from librus_mcp.presentation import validate_window_cursor, window_page
from librus_mcp.read_schemas import AccountAliasInput, Limit, PagedResult
from librus_mcp.runtime import Runtime
from librus_mcp.schemas import PresentationCursor, WireModel


class ArchiveYearItem(WireModel):
    record_type: Literal["year"] = "year"
    data: ArchiveYear


class ArchiveAchievementItem(WireModel):
    record_type: Literal["achievement"] = "achievement"
    data: ArchiveAchievement


ArchiveItem = ArchiveYearItem | ArchiveAchievementItem


def register_school_history_tools(server: MCPServer[Runtime]) -> None:
    ordinary = ToolAnnotations(read_only_hint=True, open_world_hint=True)
    server.tool(annotations=ordinary)(get_school_year_archive)
    server.tool(annotations=ordinary)(get_class_free_days)


async def get_school_year_archive(
    account_alias: AccountAliasInput,
    ctx: Context[Runtime, Any],
    cursor: PresentationCursor | None = None,
    limit: Limit = 10,
) -> PagedResult[ArchiveItem]:
    """Page earlier school years then achievements. Preserve raw marks/behaviour cells; year_end is not asserted to equal annual grades. Each page refreshes the native archive and rejects source drift."""
    runtime = ctx.request_context.lifespan_context
    client = runtime.account(account_alias)
    query = ("school-year-archive",)
    validate_window_cursor(cursor, client.context.identifier, query)
    result = await client.school_year_archive(budget=runtime.budget)
    items: tuple[ArchiveItem, ...] = tuple(
        ArchiveYearItem(data=item) for item in result.years
    ) + tuple(ArchiveAchievementItem(data=item) for item in result.achievements)
    selected, pagination = window_page(
        items, context=client.context.identifier, query=query, cursor=cursor, limit=limit
    )
    return PagedResult[ArchiveItem](
        items=selected,
        identity=result.identity,
        observation=result.observation,
        pagination=pagination,
    )


async def get_class_free_days(
    account_alias: AccountAliasInput,
    ctx: Context[Runtime, Any],
    cursor: PresentationCursor | None = None,
    limit: Limit = 100,
) -> PagedResult[ClassFreeDay]:
    """Page native class-free date/lesson ranges. Type IDs are opaque; absent lesson bounds do not establish all-day holidays. Continuation rejects source drift."""
    runtime = ctx.request_context.lifespan_context
    client = runtime.account(account_alias)
    query = ("class-free-days",)
    validate_window_cursor(cursor, client.context.identifier, query)
    result = await client.class_free_days(budget=runtime.budget)
    selected, pagination = window_page(
        result.items, context=client.context.identifier, query=query, cursor=cursor, limit=limit
    )
    return PagedResult[ClassFreeDay](
        items=selected,
        identity=result.identity,
        observation=result.observation,
        pagination=pagination,
    )
