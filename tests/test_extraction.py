import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch
from tests.test_memories_api import api

from recallfabric.main import create_app
from recallfabric.core.config import Settings

@patch("recallfabric.api.extraction.client.chat.completions.create", new_callable=AsyncMock)
def test_memory_extraction_pipeline(mock_create, api):
    # Mock the LLM JSON output
    mock_create.return_value.choices = [
        AsyncMock(
            message=AsyncMock(
                content='{"memories": [{"content": "User loves Python", "type": "preference", "importance": 0.9, "confidence": 1.0, "creation_reason": "explicit"}]}'
            )
        )
    ]

    client, engine = api
    
    response = client.post(
        "/extraction",
        json={
            "user_id": "test_extract_user",
            "text": "I really love programming in Python.",
            "source": "conversation_123"
        }
    )
    
    assert response.status_code == 201
    data = response.json()
    assert "extracted" in data
    
    memories = data["extracted"]
    assert len(memories) == 1
    assert memories[0]["content"] == "User loves Python"
    assert memories[0]["type"] == "preference"
    assert memories[0]["user_id"] == "test_extract_user"
    assert memories[0]["importance"] == 0.9
    assert memories[0]["source"] == "conversation_123"
