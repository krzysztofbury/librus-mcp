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


@pytest.mark.asyncio
async def test_published_schemas_drop_generated_titles_but_keep_title_properties():
    data = config_data() | {"features": {"send_message": True}}
    tools = await create_server(AppConfig.model_validate(data)).list_tools()
    titles = []

    def visit(schema, path):
        if not isinstance(schema, dict):
            return
        for key, value in schema.items():
            if key == "title" and isinstance(value, str):
                titles.append(path)
            elif key in {"properties", "$defs"} and isinstance(value, dict):
                for name, item in value.items():
                    visit(item, f"{path}.{key}.{name}")
            elif isinstance(value, dict):
                visit(value, f"{path}.{key}")
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    visit(item, f"{path}.{key}[{index}]")

    for tool in tools:
        visit(tool.input_schema, f"{tool.name}.input")
        visit(tool.output_schema, f"{tool.name}.output")
    assert titles == []
    agenda = next(tool for tool in tools if tool.name == "get_agenda").output_schema
    assert "title" in agenda["$defs"]["AgendaEventOutput"]["properties"]
    assert "title" in agenda["$defs"]["AgendaEventOutput"]["required"]
