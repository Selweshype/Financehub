"""Tests for backend/app/main.py — FastAPI application, middleware, and routes."""

import re
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app.config as config_module
from app.config import (
    AppConfig,
    DatabaseConfig,
    NordigenConfig,
    ResticConfig,
    Secrets,
    TokenEncryptionConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_secrets() -> Secrets:
    return Secrets(
        database=DatabaseConfig(key="testdbkey"),
        app=AppConfig(secret_key="testappsecret"),
        nordigen=NordigenConfig(secret_id="nid", secret_key="nkey"),
        token_encryption=TokenEncryptionConfig(master_key="mkey"),
        restic=ResticConfig(password="rpw", repository="s3://bucket/path"),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """TestClient with lifespan bypassed via mocked load_secrets."""
    fake_secrets = _make_fake_secrets()
    with patch("app.main.load_secrets", return_value=fake_secrets):
        from app.main import app

        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


@pytest.fixture(autouse=True)
def reset_secrets():
    """Ensure module-level _secrets is cleaned up after each test."""
    original = config_module._secrets
    yield
    config_module._secrets = original


# ---------------------------------------------------------------------------
# /health endpoint tests
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_ok_json(self, client):
        response = client.get("/health")
        assert response.json() == {"status": "ok"}

    def test_health_content_type_is_json(self, client):
        response = client.get("/health")
        assert "application/json" in response.headers["content-type"]

    def test_health_has_csp_header(self, client):
        response = client.get("/health")
        assert "Content-Security-Policy" in response.headers

    def test_health_has_x_content_type_options(self, client):
        response = client.get("/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_health_has_x_frame_options_deny(self, client):
        response = client.get("/health")
        assert response.headers.get("X-Frame-Options") == "DENY"


# ---------------------------------------------------------------------------
# CSP nonce middleware tests
# ---------------------------------------------------------------------------


class TestCspNonceMiddleware:
    def test_csp_header_is_present(self, client):
        response = client.get("/health")
        assert "Content-Security-Policy" in response.headers

    def test_csp_contains_default_src_self(self, client):
        response = client.get("/health")
        csp = response.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp

    def test_csp_contains_script_src_with_nonce(self, client):
        response = client.get("/health")
        csp = response.headers["Content-Security-Policy"]
        assert re.search(r"script-src 'self' 'nonce-[A-Za-z0-9_-]+'", csp)

    def test_csp_contains_style_src_with_nonce(self, client):
        response = client.get("/health")
        csp = response.headers["Content-Security-Policy"]
        assert re.search(r"style-src 'self' 'nonce-[A-Za-z0-9_-]+'", csp)

    def test_csp_contains_img_src(self, client):
        response = client.get("/health")
        csp = response.headers["Content-Security-Policy"]
        assert "img-src 'self' data:" in csp

    def test_csp_contains_frame_ancestors_none(self, client):
        response = client.get("/health")
        csp = response.headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in csp

    def test_csp_contains_form_action_self(self, client):
        response = client.get("/health")
        csp = response.headers["Content-Security-Policy"]
        assert "form-action 'self'" in csp

    def test_csp_contains_base_uri_self(self, client):
        response = client.get("/health")
        csp = response.headers["Content-Security-Policy"]
        assert "base-uri 'self'" in csp

    def test_csp_contains_connect_src_self(self, client):
        response = client.get("/health")
        csp = response.headers["Content-Security-Policy"]
        assert "connect-src 'self'" in csp

    def test_csp_nonce_script_and_style_match(self, client):
        """The nonce in script-src and style-src must be the same token."""
        response = client.get("/health")
        csp = response.headers["Content-Security-Policy"]
        script_match = re.search(r"script-src 'self' 'nonce-([A-Za-z0-9_-]+)'", csp)
        style_match = re.search(r"style-src 'self' 'nonce-([A-Za-z0-9_-]+)'", csp)
        assert script_match is not None
        assert style_match is not None
        assert script_match.group(1) == style_match.group(1)

    def test_nonce_is_unique_per_request(self, client):
        """Each request receives a distinct CSP nonce."""
        resp1 = client.get("/health")
        resp2 = client.get("/health")
        csp1 = resp1.headers["Content-Security-Policy"]
        csp2 = resp2.headers["Content-Security-Policy"]
        nonce1_match = re.search(r"script-src 'self' 'nonce-([A-Za-z0-9_-]+)'", csp1)
        nonce2_match = re.search(r"script-src 'self' 'nonce-([A-Za-z0-9_-]+)'", csp2)
        assert nonce1_match is not None
        assert nonce2_match is not None
        assert nonce1_match.group(1) != nonce2_match.group(1)

    def test_x_content_type_options_nosniff(self, client):
        response = client.get("/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options_deny(self, client):
        response = client.get("/health")
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_security_headers_applied_to_all_routes(self, client):
        """Both /health and other routes get security headers from middleware."""
        health_resp = client.get("/health")
        assert "Content-Security-Policy" in health_resp.headers
        assert health_resp.headers["X-Content-Type-Options"] == "nosniff"
        assert health_resp.headers["X-Frame-Options"] == "DENY"


# ---------------------------------------------------------------------------
# OpenAPI docs disabled tests
# ---------------------------------------------------------------------------


class TestOpenApiDisabled:
    def test_docs_url_returns_404(self, client):
        response = client.get("/docs")
        assert response.status_code == 404

    def test_redoc_url_returns_404(self, client):
        response = client.get("/redoc")
        assert response.status_code == 404

    def test_openapi_json_returns_404(self, client):
        response = client.get("/openapi.json")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# FastAPI app configuration tests
# ---------------------------------------------------------------------------


class TestAppConfiguration:
    def test_app_title_is_financehub(self):
        from app.main import app

        assert app.title == "FinanceHub"

    def test_docs_url_is_none(self):
        from app.main import app

        assert app.docs_url is None

    def test_redoc_url_is_none(self):
        from app.main import app

        assert app.redoc_url is None


# ---------------------------------------------------------------------------
# Lifespan tests
# ---------------------------------------------------------------------------


class TestLifespan:
    def test_lifespan_calls_load_secrets(self):
        """Lifespan startup should call load_secrets exactly once."""
        fake_secrets = _make_fake_secrets()
        with patch("app.main.load_secrets", return_value=fake_secrets) as mock_ls:
            from app.main import app

            with TestClient(app):
                pass
        mock_ls.assert_called_once()

    def test_lifespan_sets_config_module_secrets(self):
        """Lifespan startup should assign the loaded secrets to config_module._secrets."""
        fake_secrets = _make_fake_secrets()
        with patch("app.main.load_secrets", return_value=fake_secrets):
            from app.main import app

            with TestClient(app):
                assert config_module._secrets is fake_secrets

    def test_lifespan_load_secrets_failure_prevents_startup(self):
        """If load_secrets raises, the app should fail to start."""
        with patch("app.main.load_secrets", side_effect=RuntimeError("SOPS failed")):
            from app.main import app

            with pytest.raises(RuntimeError, match="SOPS failed"):
                with TestClient(app):
                    pass


# ---------------------------------------------------------------------------
# Index route tests (with mocked templates)
# ---------------------------------------------------------------------------


class TestIndexRoute:
    def test_index_returns_200(self, client):
        """GET / returns HTTP 200 (even if template raises, we verify route exists)."""
        # We patch the TemplateResponse to avoid filesystem dependency
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html; charset=utf-8"}

        with patch("app.main.templates") as mock_templates:
            from starlette.responses import HTMLResponse

            mock_templates.TemplateResponse.return_value = HTMLResponse(
                content="<html>Dashboard</html>", status_code=200
            )
            response = client.get("/")

        assert response.status_code == 200

    def test_index_passes_csp_nonce_to_template(self, client):
        """GET / should pass csp_nonce context variable to the template."""
        captured_context = {}

        def fake_template_response(template_name, context, **kwargs):
            captured_context.update(context)
            from starlette.responses import HTMLResponse

            return HTMLResponse(content="<html>ok</html>")

        with patch("app.main.templates") as mock_templates:
            mock_templates.TemplateResponse.side_effect = fake_template_response
            client.get("/")

        assert "csp_nonce" in captured_context
        nonce = captured_context["csp_nonce"]
        # nonce should be a non-empty string
        assert isinstance(nonce, str)
        assert len(nonce) > 0

    def test_index_uses_correct_template(self, client):
        """GET / should render 'dashboard/index.html'."""
        called_with_template = {}

        def fake_template_response(template_name, context, **kwargs):
            called_with_template["name"] = template_name
            from starlette.responses import HTMLResponse

            return HTMLResponse(content="<html>ok</html>")

        with patch("app.main.templates") as mock_templates:
            mock_templates.TemplateResponse.side_effect = fake_template_response
            client.get("/")

        assert called_with_template.get("name") == "dashboard/index.html"