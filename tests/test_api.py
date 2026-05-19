from fastapi.testclient import TestClient

from app.api import app

client = TestClient(app)


def test_health() -> None:
    """Execute the test health routine."""
    assert client.get("/health").status_code == 200


def test_analyze() -> None:
    """Execute the test analyze routine."""
    r = client.post("/v1/refactor/analyze", json={"target_path": "app/"})
    assert r.status_code == 200
    assert r.json()["target"] == "app/"
