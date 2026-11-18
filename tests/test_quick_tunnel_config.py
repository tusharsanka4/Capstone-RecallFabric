from recallfabric.core.config import Settings
from recallfabric.main import create_app
from recallfabric.providers.factory import get_extraction_provider


def test_quick_tunnel_json_and_auth():
    settings = Settings(
        _env_file=None, auth_enabled=True, mcp_json_response=True, mcp_stateless_http=True
    )
    app = create_app(settings)
    assert app.state.mcp_server.session_manager.json_response is True
    assert app.state.mcp_server.session_manager.stateless is True
    assert app.state.settings.auth_enabled is True


def test_explicit_loopback_ollama_production():
    settings = Settings(
        _env_file=None,
        environment="production",
        auth_enabled=True,
        admin_token="test-admin",
        llm_provider="ollama",
        allow_local_ollama=True,
        llm_base_url="http://127.0.0.1:11434/v1",
    )
    assert get_extraction_provider(settings).name == "ollama"
    assert not Settings(
        _env_file=None, allow_local_ollama=True, llm_base_url="http://untrusted.example/v1"
    ).local_ollama_allowed()
