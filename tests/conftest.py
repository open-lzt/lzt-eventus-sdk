"""Golden fixtures captured from a real `event_engine` `TestClient(build_app(...))`
run (see `tests/fixtures/api_captures.json`) — every response shape here is a
real server response, not a guess. Re-capture after any server-side API change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_FIXTURES: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "api_captures.json").read_text()
)


@pytest.fixture
def captures() -> dict[str, Any]:
    return _FIXTURES
