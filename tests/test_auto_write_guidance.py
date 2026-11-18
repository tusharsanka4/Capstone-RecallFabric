from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from test_conversation_decisions import Provider, decision, history
from test_mcp_contracts import connected

from recallfabric.core.config import Settings
from recallfabric.db.models import Memory
from recallfabric.embeddings.service import EmbeddingResult
from recallfabric.extraction.decisions import resolve_confirmed_decisions
from recallfabric.extraction.filters import filter_candidate
from recallfabric.mcp_server import RecallFabricTools


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_auto_write_guidance_has_positive_negative_and_update_boundaries():
    async with connected() as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        description = tools["remember"].description
        for phrase in [
            "Automatically save",
            "does not need to say",
            "Do not store every message",
            "monitor is vertical",
            "dark development environments",
            "Nova uses Django",
            "free-tier hosting",
            "Fedora",
            "tired today",
            "Maybe Django",
            "What if",
            "React might",
            "quoted examples",
            "general knowledge",
            "only after user",
            "update_memory",
            "expected_version",
        ]:
            assert phrase in description
        prompt = " ".join(m.content.text for m in (await client.get_prompt("use_memory")).messages)
        assert "instead of duplicating Spring Boot" in prompt
        assert "PostgreSQL replaces MongoDB" in prompt
        assert "Python instead of Java" in prompt
        assert "no durable decision without user acceptance" in prompt
        assert tools["remember"].input_schema["properties"]["extract"]["default"] is False


@pytest.mark.parametrize(
    "fact",
    [
        "User's secondary monitor is vertical for coding",
        "User prefers dark development environments",
        "User's Project Nova uses Django now",
    ],
)
def test_existing_extraction_filter_accepts_durable_candidates(fact):
    assert filter_candidate(fact, 0.8, 0.9, Settings(_env_file=None))[0]


@pytest.mark.parametrize(
    "text",
    [
        "User is tired today",
        "PostgreSQL is a relational database",
        "Use Redis",
        "What if we switched Nova to Django?",
    ],
)
def test_existing_filter_rejects_temporary_nonpersonal_questions_and_suggestions(text):
    assert not filter_candidate(text, 0.8, 0.9, Settings(_env_file=None))[0]


@pytest.mark.parametrize(
    "text",
    [
        "Maybe Django would be better.",
        "What if we switched Nova to Django?",
        "React might be nice.",
    ],
)
def test_tentative_and_hypothetical_are_not_accepted_recommendations(text):
    provider = Provider([])
    assert resolve_confirmed_decisions(provider, history("Use Redis."), text) == []
    assert provider.calls == 0


def test_existing_gate_accepts_single_grounded_recommendation():
    reply = "Sounds good, let's use that."
    provider = Provider([decision("User selected Redis for caching", "Redis", reply)])
    assert resolve_confirmed_decisions(provider, history("Use Redis."), reply)


@pytest.mark.parametrize(
    "old,new",
    [
        ("Project Nova uses Spring Boot.", "Project Nova uses Django now."),
        (
            "User prefers Java for backend work.",
            "User now prefers Python instead of Java for backend work.",
        ),
    ],
)
def test_existing_update_path_supersedes_instead_of_adding_contradictory_state(
    monkeypatch, old, new
):
    import recallfabric.mcp_server as module

    class Embedder:
        model_id = "test"
        dimensions = 3

        def embed(self, text, kind="passage"):
            return EmbeddingResult(model="test", dimensions=3, vector=[1.0, 0.0, 0.0])

    previous = Memory(
        id=uuid4(),
        version=1,
        user_id="alice",
        content=old,
        type="fact",
        status="active",
        source="test",
        importance=0.7,
        confidence=1.0,
        attributes={},
        access_count=0,
        created_at=datetime.now(UTC),
    )
    session = MagicMock()
    session.scalar.return_value = previous
    monkeypatch.setattr(module, "lock_memory_revision", lambda *args: None)
    monkeypatch.setattr(module, "record_event", lambda **kwargs: None)
    tools = RecallFabricTools(Settings(_env_file=None, auth_enabled=False), embedder=Embedder())
    tools._audit = MagicMock()
    result = tools.update_memory(
        str(previous.id), content=new, expected_version=1, session=session, user_id="alice"
    )
    current = session.add.call_args.args[0]
    assert previous.status == "superseded" and current.status == "active"
    assert current.id == previous.id and current.version == 2 and current.previous_version == 1
    assert current.content == new and result["version"] == 2


def test_compound_acceptance_still_rejects_ambiguous_alternatives():
    reply = "Sounds good, let's use that."
    provider = Provider([decision("User selected Redis", "Redis", reply)])
    assert resolve_confirmed_decisions(provider, history("Use Redis or Memcached."), reply) == []
    assert provider.calls == 0
