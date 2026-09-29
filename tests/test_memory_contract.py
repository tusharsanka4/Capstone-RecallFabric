import pytest
from pydantic import ValidationError

from recallfabric.schemas.memory import MemoryCreate


def valid_input(**changes):
    return {
        "user_id": "user_123",
        "content": "User is learning Spring Boot",
        "type": "skill",
        "source": "conversation_102",
        **changes,
    }


def test_input_defaults_and_normalization():
    memory = MemoryCreate(**valid_input(content="  Learning Spring Boot  "))
    assert memory.content == "Learning Spring Boot"
    assert memory.importance == 0.5
    assert memory.confidence == 1
    assert memory.metadata == {}


@pytest.mark.parametrize(
    "changes",
    [
        {"content": " \n "},
        {"user_id": ""},
        {"source": " "},
        {"type": "invalid"},
        {"importance": -0.1},
        {"confidence": 1.1},
        {"importance": float("nan")},
        {"confidence": float("inf")},
        {"metadata": []},
        {"version": 2},
        {"status": "superseded"},
    ],
)
def test_invalid_input(changes):
    with pytest.raises(ValidationError):
        MemoryCreate(**valid_input(**changes))
