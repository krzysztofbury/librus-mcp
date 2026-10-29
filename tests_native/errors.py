"""Closed error payloads with their diagnostic fields checked and removed."""

import re
from typing import Any

from librus_python_api import __version__ as api_version

from librus_mcp import __version__

_FIELDS = {"code", "requires", "where", "exception", "versions"}
_SITE = re.compile(r"[A-Za-z0-9_.]+:[A-Za-z0-9_.<>]+:[0-9]+")


def closed(content: Any) -> Any:
    """The `{"error": {"code": ...}}` part of an error result.

    `where` holds only code locations, `exception` only a class name and
    `versions` the two package versions; nothing else may appear. `requires`,
    an input name, is kept for the caller to compare.
    """
    if not isinstance(content, dict) or set(content) != {"error"}:
        return content
    error = dict(content["error"])
    assert set(error) <= _FIELDS, error
    assert error.pop("versions") == {"mcp": __version__, "api": api_version}
    if "where" in error:
        where = error.pop("where")
        assert where and all(_SITE.fullmatch(site) for site in where), where
    exception = error.pop("exception", None)
    assert exception is None or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", exception)
    return {"error": error}
