"""
gem_catalog.py - Load and query the 52 wisdom gems.

Loads gems from content/gems/wisdom_gems.json at import time.
Provides lookup by id, category, and filtering for deck management.

Depends on: pydantic, pathlib, json.
Used by: services/gem_service.
"""

from __future__ import annotations

import json
from pathlib import Path
from pydantic import BaseModel, Field


class Gem(BaseModel):
    """A single wisdom gem from the catalog."""
    id: str
    categories: list[str] = Field(min_length=1)
    league: int = Field(ge=1, le=5)
    text: str


def _load_gems() -> list[Gem]:
    path = Path(__file__).parent / "content" / "gems" / "wisdom_gems.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [Gem(**item) for item in data]


ALL_GEMS: list[Gem] = _load_gems()

_BY_ID: dict[str, Gem] = {g.id: g for g in ALL_GEMS}


def get_gem_by_id(gem_id: str) -> Gem | None:
    return _BY_ID.get(gem_id)


def get_gems_for_category(category: str) -> list[Gem]:
    return [g for g in ALL_GEMS if category in g.categories]
