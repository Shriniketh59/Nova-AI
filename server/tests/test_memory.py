import pytest
import respx
from httpx import Response

from conftest import requires_db
from app.core.config import DEFAULT_USER_ID


@requires_db
@pytest.mark.asyncio
async def test_extracts_a_stated_preference_and_recalls_it_for_a_related_later_query(app_client):
    from app.agents.memory_agent import memory_agent

    with respx.mock(assert_all_called=False) as mock:
        mock.post(url__regex=r".*/api/embeddings").mock(return_value=Response(200, json={"embedding": [0.5] * 384}))

        await memory_agent.extract_memory(DEFAULT_USER_ID, None, "Remember my name is Shrini")
        memories = await memory_agent.get_relevant_memories(None, "what is my name?")

    assert any("Shrini" in m for m in memories)


@requires_db
@pytest.mark.asyncio
async def test_does_not_store_memory_for_messages_without_a_trigger(app_client):
    from app.agents.memory_agent import memory_agent

    with respx.mock(assert_all_called=False) as mock:
        mock.post(url__regex=r".*/api/embeddings").mock(return_value=Response(200, json={"embedding": [0.5] * 384}))

        before = await memory_agent.get_relevant_memories(None, "name")
        await memory_agent.extract_memory(DEFAULT_USER_ID, None, "what time is it")
        after = await memory_agent.get_relevant_memories(None, "name")

    assert len(after) == len(before)


@requires_db
@pytest.mark.asyncio
async def test_supersedes_old_memory_when_updated(app_client):
    """When a user updates a fact (e.g. name), the old memory must be superseded and not returned."""
    from app.agents.memory_agent import memory_agent

    with respx.mock(assert_all_called=False) as mock:
        mock.post(url__regex=r".*/api/embeddings").mock(return_value=Response(200, json={"embedding": [0.5] * 384}))

        # First state: name is Alice
        await memory_agent.extract_memory(DEFAULT_USER_ID, None, "Remember my name is Alice")
        mem1 = await memory_agent.get_relevant_memories(None, "what is my name?")
        assert any("Alice" in m for m in mem1)

        # Later state: user updates name to Bob
        await memory_agent.extract_memory(DEFAULT_USER_ID, None, "Remember my name is Bob")
        mem2 = await memory_agent.get_relevant_memories(None, "what is my name?")

        # Bob must be present, Alice must NOT be returned as active memory
        assert any("Bob" in m for m in mem2)
        assert not any("Alice" in m for m in mem2)


@requires_db
@pytest.mark.asyncio
async def test_spelling_mistake_tolerance_in_memory_lookup(app_client):
    """Typo in query should still retrieve stored memories."""
    from app.agents.memory_agent import memory_agent

    with respx.mock(assert_all_called=False) as mock:
        mock.post(url__regex=r".*/api/embeddings").mock(return_value=Response(200, json={"embedding": [0.5] * 384}))

        await memory_agent.extract_memory(DEFAULT_USER_ID, None, "Remember my preference is Python")
        # Query with spelling mistakes: 'wht is my prefere'
        memories = await memory_agent.get_relevant_memories(None, "wht is my prefere")
        assert any("Python" in m for m in memories)
