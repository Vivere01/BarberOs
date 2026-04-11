"""
BarberOS - Testes da API
"""
import pytest
from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


class TestHealthEndpoints:
    """Testes dos endpoints de saúde."""

    def test_root(self):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "BarberOS"

    def test_health(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_ready(self):
        response = client.get("/ready")
        assert response.status_code == 200


class TestWebhookEndpoints:
    """Testes dos endpoints de webhook."""

    def test_receive_message_requires_fields(self):
        """Verifica que campos obrigatórios são exigidos."""
        response = client.post(
            "/api/v1/webhook/message",
            json={"phone": "11999999999"},
        )
        # Deve falhar por falta de campos obrigatórios
        assert response.status_code == 422

    def test_list_conversations(self):
        response = client.get("/api/v1/webhook/conversations")
        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "conversations" in data
