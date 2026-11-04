"""Settings forms for pluggable integrations (download clients, notifications).

Each implementation declares a pydantic model; the UI renders it from ``schema_fields``.
Secrets are masked on read and keep their stored value when the mask is sent back.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic.alias_generators import to_camel

from magarr.domain.errors import DomainError

MASKED = "********"


class FormSettings(BaseModel):
    """Base for implementation settings. Mark secrets with json_schema_extra={"secret": True};
    offer choices with json_schema_extra={"options": [...]}."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    @classmethod
    def secret_fields(cls) -> set[str]:
        return {
            name
            for name, info in cls.model_fields.items()
            if isinstance(info.json_schema_extra, dict) and info.json_schema_extra.get("secret")
        }


def _alias(model: type[FormSettings], name: str) -> str:
    return model.model_fields[name].alias or name


def masked(model: type[FormSettings], stored: dict[str, Any]) -> dict[str, Any]:
    data = model.model_validate(stored).model_dump(by_alias=True)
    for name in model.secret_fields():
        if data.get(_alias(model, name)):
            data[_alias(model, name)] = MASKED
    return data


def validated(
    model: type[FormSettings], raw: dict[str, Any], stored: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Validate ``raw``; masked secrets resolve to ``stored`` (the saved settings), if given."""
    raw = dict(raw)
    if stored is not None:
        current = model.model_validate(stored)
        for name in model.secret_fields():
            alias = _alias(model, name)
            if raw.get(alias) == MASKED or raw.get(name) == MASKED:
                raw.pop(name, None)
                raw[alias] = getattr(current, name)
    try:
        return model.model_validate(raw).model_dump()
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(p) for p in first["loc"])
        raise DomainError(f"{location}: {first['msg']}") from exc


def field_type(info: Any, secret: bool) -> str:
    if secret:
        return "password"
    if isinstance(info.json_schema_extra, dict) and "options" in info.json_schema_extra:
        return "select"
    if isinstance(info.json_schema_extra, dict) and info.json_schema_extra.get("multiline"):
        return "textarea"
    return {bool: "boolean", int: "number", float: "number"}.get(info.annotation, "string")


def schema_fields(model: type[FormSettings]) -> list[dict[str, Any]]:
    """Field descriptions for the UI form, in declaration order."""
    secrets = model.secret_fields()
    fields = []
    for name, info in model.model_fields.items():
        extra = info.json_schema_extra if isinstance(info.json_schema_extra, dict) else {}
        fields.append(
            {
                "name": info.alias or name,
                "label": info.title or name.replace("_", " ").capitalize(),
                "type": field_type(info, name in secrets),
                "required": info.is_required(),
                "default": None if info.is_required() else info.default,
                "description": info.description,
                "options": extra.get("options"),
            }
        )
    return fields
