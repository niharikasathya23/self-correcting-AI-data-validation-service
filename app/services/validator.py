"""Pydantic validation helper – validates parsed JSON against a target schema."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import BaseModel, ValidationError


@dataclass
class ValidationResult:
    """Outcome of validating a dict against a Pydantic model."""
    is_valid: bool
    data: Optional[dict[str, Any]] = None
    errors: list[str] = field(default_factory=list)
    error_summary: str = ""

    def __bool__(self) -> bool:
        return self.is_valid


def validate_against_schema(
    data: dict[str, Any],
    schema_cls: type[BaseModel],
) -> ValidationResult:
    """Validate *data* dict against *schema_cls* and return a structured result."""
    try:
        instance = schema_cls.model_validate(data)
        return ValidationResult(
            is_valid=True,
            data=json.loads(instance.model_dump_json()),
        )
    except ValidationError as exc:
        errors = []
        for err in exc.errors():
            loc = " → ".join(str(p) for p in err["loc"])
            msg = err["msg"]
            errors.append(f"[{loc}] {msg}")
        return ValidationResult(
            is_valid=False,
            errors=errors,
            error_summary="\n".join(errors),
        )
    except Exception as exc:
        return ValidationResult(
            is_valid=False,
            errors=[str(exc)],
            error_summary=str(exc),
        )
