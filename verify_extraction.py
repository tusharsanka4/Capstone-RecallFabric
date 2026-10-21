import json
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from recallfabric.api.extraction import get_llm_client
from recallfabric.main import create_app

app = create_app()

content = json.dumps(
    {
        "memories": [
            {
                "content": "User prefers concise answers",
                "type": "preference",
                "importance": 0.9,
                "confidence": 1.0,
                "creation_reason": "explicitly requested",
            }
        ]
    }
)
mock_client = MagicMock()
mock_client.chat.completions.create.return_value = MagicMock(
    choices=[MagicMock(message=MagicMock(content=content))]
)
app.dependency_overrides[get_llm_client] = lambda: mock_client

with TestClient(app) as client:
    response = client.post(
        "/extraction",
        json={
            "user_id": "alwin",
            "text": "I prefer concise answers when you talk to me.",
            "source": "conversation_42",
        },
    )
    print("Status Code:", response.status_code)
    print("Response JSON:", json.dumps(response.json(), indent=2))
