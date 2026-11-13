"""Dataset loading and validation for RecallFabric evaluation."""

import json
from pathlib import Path

from recallfabric.evaluation.models import Conversation


def load_dataset(dataset_path: str | Path, limit: int | None = None) -> list[Conversation]:
    file_path = Path(dataset_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Dataset file not found at: {file_path}")

    conversations: list[Conversation] = []
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if not line_str:
                continue
            data = json.loads(line_str)
            conv = Conversation.model_validate(data)
            conversations.append(conv)
            if limit is not None and len(conversations) >= limit:
                break

    return conversations
