"""Bounded presentation of native history and class-free-day reads."""

from typing import Any, Literal

from librus_python_api import ArchiveAchievement, ArchiveYear, ClassFreeDay
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from librus_mcp.presentation import validate_window_cursor, window_page
from librus_mcp.read_schemas import AccountAliasInput, Cursor, PagedResult, PageLimit
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
    server.tool(title="School year archive", annotations=ordinary)(get_school_year_archive)
    server.tool(title="Class-free days", annotations=ordinary)(get_class_free_days)


async def get_school_year_archive(
    account_alias: AccountAliasInput,
    ctx: Context[Runtime, Any],
    cursor: Cursor[PresentationCursor] = None,
    limit: PageLimit = 10,
) -> PagedResult[ArchiveItem]:
    """List earlier school years with their marks and behaviour, then achievements. Cells keep Librus's exact text; a year's year_end mark may differ from that year's annual grade. Each page rereads the archive."""
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
    cursor: Cursor[PresentationCursor] = None,
    limit: PageLimit = 100,
) -> PagedResult[ClassFreeDay]:
    """List the student's days and lesson ranges without classes, such as holidays and school free days. type_id is an opaque code, not a name; a day without lesson numbers is not necessarily free all day."""
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
