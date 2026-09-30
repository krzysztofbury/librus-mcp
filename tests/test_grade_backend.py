import pytest
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import SecretStr

from src.config import AccountConfig, AppConfig
from src.librus_client import LibrusManager
from src.scraping import FinalGrade
from src.server import to_dict


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["success", "unknown-account", "native-failure"])
async def test_explicit_summary_backend_preserves_scope_and_does_not_fallback(
    monkeypatch,
    tmp_path,
    mode,
):
    monkeypatch.setattr(
        LibrusManager,
        "_config_cache",
        AppConfig(
            accounts=[
                AccountConfig(
                    alias="fixture",
                    username="fixture",
                    password=SecretStr("fixture-only-never-valid"),
                )
            ],
            state_dir=tmp_path / "state",
            download_dir=tmp_path / "downloads",
        ),
    )
    monkeypatch.setattr(LibrusManager, "_final_grades_backend", None)
    calls: list[str] = []

    class Backend:
        async def final_grades(self, alias: str) -> list[FinalGrade]:
            calls.append(alias)
            if mode == "native-failure":
                raise ToolError("access_denied")
            return [FinalGrade("Fixture Topic", "progressing", "-", "4+")]

    async def forbidden_legacy(*args, **kwargs):
        raise AssertionError("A selected native backend must not dispatch legacy HTTP")

    monkeypatch.setattr(LibrusManager, "_execute", forbidden_legacy)
    LibrusManager.set_final_grades_backend(Backend())
    if mode == "unknown-account":
        with pytest.raises(ValueError):
            await LibrusManager.fetch_final_grades("not-configured")
        assert calls == []
    elif mode == "native-failure":
        with pytest.raises(ToolError, match="^access_denied$"):
            await LibrusManager.fetch_final_grades("fixture")
        assert calls == ["fixture"]
    else:
        result = await LibrusManager.fetch_final_grades("fixture")
        assert to_dict(result) == [
            {
                "subject": "Fixture Topic",
                "midterm": "progressing",
                "predicted_final": "-",
                "final": "4+",
            }
        ]
        assert calls == ["fixture"]
