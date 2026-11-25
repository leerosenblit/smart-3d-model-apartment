import os
import tempfile
from pathlib import Path

# Configure the environment BEFORE the app (and its cached settings) is imported.
_TMP = Path(tempfile.mkdtemp(prefix="roomcraft-tests-"))
os.environ["STORAGE_DIR"] = str(_TMP / "storage")
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'bootstrap.db').as_posix()}"
os.environ["IMAGE_TO_3D_PROVIDER"] = "mock"
os.environ["MOCK_GENERATION_SECONDS"] = "0.05"
for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "TRIPO_API_KEY", "MESHY_API_KEY"):
    os.environ[key] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, create_engine  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def engine(tmp_path):
    eng = create_engine(
        f"sqlite:///{(tmp_path / 'test.db').as_posix()}", connect_args={"check_same_thread": False}
    )
    db.set_engine(eng)
    return eng


@pytest.fixture()
def client(engine):
    """TestClient with a fresh DB; startup auto-seeds the catalog."""
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def empty_session(engine):
    db.init_db()
    with Session(engine) as s:
        yield s
