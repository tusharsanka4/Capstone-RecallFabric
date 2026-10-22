"""Smart wrapper for adding automatic memory recall and background extraction to any LLM call."""

from __future__ import annotations

import asyncio
import copy
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from recallfabric_client.client import AsyncRecallFabric, RecallFabric

logger = logging.getLogger("recallfabric_client.wrapper")


def _extract_last_user_query(messages: list[dict[str, str]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return str(m.get("content", ""))
    if messages:
        return str(messages[-1].get("content", ""))
    return ""


def _inject_context(
    messages: list[dict[str, str]],
    context: str,
    context_template: str = "Relevant User Memories:\n{context}\n\n",
) -> list[dict[str, str]]:
    if not context or not context.strip():
        return messages

    augmented = copy.deepcopy(messages)
    formatted_context = context_template.format(context=context.strip())

    if augmented and augmented[0].get("role") == "system":
        orig_system = augmented[0].get("content", "")
        augmented[0]["content"] = f"{formatted_context}{orig_system}"
    else:
        augmented.insert(0, {"role": "system", "content": formatted_context})

    return augmented


def _extract_response_text(resp: Any) -> str:
    if hasattr(resp, "content") and isinstance(resp.content, str):
        return resp.content
    if hasattr(resp, "text") and isinstance(resp.text, str):
        return resp.text
    if isinstance(resp, str):
        return resp
    return str(resp)


def with_memory(
    llm_call: Callable[[list[dict[str, str]]], Any],
    client: RecallFabric,
    user_id: str | None = None,
    *,
    extract_after: bool = True,
    limit: int = 5,
    min_similarity: float | None = None,
    context_template: str = "Relevant User Memories:\n{context}\n\n",
) -> Callable[[list[dict[str, str]]], Any]:
    """Wrap any synchronous LLM function with automatic memory recall and background extraction.

    Failures in background extraction never affect or break the main LLM call.
    """

    def wrapped(messages: list[dict[str, str]], **kwargs: Any) -> Any:
        user_query = _extract_last_user_query(messages)
        augmented_messages = messages

        # 1. Recall relevant memories
        if user_query:
            try:
                recall_res = client.recall(
                    query=user_query,
                    limit=limit,
                    min_similarity=min_similarity,
                    user_id=user_id,
                )
                if recall_res.context:
                    augmented_messages = _inject_context(
                        messages, recall_res.context, context_template
                    )
            except Exception as exc:
                logger.warning("Memory recall failed; proceeding without memories: %s", exc)

        # 2. Call the LLM
        response = llm_call(augmented_messages, **kwargs)

        # 3. Extract new memories in background thread (non-blocking, safe)
        if extract_after and user_query:
            resp_text = _extract_response_text(response)
            exchange = f"User: {user_query}\nAssistant: {resp_text}"

            def _bg_extract() -> None:
                try:
                    client.remember(
                        text=exchange,
                        extract=True,
                        user_id=user_id,
                        source="with_memory",
                    )
                except Exception as bg_exc:
                    logger.debug("Background extraction failed silently: %s", bg_exc)

            bg_thread = threading.Thread(target=_bg_extract, daemon=True)
            bg_thread.start()

        return response

    return wrapped


def async_with_memory(
    llm_call: Callable[[list[dict[str, str]]], Awaitable[Any]],
    client: AsyncRecallFabric,
    user_id: str | None = None,
    *,
    extract_after: bool = True,
    limit: int = 5,
    min_similarity: float | None = None,
    context_template: str = "Relevant User Memories:\n{context}\n\n",
) -> Callable[[list[dict[str, str]]], Awaitable[Any]]:
    """Wrap any asynchronous LLM function with automatic memory recall and background extraction."""

    async def wrapped(messages: list[dict[str, str]], **kwargs: Any) -> Any:
        user_query = _extract_last_user_query(messages)
        augmented_messages = messages

        # 1. Recall relevant memories
        if user_query:
            try:
                recall_res = await client.recall(
                    query=user_query,
                    limit=limit,
                    min_similarity=min_similarity,
                    user_id=user_id,
                )
                if recall_res.context:
                    augmented_messages = _inject_context(
                        messages, recall_res.context, context_template
                    )
            except Exception as exc:
                logger.warning("Async memory recall failed; proceeding without memories: %s", exc)

        # 2. Call the LLM
        response = await llm_call(augmented_messages, **kwargs)

        # 3. Background extraction task
        if extract_after and user_query:
            resp_text = _extract_response_text(response)
            exchange = f"User: {user_query}\nAssistant: {resp_text}"

            async def _bg_extract() -> None:
                try:
                    await client.remember(
                        text=exchange,
                        extract=True,
                        user_id=user_id,
                        source="async_with_memory",
                    )
                except Exception as bg_exc:
                    logger.debug("Background async extraction failed silently: %s", bg_exc)

            asyncio.create_task(_bg_extract())

        return response

    return wrapped
