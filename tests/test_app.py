"""Tests for the Flask web server."""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app import app
from resolver import ResolveResult


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestIndexRoute:
    def test_index_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Link Resolver" in resp.data


class TestResolveRoute:
    def test_missing_url(self, client):
        resp = client.post("/resolve", json={"url": ""})
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert "error" in data

    def test_missing_json_body(self, client):
        resp = client.post("/resolve", json={})
        assert resp.status_code == 400

    def test_valid_url_starts_task(self, client):
        with patch("app.threading.Thread") as mock_thread:
            mock_thread.return_value.start = MagicMock()
            resp = client.post("/resolve", json={"url": "https://rinku.pro/abc"})

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "task_id" in data
        assert len(data["task_id"]) == 8

    def test_url_without_protocol_gets_https(self, client):
        with patch("app.threading.Thread") as mock_thread:
            mock_thread.return_value.start = MagicMock()
            resp = client.post("/resolve", json={"url": "rinku.pro/abc"})

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "task_id" in data


class TestStreamRoute:
    def test_invalid_task_id(self, client):
        resp = client.get("/stream/nonexistent")
        assert resp.status_code == 404
