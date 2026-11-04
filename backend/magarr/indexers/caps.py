"""Parse the ``t=caps`` capabilities document."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from xml.etree.ElementTree import Element

from magarr.indexers.xml import local_name


@dataclass
class Category:
    id: int
    name: str
    subcategories: list[Category] = field(default_factory=list)


@dataclass
class Caps:
    search_available: bool = True
    search_params: list[str] = field(default_factory=lambda: ["q"])
    limit_max: int = 100
    limit_default: int = 100
    categories: list[Category] = field(default_factory=list)

    def category_ids(self) -> set[int]:
        ids: set[int] = set()
        for category in self.categories:
            ids.add(category.id)
            ids.update(sub.id for sub in category.subcategories)
        return ids

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> Caps:
        if not data:
            return cls()
        categories = [
            Category(c["id"], c["name"], [Category(s["id"], s["name"]) for s in c["subcategories"]])
            for c in data.get("categories", [])
        ]
        return cls(
            search_available=data.get("search_available", True),
            search_params=data.get("search_params", ["q"]),
            limit_max=data.get("limit_max", 100),
            limit_default=data.get("limit_default", 100),
            categories=categories,
        )


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def parse_caps(root: Element) -> Caps:
    caps = Caps()
    for child in root:
        name = local_name(child.tag)
        if name == "limits":
            caps.limit_max = _int(child.get("max"), caps.limit_max)
            caps.limit_default = _int(child.get("default"), min(caps.limit_max, 100))
        elif name == "searching":
            for mode in child:
                if local_name(mode.tag) == "search":
                    caps.search_available = mode.get("available", "yes").lower() == "yes"
                    params = mode.get("supportedParams") or mode.get("supportedparams") or "q"
                    caps.search_params = [p.strip() for p in params.split(",") if p.strip()]
        elif name == "categories":
            for cat in child:
                if local_name(cat.tag) != "category":
                    continue
                category = Category(_int(cat.get("id"), 0), cat.get("name", ""))
                category.subcategories = [
                    Category(_int(sub.get("id"), 0), sub.get("name", ""))
                    for sub in cat
                    if local_name(sub.tag) == "subcat"
                ]
                caps.categories.append(category)
    return caps
