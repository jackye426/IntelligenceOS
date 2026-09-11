"""Comment theme vocabularies, selected per account.

The DocMap vocabulary is an endometriosis keyword list (`pouch_anatomy_question`,
`imaging_mri`, `advocacy_what_to_ask`). Run against another clinician's audience
it labels nearly everything `other_uncategorized`, so "audience demand" evidence
comes back empty while looking populated.

The generic vocabulary is specialty-neutral: it classifies what a comment *does*
rather than what condition it mentions.
"""

from __future__ import annotations

import re
from typing import Any

from marketing_pipeline import config

DOCMAP_THEME_PATTERNS: list[tuple[str, list[str]]] = [
    ("advocacy_what_to_ask", [r"\b360\b", r"ask for", r"surgeon", r"refused", r"say no", r"check my"]),
    ("post_op_experience", [r"after surgery", r"months ago", r"worse", r"laparoscopy", r"had mine"]),
    ("imaging_mri", [r"\bmri\b", r"scan", r"pick up", r"imaging"]),
    (
        "system_frustration",
        [r"degree in medicine", r"myself\b", r"going in circles", r"not fair", r"ridiculous"],
    ),
    ("humor_reaction", [r"😂|😳|lol|haha|who\?"]),
    ("pouch_anatomy_question", [r"pouch of", r"douglas", r"what is"]),
    ("validation_gratitude", [r"thank", r"needed this", r"so helpful", r"wish i knew"]),
    ("personal_story", [r"\bi\b.*\b(my|me|i'm|i am)\b", r"when i", r"i had"]),
    ("general_question", [r"\?", r"can someone", r"why is", r"what if"]),
]

GENERIC_THEME_PATTERNS: list[tuple[str, list[str]]] = [
    (
        "asks_next_step",
        [
            r"where (can|do) i",
            r"how (do|can) i (get|find|start|book)",
            r"link\b",
            r"which (book|episode|video)",
            r"do you have",
            r"is there a",
            r"sign up",
            r"appointment|consult|booking",
        ],
    ),
    (
        "question",
        [r"\?", r"^(what|why|how|when|where|which|can|could|would|should|is|are|does|do)\b", r"anyone know"],
    ),
    (
        "objection_disagreement",
        [
            r"not true",
            r"disagree",
            r"wrong\b",
            r"nonsense",
            r"\bbut\b.*\b(actually|isn't|doesn't)\b",
            r"prove it",
            r"source\?",
        ],
    ),
    (
        "distress_frustration",
        [r"worse", r"refused", r"terrified", r"scared", r"angry", r"frustrat", r"unfair", r"😭|💔"],
    ),
    ("personal_story", [r"\b(i|my|me|i'm|i am|i've|i had)\b", r"when i", r"my (mum|mom|dad|wife|husband|son|daughter)"]),
    ("gratitude_validation", [r"thank", r"needed (this|to hear)", r"so helpful", r"god bless", r"love this"]),
    ("praise_creator", [r"you are|you're (amazing|the best|a legend)", r"respect", r"fan of yours"]),
    ("humor_reaction", [r"😂|🤣|lol|haha|lmao"]),
    ("request_more_content", [r"more of (this|these)", r"part \d", r"please (do|make|cover)", r"video on"]),
]

QUESTION_THEMES_BY_VOCAB = {
    "docmap-endo": {"general_question", "advocacy_what_to_ask", "pouch_anatomy_question"},
    "generic": {"question", "asks_next_step"},
}
OBJECTION_THEMES_BY_VOCAB = {
    "docmap-endo": {"system_frustration", "imaging_mri"},
    "generic": {"objection_disagreement", "distress_frustration"},
}

VOCABULARIES: dict[str, list[tuple[str, list[str]]]] = {
    "docmap-endo": DOCMAP_THEME_PATTERNS,
    "generic": GENERIC_THEME_PATTERNS,
}
DEFAULT_VOCAB = "docmap-endo"
PEER_VOCAB = "generic"


def resolve_vocabulary(name: str | None = None) -> tuple[str, list[tuple[str, list[str]]]]:
    """Peer accounts get the generic vocabulary unless told otherwise."""
    vocab = name or (PEER_VOCAB if config.is_peer_account() else DEFAULT_VOCAB)
    if vocab not in VOCABULARIES:
        raise ValueError(f"Unknown comment vocabulary '{vocab}'. Known: {sorted(VOCABULARIES)}")
    return vocab, VOCABULARIES[vocab]


def label_themes(text: str, *, vocabulary: str | None = None) -> list[str]:
    _, patterns = resolve_vocabulary(vocabulary)
    t = text.lower()
    hits: list[str] = []
    for name, pats in patterns:
        for pat in pats:
            if re.search(pat, t, re.I):
                hits.append(name)
                break
    if not hits:
        hits.append("other_uncategorized")
    return hits


def question_themes(vocabulary: str | None = None) -> set[str]:
    vocab, _ = resolve_vocabulary(vocabulary)
    key = "generic" if vocab == "generic" else "docmap-endo"
    return QUESTION_THEMES_BY_VOCAB[key]


def objection_themes(vocabulary: str | None = None) -> set[str]:
    vocab, _ = resolve_vocabulary(vocabulary)
    key = "generic" if vocab == "generic" else "docmap-endo"
    return OBJECTION_THEMES_BY_VOCAB[key]


def coverage(labels: list[list[str]]) -> dict[str, Any]:
    """Share of comments that landed anywhere but the fallback bucket.

    A low value means the vocabulary does not fit this audience, which is the
    failure the DocMap regex would produce silently on a peer library.
    """
    total = len(labels)
    uncategorized = sum(1 for ls in labels if ls == ["other_uncategorized"])
    return {
        "comments": total,
        "uncategorized": uncategorized,
        "labelled_share": round((total - uncategorized) / total, 3) if total else None,
    }
