"""Every published tool schema must compile in real JSON Schema validators."""

import pytest
from jsonschema.validators import validator_for

from librus_mcp.config import AppConfig
from librus_mcp.server import create_server
from tests_native.test_config import config_data


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("features", "count"),
    [
        (None, 26),  # defaults: notifications and attachments on, sending off
        ({"notifications": False, "attachments": False}, 22),
        ({"send_message": True}, 30),
    ],
)
async def test_all_published_input_and_output_schemas_compile(features, count):
    data = config_data() | ({} if features is None else {"features": features})
    server = create_server(AppConfig.model_validate(data))
    tools = await server.list_tools()
    assert len(tools) == count
    for tool in tools:
        validator_for(tool.input_schema).check_schema(tool.input_schema)
        assert tool.output_schema is not None
        validator_for(tool.output_schema).check_schema(tool.output_schema)
