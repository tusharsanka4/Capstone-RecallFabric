from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from recallfabric.core.config import Settings
from recallfabric.db.models import Memory
from recallfabric.embeddings.service import EmbeddingResult
from recallfabric.mcp_server import RecallFabricTools
from recallfabric.memory_manager.entities import (
    explicit_projects,
    normalize_project,
    project_scope,
    with_project_metadata,
)


@pytest.mark.parametrize("name", ["Project Nova", "Nova", "project nova", "PROJECT NOVA"])
def test_normalized_project_identity(name):
    assert normalize_project(name) == "nova"


def test_conservative_labels_preserve_other_metadata():
    tagged = with_project_metadata("Project Nova uses React.", {"decision_slot": "frontend"})
    assert tagged["project_entities"] == [
        {"type": "project", "key": "nova", "name": "Project Nova"}
    ]
    assert tagged["decision_slot"] == "frontend"
    assert not explicit_projects("My notebook is teal. I prefer dark IDE themes.")
    assert not explicit_projects("The project uses PostgreSQL.")
    assert "project_entities" not in with_project_metadata("My notebook is teal.", tagged)
    assert with_project_metadata("No project is named.", {"project_entities": None}) == {}
    renamed = with_project_metadata("Project Atlas uses React.", tagged)
    assert [e["key"] for e in renamed["project_entities"]] == ["atlas"]


class Embedder:
    model_id = "entity-test"
    dimensions = 3

    def embed(self, text, kind="passage"):
        return EmbeddingResult(model=self.model_id, dimensions=3, vector=[1.0, 0.0, 0.0])


def memory(content, score=0.85, status="active", owner="alice"):
    return Memory(
        id=uuid4(),
        user_id=owner,
        content=content,
        status=status,
        version=1,
        type="fact",
        source="test",
        importance=0.5,
        confidence=1.0,
        access_count=0,
        created_at=datetime.now(UTC),
        attributes={},
    ), score


def recall(query, rows):
    session = MagicMock()

    def execute(statement):
        params = statement.compile().params
        assert "alice" in params.values()
        own = [(m, s) for m, s in rows if m.user_id == "alice" and m.status == "active"]
        result = MagicMock()
        if len(statement.selected_columns) == 3:
            result.all.return_value = [(m.id, m.content, m.attributes) for m, s in own]
        else:
            ids = next((v for k, v in params.items() if k.startswith("id_")), None)
            result.all.return_value = [(m, s) for m, s in own if ids is None or m.id in ids]
        return result

    session.execute.side_effect = execute
    tools = RecallFabricTools(Settings(_env_file=None, auth_enabled=False), embedder=Embedder())
    return tools.recall(query, limit=10, session=session, user_id="alice")


@pytest.mark.parametrize(
    "query,expected",
    [
        ("What do you know about Project Nova?", {"nova"}),
        ("Continue Nova.", {"nova"}),
        ("What stack are we using for Atlas?", {"atlas"}),
        ("Compare Atlas and Nova.", {"nova", "atlas"}),
        ("What projects am I working on?", {"nova", "atlas"}),
    ],
)
def test_named_projects_do_not_compete(query, expected):
    rows = [
        memory("Project Nova is a study platform."),
        memory("Nova uses React."),
        memory("Project Atlas uses Next.js."),
        memory("Atlas uses PostgreSQL."),
        memory("Project Nova uses FastAPI.", owner="bob"),
    ]
    result = recall(query, rows)
    assert {e["key"] for m in result["memories"] for e in m["entities"]} == expected
    assert all(m["id"] != str(rows[-1][0].id) for m in result["memories"])
    assert result["count"] == 2 * len(expected)


def test_current_state_relevance_and_general_memories():
    rows = [
        memory("Project Mercury uses MongoDB.", status="superseded"),
        memory("Project Mercury uses PostgreSQL."),
        memory("Project Nova uses MongoDB."),
        memory("Project Mercury has a logo.", score=0.45),
    ]
    result = recall("What database does Mercury use?", rows)
    assert [m["content"] for m in result["memories"]] == ["Project Mercury uses PostgreSQL."]
    for text, query in [
        ("My notebook is teal.", "What color is my notebook?"),
        ("I prefer Python for backend work.", "What backend language do I prefer?"),
    ]:
        result = recall(query, [memory(text)])
        assert result["count"] == 1 and result["memories"][0]["entities"] == []


def test_unknown_explicit_project_does_not_fall_back():
    assert recall("Tell me about Project Vega.", [memory("Project Nova uses React.")])["count"] == 0


def test_project_filter_applies_before_limit_and_reads_active_tenant_only():
    session = MagicMock()
    mid = uuid4()
    session.execute.return_value.all.return_value = [(mid, "Project Nova uses React.", {})]
    statement = select(Memory).where(Memory.user_id == "alice", Memory.status == "active").limit(1)
    scoped, _ = project_scope(statement, session, "alice", "Nova")
    assert scoped.compile().params["id_1"] == [mid]
    sql = str(scoped)
    assert sql.index("memories.id IN") < sql.index("LIMIT")
    catalog = session.execute.call_args.args[0].compile().params
    assert "alice" in catalog.values() and "active" in catalog.values()


def test_identified_revision_can_retain_project_without_repeating_name():
    prior = with_project_metadata("Project Mercury uses MongoDB.")
    updated = with_project_metadata("We use PostgreSQL now.", inherited=prior)
    assert updated["project_entities"][0]["key"] == "mercury"
    renamed = with_project_metadata("Project Vega uses PostgreSQL.", inherited=prior)
    assert [e["key"] for e in renamed["project_entities"]] == ["vega"]


def test_similar_names_stay_separate_and_no_cross_tenant_aliases():
    rows = [
        memory("Project Nova uses React."),
        memory("Project Novaa uses React."),
        memory("Project PrivateName uses React.", owner="bob"),
    ]
    assert recall("Nova", rows)["count"] == 1
    # A name known only to Bob must not become Alice's resolved project.
    session = MagicMock()
    session.execute.return_value.all.return_value = []
    original = select(Memory).where(Memory.user_id == "alice")
    scoped, _ = project_scope(original, session, "alice", "Continue PrivateName")
    assert "id_1" not in scoped.compile().params


def test_current_id_bound_correction_is_recalled_by_inherited_project():
    mem, score = memory("We use PostgreSQL now.")
    mem.attributes = with_project_metadata("Project Mercury uses MongoDB.")
    result = recall("What database does Mercury use?", [(mem, score)])
    assert result["count"] == 1
    assert result["memories"][0]["entities"][0]["key"] == "mercury"


def test_generic_project_phrases_and_multiword_names_are_not_invented():
    assert not explicit_projects("Project management is important.")
    assert not explicit_projects("Project Evening Star uses React.")
    assert not explicit_projects("Project Evening Moon uses React.")
    assert explicit_projects("PROJECT NOVA USES REACT.")[0]["key"] == "nova"
