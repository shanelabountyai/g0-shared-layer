from __future__ import annotations

import pytest

from shared_layer.storage import Database, open_database


@pytest.fixture
def db() -> Database:
    database = open_database(":memory:")
    yield database
    database.close()
