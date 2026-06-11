"""Per-alias persistence of librus-apix NotificationIds.

The notifications module diffs current data against previously seen IDs.
The MCP server is stateless between sessions, so seen IDs are stored as one
JSON file per student alias under the state directory.
"""

import json
import os
import re
import sys
from pathlib import Path
from uuid import uuid4

from librus_apix.notifications import NotificationIds

CATEGORY_KEYS = ("grades", "attendance", "messages", "announcements", "schedule", "homework")
MAX_IDS_PER_CATEGORY = 10_000
# Upstream appends to seen-ID lists forever; keep only the newest tail so the
# file cannot grow without bound. Old items never reappear in the
# since-last-login views the diff reads from, so pruning them is safe.
MAX_SAVED_IDS_PER_CATEGORY = 500


def resolve_state_dir(config_state_dir: str | None) -> Path:
    """Resolve state dir. Priority: LIBRUS_STATE_DIR env > config > default."""
    if "LIBRUS_STATE_DIR" in os.environ:
        return Path(os.environ["LIBRUS_STATE_DIR"]).expanduser()
    if config_state_dir:
        return Path(config_state_dir).expanduser()
    return Path.home() / ".librus-mcp" / "state"


def _state_path(state_dir: Path, alias: str) -> Path:
    assert alias, "alias must not be empty"
    assert isinstance(alias, str), "alias must be a string"
    safe_alias = re.sub(r"[^A-Za-z0-9_-]", "_", alias)
    assert safe_alias, f"alias '{alias}' sanitizes to an empty filename"
    return state_dir / f"{safe_alias}.notifications.json"


def load_notification_ids(state_dir: Path, alias: str) -> NotificationIds | None:
    """Load seen notification IDs for an alias. Returns None when the file is
    missing or unusable (corrupt JSON, wrong schema) — callers then rebuild the
    baseline. Filesystem errors propagate: masking them as 'first run' would
    silently re-report every notification."""
    path = _state_path(Path(state_dir), alias)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"librus-mcp: corrupt notification state at {path}, rebuilding", file=sys.stderr)
        return None
    if not isinstance(data, dict) or set(data.keys()) != set(CATEGORY_KEYS):
        print(f"librus-mcp: unexpected notification state schema at {path}", file=sys.stderr)
        return None
    for key in CATEGORY_KEYS:
        if not isinstance(data[key], list):
            print(f"librus-mcp: unexpected notification state schema at {path}", file=sys.stderr)
            return None
    return NotificationIds(**data)


def save_notification_ids(state_dir: Path, alias: str, ids: NotificationIds) -> None:
    """Persist seen notification IDs atomically. The temp filename is unique per
    call so concurrent writers cannot interleave bytes in a shared temp file;
    last rename wins. Each category is pruned to its newest tail."""
    assert isinstance(ids, NotificationIds), "ids must be a NotificationIds instance"
    payload: dict[str, list] = {}
    for key in CATEGORY_KEYS:
        category = getattr(ids, key)
        assert isinstance(category, list), f"ids.{key} must be a list"
        assert len(category) <= MAX_IDS_PER_CATEGORY, f"ids.{key} unexpectedly large"
        payload[key] = category[-MAX_SAVED_IDS_PER_CATEGORY:]
    assert set(payload.keys()) == set(CATEGORY_KEYS), "payload must cover all categories"
    path = _state_path(Path(state_dir), alias)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    tmp_path.replace(path)
