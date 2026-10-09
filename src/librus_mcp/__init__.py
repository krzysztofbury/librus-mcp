"""MCP 2.x application over the independent native API."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("librus-mcp")
except PackageNotFoundError:
    __version__ = "0+unknown"
