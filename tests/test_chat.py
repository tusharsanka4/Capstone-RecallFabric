import json
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openai import APIConnectionError, APITimeoutError

from recallfabric.api.chat import get_llm_client
from recallfabric.context.builder import (
    assemble_system_prompt,
    build_context_block,
    format_memory_line,
)
from recallfabric.core.config import Settings
from recallfabric.db.models import Memory
from recallfabric.db.session import get_session
from recallfabric.embeddings.service import get_embedding_provider
from recallfabric.main import create_app


class FakeEmbedder:
    model_id = "BAAI/bge-small-en-v1.5"
    dimensions = 384

    def embed(self, text: str, kind: str = "passage"):
        vector = [0.0] * self.dimensions
        if "ramen" in text.lower() or "eat" in text.lower() or "food" in text.lower():
            vector[0] = 1.0
        elif "close" in text.lower():
            vector[0] = 0.9
        else:
            vector[1] = 1.0
        return SimpleNamespace(vector=vector, model=self.model_id, dimensions=self.dimensions)


def make_mock_llm(reply_text: str = "I am RecallFabric"):
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = reply_text
    mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
    return mock_client


def test_context_builder_formatting_and_budget_truncation():
    mem1 = SimpleNamespace(type="preference", content="Likes spicy food", score=0.9)
    mem2 = SimpleNamespace(type="fact", content="Lives in Seattle", score=0.8)
    mem3 = SimpleNamespace(type="goal", content="Wants to run a marathon", score=0.4)

    assert format_memory_line(mem1) == "- [preference] Likes spicy food"

    full_context, used = build_context_block([mem1, mem2, mem3], max_chars=1000)
    assert len(used) == 3
    assert "- [preference] Likes spicy food" in full_context
    assert "- [fact] Lives in Seattle" in full_context
    assert "- [goal] Wants to run a marathon" in full_context

    budget = len("- [preference] Likes spicy food\n- [fact] Lives in Seattle") + 5
    truncated_context, truncated_used = build_context_block([mem1, mem2, mem3], max_chars=budget)
    assert len(truncated_used) == 2
    assert mem3 not in truncated_used
    assert "- [goal]" not in truncated_context

    zero_context, zero_used = build_context_block([mem1, mem2, mem3], max_chars=0)
    assert zero_context == ""
    assert zero_used == []


def test_context_builder_assemble_system_prompt():
    base = "Base system prompt."
    ctx = "- [fact] User loves python"
    assembled = assemble_system_prompt(base, ctx)
    assert "Base system prompt." in assembled
    assert "Memory Notes about the User:" in assembled
    assert ctx in assembled

    empty_assembled = assemble_system_prompt(base, "")
    assert empty_assembled == base


def test_chat_endpoint_prompt_contains_memories_and_budget():
    app = create_app(Settings(_env_file=None, environment="test", context_max_chars=2000))
    mock_llm = make_mock_llm("You like ramen.")
    app.dependency_overrides[get_llm_client] = lambda: mock_llm
    app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbedder()

    mock_memory = Memory(
        id=uuid4(),
        version=1,
        user_id="alice",
        content="User likes spicy ramen",
        type="preference",
        source="test",
        status="active",
        importance=0.9,
        confidence=0.9,
        access_count=0,
        attributes={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        embedding=[1.0] + [0.0] * 383,
        embedding_model="BAAI/bge-small-en-v1.5",
        embedding_dimensions=384,
    )
    mock_session = MagicMock()
    mock_session.execute.return_value.all.return_value = [(mock_memory, 0.95)]
    mock_session.begin.return_value.__enter__.return_value = None
    mock_session.begin.return_value.__exit__.return_value = None
    app.dependency_overrides[get_session] = lambda: mock_session

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={
                "user_id": "alice",
                "message": "What do I like to eat?",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["reply"] == "You like ramen."
        assert len(data["memories_used"]) == 1
        assert data["memories_used"][0]["content"] == "User likes spicy ramen"
        assert "score" in data["memories_used"][0]

        call_args = mock_llm.chat.completions.create.call_args[1]
        sent_messages = call_args["messages"]
        system_msg = sent_messages[0]["content"]
        assert "Memory Notes about the User:" in system_msg
        assert "User likes spicy ramen" in system_msg


def test_chat_endpoint_history_is_trimmed():
    app = create_app(Settings(_env_file=None, environment="test", chat_history_limit=4))
    mock_llm = make_mock_llm("History trimmed reply")
    app.dependency_overrides[get_llm_client] = lambda: mock_llm
    app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbedder()

    mock_session = MagicMock()
    mock_session.execute.return_value.all.return_value = []
    mock_session.begin.return_value.__enter__.return_value = None
    mock_session.begin.return_value.__exit__.return_value = None
    app.dependency_overrides[get_session] = lambda: mock_session

    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg_{i}"} for i in range(10)
    ]

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={
                "user_id": "alice",
                "message": "New question",
                "history": history,
            },
        )
        assert response.status_code == 200
        sent_messages = mock_llm.chat.completions.create.call_args[1]["messages"]
        history_msgs = sent_messages[1:-1]
        assert len(history_msgs) == 4
        assert history_msgs[0]["content"] == "msg_6"
        assert history_msgs[-1]["content"] == "msg_9"
        assert sent_messages[-1]["content"] == "New question"


def test_chat_endpoint_errors_unreachable():
    app = create_app(Settings(_env_file=None, environment="test"))
    mock_llm = MagicMock()
    mock_llm.chat.completions.create.side_effect = APIConnectionError(request=MagicMock())
    app.dependency_overrides[get_llm_client] = lambda: mock_llm
    app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbedder()

    mock_session = MagicMock()
    mock_session.execute.return_value.all.return_value = []
    mock_session.begin.return_value.__enter__.return_value = None
    mock_session.begin.return_value.__exit__.return_value = None
    app.dependency_overrides[get_session] = lambda: mock_session

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"user_id": "alice", "message": "hello"},
        )
        assert response.status_code == 503


def test_chat_endpoint_errors_timeout():
    app = create_app(Settings(_env_file=None, environment="test"))
    mock_llm = MagicMock()
    mock_llm.chat.completions.create.side_effect = APITimeoutError(request=MagicMock())
    app.dependency_overrides[get_llm_client] = lambda: mock_llm
    app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbedder()

    mock_session = MagicMock()
    mock_session.execute.return_value.all.return_value = []
    mock_session.begin.return_value.__enter__.return_value = None
    mock_session.begin.return_value.__exit__.return_value = None
    app.dependency_overrides[get_session] = lambda: mock_session

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"user_id": "alice", "message": "hello"},
        )
        assert response.status_code == 504


@pytest.mark.skipif(
    os.getenv("RECALLFABRIC_RUN_DB_TESTS") != "1",
    reason="Set RECALLFABRIC_RUN_DB_TESTS=1 for PostgreSQL integration checks",
)
def test_chat_acceptance_flow_with_db(retrieval_api):
    client, engine, _ = retrieval_api

    mock_llm = make_mock_llm("You love spicy ramen.")
    client.app.dependency_overrides[get_llm_client] = lambda: mock_llm

    create_res = client.post(
        "/memories",
        json={
            "user_id": "ramen_lover",
            "content": "User likes spicy ramen",
            "type": "preference",
            "source": "test",
            "importance": 0.9,
            "confidence": 0.9,
        },
    )
    assert create_res.status_code == 201

    chat_res = client.post(
        "/chat",
        json={
            "user_id": "ramen_lover",
            "message": "What do I like to eat?",
        },
    )
    assert chat_res.status_code == 200
    data = chat_res.json()
    assert data["reply"] == "You love spicy ramen."
    assert len(data["memories_used"]) >= 1
    contents = [m["content"] for m in data["memories_used"]]
    assert "User likes spicy ramen" in contents


@pytest.mark.skipif(
    os.getenv("RECALLFABRIC_RUN_DB_TESTS") != "1",
    reason="Set RECALLFABRIC_RUN_DB_TESTS=1 for PostgreSQL integration checks",
)
def test_chat_extract_flag_creates_memories(retrieval_api):
    client, engine, _ = retrieval_api

    chat_resp_obj = MagicMock()
    chat_resp_obj.choices = [
        MagicMock(message=MagicMock(content="I noted that you live in Seattle."))
    ]

    extract_resp_obj = MagicMock()
    extract_payload = json.dumps(
        {
            "memories": [
                {
                    "content": "User lives in Seattle",
                    "type": "profile",
                    "importance": 0.9,
                    "confidence": 0.9,
                }
            ]
        }
    )
    extract_resp_obj.choices = [MagicMock(message=MagicMock(content=extract_payload))]

    mock_llm = MagicMock()
    mock_llm.chat.completions.create.side_effect = [chat_resp_obj, extract_resp_obj]
    client.app.dependency_overrides[get_llm_client] = lambda: mock_llm

    chat_res = client.post(
        "/chat",
        json={
            "user_id": "extract_user",
            "message": "I live in Seattle.",
            "extract": True,
        },
    )
    assert chat_res.status_code == 200
    data = chat_res.json()
    assert data["reply"] == "I noted that you live in Seattle."
    assert len(data["extracted"]) == 1
    assert data["extracted"][0]["content"] == "User lives in Seattle"
