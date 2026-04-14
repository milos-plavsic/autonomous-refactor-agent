from fastapi.testclient import TestClient

from app.api import app

client = TestClient(app)


def test_health() -> None:
    assert client.get("/health").status_code == 200


def test_analyze() -> None:
    r = client.post("/v1/refactor/analyze", json={"target_path": "app/"})
    assert r.status_code == 200
    assert r.json()["target"] == "app/"
