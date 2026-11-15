from __future__ import annotations

import hashlib
import re

# Part of every fingerprint input: changing normalize() means bumping this, so
# existing issues are never silently merged with or split from new ones.
NORMALIZATION_VERSION = 1

_STEPS = (
    (
        re.compile(
            r"\d{4}-\d\d-\d\d(?:[t ]\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:z|[+-]\d\d:?\d\d)?)?"
        ),
        "",
    ),
    (re.compile(r"\b\d\d:\d\d(?::\d\d(?:\.\d+)?)?\b"), ""),
    (re.compile(r"(https?://[^\s?#]*)\?[^\s#]*"), r"\1"),
    (re.compile(r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b"), ""),
    (re.compile(r"\b[0-9a-f]{8,}\b"), ""),
    (re.compile(r"\d{4,}"), ""),
    (re.compile(r"\s+"), " "),
)


def normalize(observed: str) -> str:
    text = observed.lower()
    for pattern, replacement in _STEPS:
        text = pattern.sub(replacement, text)
    return text.strip()[:200]


def fingerprint(scenario: str, failure_class: str, index: int, observed: str) -> str:
    """Identity of a defect: service/scenario, failure class, failed expectation
    index and normalized observed text. The commit is an occurrence, never part of it."""
    if not scenario or not failure_class or index < 0:
        raise ValueError(
            "scenario, failure class and a non-negative index are required"
        )
    parts = (
        str(NORMALIZATION_VERSION),
        scenario,
        failure_class,
        str(index),
        normalize(observed),
    )
    if any("\0" in p for p in parts):
        raise ValueError("fingerprint inputs must not contain NUL")
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()
