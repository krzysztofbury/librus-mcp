"""Closed error payloads with their diagnostic fields checked and removed."""

import json
import re
from typing import Any

from librus_python_api import __version__ as api_version
from mcp.types import CallToolResult, TextContent

from librus_mcp import __version__

_FIELDS = {"code", "requires", "where", "at", "exception", "versions"}
_SITE = re.compile(r"[A-Za-z0-9_.]+:[A-Za-z0-9_.<>]+:[0-9]+")


def closed(result: CallToolResult) -> Any:
    """The `{"error": {"code": ...}}` part of an error result.

    An error result is text only: hosts on the TypeScript SDK 1.x check any
    structuredContent against the output schema, even on an error. `where`
    holds only code locations, `at` a masked page location, `exception` only a
    class name and `versions` the two package versions; nothing else may
    appear. `requires`, an input name, is kept for the caller to compare.
    """
    if not result.is_error:
        return result.structured_content
    assert result.structured_content is None, result.structured_content
    (block,) = result.content
    assert isinstance(block, TextContent)
    content = json.loads(block.text)
    assert isinstance(content, dict) and set(content) == {"error"}, content
    error = dict(content["error"])
    assert set(error) <= _FIELDS, error
    assert error.pop("versions") == {"mcp": __version__, "api": api_version}
    if "where" in error:
        where = error.pop("where")
        assert where and all(_SITE.fullmatch(site) for site in where), where
    if "at" in error:
        at = error.pop("at")
        assert isinstance(at, str) and 0 < len(at) <= 512, at
    exception = error.pop("exception", None)
    assert exception is None or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", exception)
    return {"error": error}
