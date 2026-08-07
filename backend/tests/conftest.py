"""Test fixtures.

Tests run against SQLite in-memory so they need no containers. Two Postgres
types have to be taught to render on SQLite — JSONB and UUID. Production keeps
the real types; only the test dialect is adapted, so this never weakens the
schema that actually ships.
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret-key-that-is-long-enough-for-hs256!!")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "Bnma63VVdtrwvx4Gw1a8c07EXXqpgPtaaDwCAzyU0co=")
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "test-internal-token")

import pytest  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB, UUID  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(JSONB, "sqlite")
def _jsonb_on_sqlite(_type, _compiler, **_kw) -> str:
    return "JSON"


@compiles(UUID, "sqlite")
def _uuid_on_sqlite(_type, _compiler, **_kw) -> str:
    return "CHAR(36)"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
