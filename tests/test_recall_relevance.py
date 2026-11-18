from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from recallfabric.core.config import Settings
from recallfabric.db.models import Memory
from recallfabric.embeddings.service import EmbeddingResult
from recallfabric.mcp_server import RecallFabricTools


class Embedder:
    model_id = "test-model"
    dimensions = 3

    def embed(self, text, kind="passage"):
        return EmbeddingResult(model=self.model_id, dimensions=3, vector=[1.0, 0.0, 0.0])


def run(scores, limit=5, cutoff=0.6, alias=False):
    session = MagicMock()
    rows = []
    for index, score in enumerate(scores):
        mem = Memory(
            id=uuid4(),
            user_id="alice",
            content=f"memory-{index}",
            type="fact",
            importance=1.0,
            confidence=1.0,
            access_count=0,
            created_at=datetime.now(UTC),
            version=1,
            status="active",
        )
        rows.append((mem, score))
    session.execute.return_value.all.return_value = rows
    tools = RecallFabricTools(
        settings=Settings(_env_file=None, auth_enabled=False, recall_min_relevance=cutoff),
        embedder=Embedder(),
    )
    result = (tools.search_memory if alias else tools.recall)(
        "Project Orion", limit=limit, session=session, user_id="alice"
    )
    return result, rows, session


@pytest.mark.parametrize(
    "scores,expected",
    [
        ([0.7332, 0.3489], 1),
        ([0.4257, 0.3595], 0),
        ([0.8161, 0.7838, 0.7519, 0.3957], 3),
        ([0.8, 0.75, 0.48], 2),
        ([0.95, 0.9, 0.85], 3),
    ],
)
def test_recall_returns_only_relevant_matches(scores, expected):
    result, rows, session = run(scores)
    assert result["count"] == expected
    assert len(result["memories"]) == expected
    assert all(m["similarity"] >= 0.6 for m in result["memories"])
    assert all(mem.access_count == (1 if score >= 0.6 else 0) for mem, score in rows)
    if expected == 0:
        assert result["context"] == ""
    query = session.execute.call_args.args[0]
    params = query.compile().params
    assert "alice" in params.values()  # Tenant predicate remains in the database query.
    assert 15 in params.values()  # Wider candidate pool for default limit=5.


def test_cutoff_configurable_and_inclusive():
    result, _, _ = run([0.6, 0.59], cutoff=0.6)
    assert result["count"] == 1
    result, _, _ = run([0.6, 0.59], cutoff=0.59)
    assert result["count"] == 2


def test_limit_is_maximum_and_search_alias_filters():
    result, _, _ = run([0.95, 0.9, 0.85, 0.8], limit=2)
    assert result["count"] == 2
    result, _, _ = run([0.78, 0.4808], alias=True)
    assert len(result) == 1
