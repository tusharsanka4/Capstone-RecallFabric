"""Memory extraction from unstructured text using AI models."""

import json
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from recallfabric.api.memories import Embedder, Database
from recallfabric.db.models import Memory
from recallfabric.schemas.memory import MemoryCreate, MemoryRead, NonemptyText

router = APIRouter(prefix="/extraction", tags=["extraction"])

client = AsyncOpenAI(
    base_url="http://127.0.0.1:11434/v1",
    api_key="ollama",
)


class MemoryExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: Annotated[NonemptyText, Field(max_length=255)]
    text: NonemptyText
    source: Annotated[NonemptyText, Field(max_length=512)]


class ExtractionResponse(BaseModel):
    extracted: list[MemoryRead]


# ── Quality filters ──────────────────────────────────────────────────────────
_AI_PHRASES = [
    "i don't know", "i do not know", "i'm not sure", "i am not sure",
    "not a real person", "i cannot", "i can't", "as an ai", "as a language model",
    "i have no information", "i have no memory", "i don't have", "i do not have",
    "please provide", "could you clarify", "i'm unable", "i am unable",
    "i apologize", "i am sorry", "let me know", "feel free",
]
_CONVERSATIONAL_PATTERNS = [
    "user says", "user asked", "user is asking", "user is greeting",
    "user asks", "user is inquiring", "user said hello", "how are you",
    "what is the weather", "good morning", "good evening", "how's it going",
]
_QUESTION_RE = re.compile(r"\?\s*$")


def _is_garbage(content: str) -> bool:
    """Return True if this extracted memory should be discarded."""
    lower = content.lower().strip()
    if not lower:
        return True
    if _QUESTION_RE.search(lower):          # reject questions
        return True
    for phrase in _AI_PHRASES:              # reject AI-sounding output
        if phrase in lower:
            return True
    for phrase in _CONVERSATIONAL_PATTERNS: # reject conversational echoes
        if phrase in lower:
            return True
    if len(lower.split()) < 2:              # reject single words
        return True
    return False


# ── Extraction prompt ─────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an expert Memory Extraction Assistant for an AI system.
Extract atomic, declarative facts from the user's message in the third person (starting with 'User').
Extract ONLY clear facts the user explicitly stated. Never guess, infer, or hallucinate.

Rules:
1. Extract atomic facts (e.g. "User's name is Alwin", "User lives in San Francisco", "User works as a software engineer", "User likes chicken").
2. If multiple facts are stated in one sentence, extract each as a separate atomic memory.
3. NEVER extract conversational messages, greetings, pleasantries, or questions (e.g. "Hello", "How are you?", "What can you do?"). Return {"memories": []} for these.
4. Realistic confidence scores (0.60 to 0.95):
   - 0.90 to 0.95: Direct identity, name, occupation, location assertions
   - 0.80 to 0.88: Stated preferences, hobbies, skills, tools
   - 0.65 to 0.75: Secondary or indirect details
5. Realistic importance scores (0.60 to 0.95):
   - 0.85 to 0.95: Core identity, profession, residence
   - 0.65 to 0.80: Preferences, hobbies, skills

Example 1:
Input: "My name is Alwin and I work as a backend engineer in San Francisco."
Output:
{"memories": [
  {"content": "User's name is Alwin", "type": "profile", "importance": 0.95, "confidence": 0.95, "creation_reason": "Direct self-introduction"},
  {"content": "User works as a backend engineer", "type": "profile", "importance": 0.88, "confidence": 0.92, "creation_reason": "Stated job title"},
  {"content": "User is located in San Francisco", "type": "profile", "importance": 0.85, "confidence": 0.90, "creation_reason": "Stated location"}
]}

Example 2:
Input: "I really like spicy ramen and I play acoustic guitar."
Output:
{"memories": [
  {"content": "User likes spicy ramen", "type": "preference", "importance": 0.72, "confidence": 0.85, "creation_reason": "Stated food preference"},
  {"content": "User plays acoustic guitar", "type": "skill", "importance": 0.70, "confidence": 0.85, "creation_reason": "Stated musical hobby"}
]}

Example 3:
Input: "Hello! How are you doing today?"
Output:
{"memories": []}

Return ONLY raw JSON."""


@router.post("", response_model=ExtractionResponse, status_code=201)
async def extract_memories(
    payload: MemoryExtractRequest,
    session: Database,
    embedder: Embedder,
):
    try:
        user_message = (
            'Extract all atomic facts from this user message:\n'
            f'"""\n{payload.text}\n"""'
        )
        response = await client.chat.completions.create(
            model="qwen2.5:0.5b",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )

        result_content = response.choices[0].message.content
        if not result_content:
            return ExtractionResponse(extracted=[])

        data = json.loads(result_content)
        memories_data = data.get("memories", [])

        created_memories = []
        for item in memories_data:
            content = str(item.get("content", "")).strip().strip('"').strip("'").strip()
            importance = float(item.get("importance", 0.0))
            confidence = float(item.get("confidence", 0.0))

            # Quality gates
            if not content:
                continue
            if importance < 0.6:        # drop low-importance facts
                continue
            if confidence < 0.5:        # drop uncertain facts
                continue
            if _is_garbage(content):    # drop AI-sounding / question content / single words
                continue

            reason = str(item.get("creation_reason") or "").strip() or "Explicitly stated by user"
            mem_type = str(item.get("type", "fact")).lower().strip()
            if mem_type not in {"preference", "goal", "skill", "profile", "fact", "other"}:
                mem_type = "fact"

            mem_create = MemoryCreate(
                user_id=payload.user_id,
                content=content,
                type=mem_type,
                importance=importance,
                confidence=confidence,
                source=payload.source,
                creation_reason=reason,
            )

            embedding = embedder.embed(mem_create.content)

            with session.begin():
                values = mem_create.model_dump(exclude={"metadata"})
                memory = Memory(
                    **values,
                    attributes=mem_create.metadata,
                    embedding=embedding.vector,
                    embedding_model=embedding.model,
                    embedding_dimensions=embedding.dimensions,
                )
                session.add(memory)
                session.flush()
                created_memories.append(MemoryRead.model_validate(memory))

        return ExtractionResponse(extracted=created_memories)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")
