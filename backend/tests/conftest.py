"""
Integration-style tests run against the real Postgres+pgvector service
(from docker-compose), not a mocked DB. Vector columns don't have a
faithful SQLite equivalent, and this platform's whole point is the
retrieval behavior — mocking the DB would test nothing that matters.

Run with the stack up:
    docker compose up -d postgres
    cd backend && pytest
"""

import pytest
from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import engine
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def _prepare_schema():
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict:
    from app.config import settings

    return {"Authorization": f"Bearer {settings.api_auth_token}"}
