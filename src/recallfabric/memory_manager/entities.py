"""Conservative project labels and tenant-local, read-time legacy resolution."""

import re
import unicodedata

from sqlalchemy import select

from recallfabric.db.models import Memory
from recallfabric.security.encryption import decrypt_content

_EXPLICIT = re.compile(r"\bproject\s+([^\W_][\w-]{0,63})", re.IGNORECASE)
_GENERIC = set(
    "a an the is are was were uses use has have am do does did can should will "
    "would could that this my our your we i you and or for in on at of to with "
    "decisions context memory memories stack settings project projects details "
    "management planning work team name requirements documentation "
    "backend frontend database".split()
)


def normalize_project(name):
    text = unicodedata.normalize("NFKC", name).strip()
    return re.sub(r"^project\s+", "", text, flags=re.IGNORECASE).casefold()


def explicit_projects(text):
    found = {}
    for match in _EXPLICIT.finditer(text):
        name = match.group(1)
        key = normalize_project(name)
        following = re.match(r"\s+([^\W_][\w-]*)", text[match.end() :])
        if (
            following
            and following.group(1)[0].isupper()
            and following.group(1).casefold() not in _GENERIC
        ):
            # Do not truncate an unsupported multiword name into another project's key.
            continue
        if key not in _GENERIC:
            found[key] = {"type": "project", "key": key, "name": "Project " + name}
    return list(found.values())


def resolve_projects(text, known):
    found = {e["key"]: e for e in explicit_projects(text)}
    normalized = unicodedata.normalize("NFKC", text).casefold()
    for key, entity in known.items():
        if re.search(r"(?<![\w-])" + re.escape(key) + r"(?![\w-])", normalized):
            found.setdefault(key, entity)
    return list(found.values())


def with_project_metadata(content, metadata=None, inherited=None):
    result = dict(metadata or {})
    previous = result.get("project_entities") or (inherited or {}).get("project_entities")
    previous = previous if isinstance(previous, list) else []
    known = {
        e["key"]: e
        for e in previous
        if isinstance(e, dict)
        and e.get("type") == "project"
        and isinstance(e.get("key"), str)
        and e["key"] not in _GENERIC
    }
    entities = resolve_projects(content, known)
    if not entities and inherited:
        entities = list(known.values())
    # Explicit renames replace labels; ID-bound corrections may inherit their project.
    if entities:
        result["project_entities"] = entities
    else:
        result.pop("project_entities", None)
    return result


def project_scope(statement, session, user_id, query, encryption_key=None, status="active"):
    """Constrain before vector LIMIT, using active rows from this tenant only.

    No backfill is performed. Bare aliases require an explicit tenant-local anchor.
    """
    rows = session.execute(
        select(Memory.id, Memory.content, Memory.attributes).where(
            Memory.user_id == user_id, Memory.status == status
        )
    ).all()
    decoded = []
    known = {}
    for row in rows:
        if len(row) != 3 or not isinstance(row[1], str):
            continue
        mid, content, metadata = row
        text = decrypt_content(content, encryption_key)
        entities = with_project_metadata(text, metadata, inherited=metadata).get(
            "project_entities", []
        )
        known.update({e["key"]: e for e in entities})
        decoded.append((mid, text, entities))
    entities_by_id = {}
    for mid, text, carried in decoded:
        resolved = {e["key"]: e for e in carried}
        resolved.update({e["key"]: e for e in resolve_projects(text, known)})
        entities_by_id[mid] = list(resolved.values())
    requested = {e["key"] for e in resolve_projects(query, known)}
    if requested:
        ids = [
            mid
            for mid, entities in entities_by_id.items()
            if {e["key"] for e in entities} & requested
        ]
        statement = statement.where(Memory.id.in_(ids))
    return statement, entities_by_id
