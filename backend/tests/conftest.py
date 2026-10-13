import os
import tempfile

os.environ["PADDY_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DEV_LOGIN"] = "1"
os.environ["WA_WORKER"] = "0"  # tests drive the relay directly
os.environ["ADMIN_EMAILS"] = "boss@x.org"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import core  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    if os.path.exists(core.DB_PATH):
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(core.DB_PATH + suffix):
                os.remove(core.DB_PATH + suffix)
    with TestClient(app) as c:
        yield c


def login(client, email, name="Ravi", phone="9876543210"):
    c = TestClient(app)  # app.state.conn already set up by the `client` fixture's lifespan
    r = c.post("/api/auth/dev", json={"email": email})
    assert r.status_code == 200, r.text
    if name:
        assert c.put("/api/me", json={"name": name, "phone": phone}).status_code == 200
    return c
