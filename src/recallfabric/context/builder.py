from collections.abc import Sequence
from typing import Any

DEFAULT_CHAT_SYSTEM_PROMPT = (
    "You are RecallFabric, a helpful, friendly AI assistant with persistent memory. "
    "The user is a human speaking with you. You are the AI.\n\n"
    "Rules:\n"
    "- When the user tells you something (like a preference, hobby, or greeting), "
    "respond conversationally, warmly, and relevantly to what they just said.\n"
    "- When the user asks what you remember about them or asks questions about their "
    "background/details, answer directly using the Memory Notes below.\n"
    "- Address the user as 'You' and yourself as 'I'. "
    "Keep responses concise, direct, and natural without repetitive phrases."
)


def format_memory_line(memory: Any) -> str:
    m_type = getattr(memory, "type", "fact")
    if hasattr(m_type, "value"):
        m_type = m_type.value
    content = getattr(memory, "content", "")
    return f"- [{m_type}] {content}"


def select_memories_for_context(
    memories: Sequence[Any],
    max_chars: int,
) -> list[Any]:
    if max_chars <= 0:
        return []

    sorted_mems = sorted(
        memories,
        key=lambda m: getattr(m, "score", 0.0),
        reverse=True,
    )
    selected = list(sorted_mems)
    while selected:
        lines = [format_memory_line(m) for m in selected]
        text = "\n".join(lines)
        if len(text) <= max_chars:
            return selected
        selected.pop()
    return []


def build_context(
    memories: Sequence[Any],
    max_chars: int,
) -> str:
    selected = select_memories_for_context(memories, max_chars)
    return "\n".join(format_memory_line(m) for m in selected)


def build_context_block(
    memories: Sequence[Any],
    max_chars: int,
) -> tuple[str, list[Any]]:
    selected = select_memories_for_context(memories, max_chars)
    text = "\n".join(format_memory_line(m) for m in selected)
    return text, selected


def assemble_system_prompt(system_prompt: str, context: str) -> str:
    if not context.strip():
        return system_prompt
    notes_header = "\n\nMemory Notes about the User:\n"
    notes_footer = "\n\nUse these notes when the user asks about their background."
    return f"{system_prompt}{notes_header}{context}{notes_footer}"
