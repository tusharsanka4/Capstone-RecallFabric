import asyncio
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from recallfabric.main import create_app

app = create_app()

with patch('recallfabric.api.extraction.client.chat.completions.create', new_callable=AsyncMock) as mock_create:
    mock_create.return_value.choices = [
        AsyncMock(message=AsyncMock(content='{"memories": [{"content": "User prefers concise answers", "type": "preference", "importance": 0.9, "confidence": 1.0, "creation_reason": "explicitly requested"}]}'))
    ]

    with TestClient(app) as client:
        print('Sending Memory Extraction Request to running app (Mocked LLM)...')
        response = client.post('/extraction', json={
            'user_id': 'alwin',
            'text': 'I prefer concise answers when you talk to me.',
            'source': 'conversation_42'
        })

        print('Status Code:', response.status_code)
        import json
        print('Response JSON:', json.dumps(response.json(), indent=2))
