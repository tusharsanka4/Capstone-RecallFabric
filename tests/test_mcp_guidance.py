import pytest
from test_mcp_contracts import connected


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_continuity_guidance_and_canonical_tool_selection():
    async with connected() as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert len(tools) == 11  # Existing clients retain their compatibility aliases.
        recall = tools["recall"].description
        assert "before asking the user to repeat context" in recall
        for trigger in ["continue/resume", "earlier decisions", "switching clients"]:
            assert trigger in recall
        assert "general knowledge" in recall and "self-contained" in recall
        for alias, canonical in [
            ("search_memory", "recall"),
            ("store_memory", "remember"),
            ("delete_memory", "forget"),
        ]:
            assert "Prefer " + canonical in tools[alias].description
        assert "only after user acceptance" in tools["remember"].description
        assert "temporary" in tools["remember"].description
        assert "expected_version" in tools["update_memory"].description
        assert "user_id" not in tools["recall"].input_schema["properties"]
        assert tools["forget"].annotations.destructive_hint is True
        assert tools["get_profile"].annotations.read_only_hint is True


@pytest.mark.anyio
async def test_prompt_examples_and_memory_safety():
    async with connected() as client:
        result = await client.get_prompt("use_memory")
        text = " ".join(m.content.text for m in result.messages)
        for phrase in [
            "Let's continue Orion",
            "What stack did we choose",
            "binary search",
            "merge sort",
            "not on every message",
            "unquestionable",
            "current user statements",
            "irrelevant memories",
            "similarity scores",
            "Do not narrate",
            "user acceptance",
            "SQLite",
            "expected_version",
        ]:
            assert phrase in text
        resources = (await client.list_resources()).resources
        assert str(resources[0].uri) == "memory://profile"
        assert "recall for a specific" in resources[0].description
