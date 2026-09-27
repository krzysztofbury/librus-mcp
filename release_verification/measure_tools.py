"""Measure the actual MCP tools/list response over stdio with synthetic credentials."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import anyio
from mcp.client import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REPOSITORY = Path(__file__).resolve().parents[1]
TIMEOUT_SECONDS = 30


async def measure_tools(all_features: bool) -> dict[str, object]:
    features = {
        "notifications": True,
        "attachments": True,
        "behaviour_notes": all_features,
        "send_message": all_features,
    }
    environment = {
        "LIBRUS_ACCOUNTS": json.dumps(
            [{"alias": "synthetic", "username": "synthetic", "password": "synthetic"}]
        ),
        "LIBRUS_FEATURES": json.dumps(features),
    }
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.cli"],
        cwd=REPOSITORY,
        env=environment,
    )
    with anyio.fail_after(TIMEOUT_SECONDS):
        async with stdio_client(server) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                response = await session.list_tools()

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
    arguments = parser.parse_args()
    print(json.dumps(asyncio.run(measure_tools(arguments.all_features)), ensure_ascii=False))


if __name__ == "__main__":
    main()
