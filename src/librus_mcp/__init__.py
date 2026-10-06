"""MCP 2.0 application over the independent native API."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("librus-mcp")
except PackageNotFoundError:
    __version__ = "0+unknown"
