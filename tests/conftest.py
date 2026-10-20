import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from internal_ai.app.config import Settings
from internal_ai.app.database import Base
from internal_ai.app.main import app, get_db

settings = Settings()

engine = create_engine(
    "postgresql+psycopg2://postgres:weneedjust12@localhost:5432/testing",
    pool_pre_ping=True,
)

TestingSessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


@pytest.fixture
def db_session():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    with TestingSessionLocal() as session:
        yield session

    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
