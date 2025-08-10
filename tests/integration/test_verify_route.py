from fastapi.testclient import TestClient
from main import app   # assume you expose FastAPI instance in main.py

def test_verify_404():
    cli = TestClient(app)
    res = cli.post("/v1/verify", json={"nie":"FAKE0000000000"})
    assert res.status_code == 200
    assert res.json()["data"]["status"] == "not_found"
