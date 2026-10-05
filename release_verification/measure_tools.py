"""Measure the actual MCP tools/list response over stdio with synthetic credentials."""

import argparse
import asyncio
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path
from typing import Any

import anyio
from mcp.client import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import ListToolsResult

REPOSITORY = Path(__file__).resolve().parents[1]
TIMEOUT_SECONDS = 30


async def list_tools(all_features: bool) -> ListToolsResult:
    features = {
        "notifications": all_features,
        "attachments": all_features,
        "behaviour_notes": False,
        "send_message": all_features,
    }
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("LIBRUS_")
    }
    environment.update(
        {
            "LIBRUS_ACCOUNTS": json.dumps(
                [
                    {
                        "alias": "synthetic",
                        "username": "synthetic",
                        "password": "synthetic",  # pragma: allowlist secret - fixture only
                    }
                ]
            ),
            "LIBRUS_FEATURES": json.dumps(features),
            "LIBRUS_CONTEXT_KEY": secrets.token_hex(32),
        }
    )
    scratch_root = os.environ.get("AGENT_SCRATCH_DIR")
    if scratch_root is None and Path("/tmp/opencode").is_dir():
        scratch_root = "/tmp/opencode"
    with (
        tempfile.TemporaryDirectory(prefix="catalog-", dir=scratch_root) as scratch,
        anyio.fail_after(TIMEOUT_SECONDS),
    ):
        environment.update(
            LIBRUS_STATE_DIR=str(Path(scratch) / "state"),
            LIBRUS_DOWNLOAD_DIR=str(Path(scratch) / "downloads"),
        )
        server = StdioServerParameters(
            command=sys.executable, args=["-m", "librus_mcp.cli"], cwd=REPOSITORY, env=environment
        )
        async with stdio_client(server) as streams, ClientSession(*streams) as session:
            await session.initialize()
            response = await session.list_tools()

    return response


def tool_contracts(response: ListToolsResult) -> dict[str, dict[str, Any]]:
    """Capture the public schemas and safety hints, independent of prose."""
    return {
        tool.name: {
            "inputSchema": tool.input_schema,
            "outputSchema": tool.output_schema,
            "annotations": tool.annotations.model_dump(by_alias=True, exclude_unset=True)
            if tool.annotations is not None
            else None,
        }
        for tool in sorted(response.tools, key=lambda tool: tool.name)
    }


async def measure_tools(all_features: bool) -> dict[str, object]:
    response = await list_tools(all_features)
    return {
        "profile": "all" if all_features else "default",
        "tools": len(response.tools),
        "bytes": len(response.model_dump_json(by_alias=True, exclude_unset=True).encode("utf-8")),
        "with_output_schema": sum(tool.output_schema is not None for tool in response.tools),
        "names": [tool.name for tool in response.tools],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all-features", action="store_true", help="include disabled optional tools"
    )
    parser.add_argument("--contracts", action="store_true", help="print schemas and annotations")
    arguments = parser.parse_args()
    if arguments.contracts:
        result = tool_contracts(asyncio.run(list_tools(arguments.all_features)))
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(json.dumps(asyncio.run(measure_tools(arguments.all_features)), ensure_ascii=False))


if __name__ == "__main__":
    main()
