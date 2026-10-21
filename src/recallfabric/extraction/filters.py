import re

from recallfabric.core.config import Settings

_AI_PHRASES = [
    "i don't know",
    "i do not know",
    "i'm not sure",
    "i am not sure",
    "not a real person",
    "i cannot",
    "i can't",
    "as an ai",
    "as a language model",
    "i have no information",
    "i have no memory",
    "i don't have",
    "i do not have",
    "please provide",
    "could you clarify",
    "i'm unable",
    "i am unable",
    "i apologize",
    "i am sorry",
    "let me know",
    "feel free",
    "how can i help",
    "how may i assist",
    "i am an ai",
]

_CONVERSATIONAL_PATTERNS = [
    "user says",
    "user said",
    "user asked",
    "user is asking",
    "user is greeting",
    "user asks",
    "user is inquiring",
    "user said hello",
    "user greeted",
    "user wants to know",
]

_GREETINGS = [
    "hello",
    "hi",
    "hey",
    "good morning",
    "good evening",
    "good afternoon",
    "welcome",
    "how are you",
    "how's it going",
    "how are things",
    "nice to meet you",
]

_TEMPORARY_PATTERNS = [
    "right now",
    "at the moment",
    "at this moment",
    "currently",
    "for now",
    "in a meeting",
    "on a call",
    "on the phone",
    "in traffic",
    "is busy",
    "is hungry",
    "feels hungry",
    "feeling hungry",
    "is thirsty",
    "feels thirsty",
    "feeling thirsty",
    "is tired",
    "feels tired",
    "feeling tired",
    "is sleepy",
    "feels sleepy",
    "feeling sleepy",
    "is exhausted",
    "feeling sick",
    "has a headache",
    "has a cold",
    "eating lunch",
    "having lunch",
    "eating dinner",
    "having dinner",
    "eating breakfast",
    "having breakfast",
    "today",
    "tonight",
    "this morning",
    "this afternoon",
    "this evening",
    "yesterday",
    "tomorrow",
    "is driving",
    "is commuting",
    "is heading home",
]

_QUESTION_RE = re.compile(r"\?\s*$")


def filter_candidate(
    content: str,
    importance: float,
    confidence: float,
    settings: Settings,
) -> tuple[bool, str | None]:
    stripped = content.strip().strip('"').strip("'").strip()
    if not stripped:
        return False, "Content cannot be empty"

    words = stripped.split()
    if len(words) < 2:
        return False, "Content too short (fewer than 2 words)"

    if importance < settings.extraction_min_importance:
        min_imp = settings.extraction_min_importance
        return False, f"Importance {importance:.2f} is below threshold {min_imp:.2f}"

    if confidence < settings.extraction_min_confidence:
        min_conf = settings.extraction_min_confidence
        return False, f"Confidence {confidence:.2f} is below threshold {min_conf:.2f}"

    lower = stripped.lower()

    if _QUESTION_RE.search(lower) or lower.startswith(
        (
            "is user",
            "does user",
            "can user",
            "will user",
            "what is",
            "who is",
            "where is",
            "how is",
            "why is",
        )
    ):
        return False, "Content is a question"

    for phrase in _AI_PHRASES:
        if phrase in lower:
            return False, "Content contains assistant or AI boilerplate phrasing"

    for phrase in _CONVERSATIONAL_PATTERNS:
        if phrase in lower:
            return False, "Content is a conversational description"

    for phrase in _GREETINGS:
        if lower == phrase or lower.startswith(f"{phrase} ") or lower.endswith(f" {phrase}"):
            return False, "Content is a greeting or conversational pleasantry"

    for pattern in _TEMPORARY_PATTERNS:
        if re.search(rf"\b{re.escape(pattern)}\b", lower):
            return False, "Content is a temporary or situational statement"

    if not (
        stripped.startswith("User ")
        or stripped.startswith("User's ")
        or stripped.startswith("User’s ")
    ):
        return False, "Fact must be in third person starting with 'User'"

    return True, None


def is_valid_candidate(
    content: str,
    importance: float,
    confidence: float,
    settings: Settings,
) -> bool:
    valid, _ = filter_candidate(content, importance, confidence, settings)
    return valid
