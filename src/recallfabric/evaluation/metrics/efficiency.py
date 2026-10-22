"""Memory efficiency metrics: memory counts, duplicate rate, and distractor rejection."""


def calculate_memory_efficiency(
    memories_per_conv: list[int],
    duplicate_counts: list[int],
    distractors_stored: list[int],
    total_distractors: list[int],
) -> dict[str, float]:
    """Compute summary memory efficiency metrics."""
    if not memories_per_conv:
        return {
            "avg_memories_per_conv": 0.0,
            "duplicate_rate": 0.0,
            "distractor_rejection_rate": 0.0,
        }

    total_memories = sum(memories_per_conv)
    avg_memories = total_memories / float(len(memories_per_conv))

    total_dupes = sum(duplicate_counts)
    duplicate_rate = (total_dupes / float(total_memories)) if total_memories > 0 else 0.0

    sum_distractors = sum(total_distractors)
    sum_distractors_stored = sum(distractors_stored)
    if sum_distractors > 0:
        distractor_rejection = max(0.0, 1.0 - (sum_distractors_stored / float(sum_distractors)))
    else:
        distractor_rejection = 1.0

    return {
        "avg_memories_per_conv": round(avg_memories, 2),
        "duplicate_rate": round(duplicate_rate, 4),
        "distractor_rejection_rate": round(distractor_rejection, 4),
    }
