import logging
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from recallfabric.core.config import Settings
from recallfabric.embeddings.service import (
    EmbeddingResult,
    create_embedding_provider,
)
from recallfabric.main import create_app


class TestProductionSafetyChecks:
    def test_refuse_auth_disabled_in_production(self):
        with pytest.raises(ValueError, match="Auth cannot be disabled"):
            Settings(
                environment="production",
                auth_enabled=False,
                admin_token=SecretStr("admin-secret-token"),
                openai_api_key=SecretStr("sk-proj-test1234"),
                db_password=SecretStr("custom-secure-pw"),
                _env_file=None,
            )

    def test_refuse_empty_admin_token_in_production(self):
        with pytest.raises(ValueError, match="RECALLFABRIC_ADMIN_TOKEN must be set"):
            Settings(
                environment="production",
                auth_enabled=True,
                admin_token=SecretStr(""),
                openai_api_key=SecretStr("sk-proj-test1234"),
                db_password=SecretStr("custom-secure-pw"),
                _env_file=None,
            )

    def test_refuse_default_db_password_in_production(self):
        with pytest.raises(ValueError, match="Default database password 'recallfabric_local'"):
            Settings(
                environment="production",
                auth_enabled=True,
                admin_token=SecretStr("admin-secret-token"),
                openai_api_key=SecretStr("sk-proj-test1234"),
                db_password=SecretStr("recallfabric_local"),
                _env_file=None,
            )

    def test_refuse_default_db_password_in_url_in_production(self):
        with pytest.raises(ValueError, match="Default database password 'recallfabric_local'"):
            Settings(
                environment="production",
                auth_enabled=True,
                admin_token=SecretStr("admin-secret-token"),
                openai_api_key=SecretStr("sk-proj-test1234"),
                database_url=SecretStr("postgresql://user:recallfabric_local@cloud-host/db"),
                _env_file=None,
            )

    def test_refuse_ollama_in_production_without_hosted_keys(self):
        with pytest.raises(ValueError, match="Ollama cannot be used in production"):
            Settings(
                environment="production",
                auth_enabled=True,
                admin_token=SecretStr("admin-secret-token"),
                db_password=SecretStr("custom-secure-pw"),
                llm_provider="ollama",
                _env_file=None,
            )

    def test_auto_defaults_to_hosted_provider_in_production(self):
        settings = Settings(
            environment="production",
            auth_enabled=True,
            admin_token=SecretStr("admin-secret-token"),
            db_password=SecretStr("custom-secure-pw"),
            openai_api_key=SecretStr("sk-proj-123"),
            _env_file=None,
        )
        assert settings.llm_provider == "openai"

    def test_hosted_embedding_requires_key_in_production(self):
        with pytest.raises(ValueError, match="requires RECALLFABRIC_OPENAI_API_KEY"):
            Settings(
                environment="production",
                auth_enabled=True,
                admin_token=SecretStr("admin-secret-token"),
                db_password=SecretStr("custom-secure-pw"),
                gemini_api_key=SecretStr("gemini-test-key"),  # LLM uses gemini
                embedding_provider="openai",
                openai_api_key=SecretStr(""),
                _env_file=None,
            )

    def test_valid_production_settings_pass(self):
        settings = Settings(
            environment="production",
            auth_enabled=True,
            admin_token=SecretStr("admin-secret-token-32-chars-ok!"),
            db_password=SecretStr("prod-super-secure-password"),
            openai_api_key=SecretStr("sk-proj-valid-api-key"),
            _env_file=None,
        )
        assert settings.environment == "production"
        assert settings.auth_enabled is True
        assert settings.llm_provider == "openai"


class TestCorsAndMiddleware:
    def test_cors_origins_parsing(self):
        s1 = Settings(cors_origins=["https://a.com", "https://b.com"], _env_file=None)
        assert s1.get_cors_origins() == ["https://a.com", "https://b.com"]

        s2 = Settings(cors_origins="https://a.com, https://b.com", _env_file=None)
        assert s2.get_cors_origins() == ["https://a.com", "https://b.com"]

    def test_cors_headers_returned(self):
        settings = Settings(cors_origins=["https://example.com"], _env_file=None)
        app = create_app(settings)
        with TestClient(app) as client:
            resp = client.options(
                "/health",
                headers={
                    "Origin": "https://example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert resp.status_code == 200
            assert resp.headers.get("access-control-allow-origin") == "https://example.com"

    def test_request_logging_without_bodies(self, caplog):
        caplog.set_level(logging.INFO)
        settings = Settings(_env_file=None)
        app = create_app(settings)
        with TestClient(app) as client:
            client.get("/health")

        log_messages = [r.getMessage() for r in caplog.records]
        assert any("request method=GET path=/health status=200" in m for m in log_messages)


class TestHostedEmbeddingProviders:
    def test_openai_embedding_provider_mock(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_item = MagicMock()
        mock_item.embedding = [0.05] * 1536
        mock_response.data = [mock_item]
        mock_client.embeddings.create.return_value = mock_response

        settings = Settings(
            embedding_provider="openai",
            openai_embedding_model="text-embedding-3-small",
            openai_embedding_dimensions=1536,
            openai_api_key=SecretStr("sk-test"),
            _env_file=None,
        )
        provider = create_embedding_provider(settings, client=mock_client)
        assert provider.model_id == "openai:text-embedding-3-small"
        assert provider.dimensions == 1536

        res = provider.embed("Hello world")
        assert isinstance(res, EmbeddingResult)
        assert len(res.vector) == 1536
        assert res.model == "openai:text-embedding-3-small"

    def test_gemini_embedding_provider_mock(self):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embedding": {"values": [0.02] * 768}}
        mock_client.post.return_value = mock_resp

        settings = Settings(
            embedding_provider="gemini",
            gemini_embedding_model="text-embedding-004",
            gemini_embedding_dimensions=768,
            gemini_api_key=SecretStr("gemini-test-key"),
            _env_file=None,
        )
        provider = create_embedding_provider(settings, client=mock_client)
        assert provider.model_id == "gemini:text-embedding-004"
        assert provider.dimensions == 768

        res = provider.embed("Testing gemini embedding")
        assert isinstance(res, EmbeddingResult)
        assert len(res.vector) == 768
        assert res.model == "gemini:text-embedding-004"
