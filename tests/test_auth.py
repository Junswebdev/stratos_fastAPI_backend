from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_register_validation():
    response = client.post("/api/v1/auth/register", json={})
    assert response.status_code == 422

def test_login_validation():
    response = client.post("/api/v1/auth/login", json={})
    assert response.status_code == 422
