"""Shared API schema base: camelCase on the wire, snake_case in Python."""

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# Bounded text for request bodies (Phase 7: nothing a client sends is unbounded).
ShortText = Annotated[str, StringConstraints(max_length=255)]
Tag = Annotated[str, StringConstraints(max_length=100)]
PathText = Annotated[str, StringConstraints(max_length=4096)]
SettingsMap = Annotated[dict[str, Any], Field(max_length=50)]
