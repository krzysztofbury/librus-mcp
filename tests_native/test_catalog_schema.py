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
        (None, 31),  # defaults: notifications and attachments on, sending off
        ({"notifications": False, "attachments": False}, 27),
        ({"send_message": True}, 35),
    ],
)
async def test_every_tool_has_a_title_effect_hints_described_inputs_and_compiling_schemas(
    features, count
):
    data = config_data() | ({} if features is None else {"features": features})
    server = create_server(AppConfig.model_validate(data))
    tools = await server.list_tools()
    assert len(tools) == count
    for tool in tools:
        # Directories and clients show the title and warn on effects; an unset
        # destructive hint on a write is read as destructive.
        assert tool.title, tool.name
        assert tool.annotations is not None and tool.annotations.read_only_hint is not None
        if not tool.annotations.read_only_hint:
            assert tool.annotations.destructive_hint is not None, tool.name
        # Agents choose arguments from these; a second, undescribed alias type
        # once left account_alias bare on most tools.
        for name, schema in tool.input_schema.get("properties", {}).items():
            assert schema.get("description"), (tool.name, name)
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


def _closed_objects(schema):
    if isinstance(schema, dict):
        return (schema.get("additionalProperties") is False) + sum(
            _closed_objects(value) for value in schema.values()
        )
    if isinstance(schema, list):
        return sum(_closed_objects(value) for value in schema)
    return 0


@pytest.mark.asyncio
async def test_output_schemas_accept_fields_a_later_release_adds():
    # Hosts validate results against the catalog they cached. A closed output
    # object made 2.4's new grade field fail every host holding the 2.3 catalog.
    data = config_data() | {"features": {"send_message": True}}
    tools = await create_server(AppConfig.model_validate(data)).list_tools()
    assert all(_closed_objects(tool.output_schema) == 0 for tool in tools)
    # Input schemas stay closed for hosts that validate arguments.
    assert any(_closed_objects(tool.input_schema) for tool in tools)
    grades = next(tool for tool in tools if tool.name == "get_final_grades").output_schema
    result = {
        "items": [],
        "identity": {"owner": {"id": "1"}, "student": {"id": "2"}},
        "observation": {},
        "added_later": True,
    }
    errors = list(validator_for(grades)(grades).iter_errors(result))
    assert not any("added_later" in error.message for error in errors)
