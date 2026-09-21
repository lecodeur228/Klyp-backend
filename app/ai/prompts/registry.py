"""Versioned prompt registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: str
    system: str
    user_template: str
    metadata: dict[str, Any]


_REGISTRY: dict[str, PromptTemplate] = {
    "summarize": PromptTemplate(
        name="summarize",
        version="1.0.0",
        system="You are a concise assistant that summarizes text clearly.",
        user_template="Summarize the following text:\n\n{content}",
        metadata={"tags": ["summary"], "owner": "starter"},
    ),
    "extract_json": PromptTemplate(
        name="extract_json",
        version="1.0.0",
        system="You extract structured data and reply with JSON only.",
        user_template="Extract key facts from:\n\n{content}",
        metadata={"tags": ["structured"], "owner": "starter"},
    ),
}


def get_prompt(name: str) -> PromptTemplate:
    if name not in _REGISTRY:
        raise KeyError(name)
    return _REGISTRY[name]


def render_prompt(name: str, **kwargs: str) -> tuple[str, str, str]:
    """Return (system, user, version)."""
    template = get_prompt(name)
    return template.system, template.user_template.format(**kwargs), template.version


def list_prompts() -> list[PromptTemplate]:
    return list(_REGISTRY.values())
