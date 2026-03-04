"""Prompt templates used for LLM extraction and correction."""

from __future__ import annotations

from pydantic import BaseModel


def _schema_to_field_descriptions(schema_cls: type[BaseModel]) -> str:
    """Convert a Pydantic model's JSON schema to a human-readable field list."""
    schema = schema_cls.model_json_schema()
    lines: list[str] = []

    def _walk(props: dict, required: set[str], indent: int = 0) -> None:
        prefix = "  " * indent
        for name, info in props.items():
            req = "(required)" if name in required else "(optional)"
            desc = info.get("description", "")
            typ = info.get("type", info.get("anyOf", "object"))
            lines.append(f"{prefix}- {name}: {typ} {req} — {desc}")
            # Recurse into nested objects
            if "properties" in info:
                _walk(
                    info["properties"],
                    set(info.get("required", [])),
                    indent + 1,
                )
            if "items" in info and "properties" in info["items"]:
                lines.append(f"{prefix}  (array of objects):")
                _walk(
                    info["items"]["properties"],
                    set(info["items"].get("required", [])),
                    indent + 2,
                )

    _walk(schema.get("properties", {}), set(schema.get("required", [])))
    return "\n".join(lines)


def build_extraction_prompt(raw_text: str, schema_cls: type[BaseModel]) -> str:
    """Build the initial extraction prompt."""
    fields = _schema_to_field_descriptions(schema_cls)
    return f"""You are a precise data-extraction assistant.

TASK:
Extract structured data from the unstructured text below and return
**only** a valid JSON object (no markdown fences, no commentary).

TARGET SCHEMA:
{fields}

RULES:
1. Output ONLY the JSON object — nothing else.
2. All required fields MUST be present.
3. Use correct data types (string, number, boolean, date as YYYY-MM-DD).
4. Numeric totals must be arithmetically consistent
   (e.g. line_total = quantity * unit_price; subtotal = sum of line totals).
5. If information is missing from the text, use reasonable defaults or null
   for optional fields.  Never omit required fields.

UNSTRUCTURED TEXT:
\"\"\"
{raw_text}
\"\"\"

JSON OUTPUT:"""


def build_correction_prompt(
    raw_text: str,
    previous_json: str,
    validation_errors: str,
    schema_cls: type[BaseModel],
) -> str:
    """Build a correction prompt that feeds back validation errors."""
    fields = _schema_to_field_descriptions(schema_cls)
    return f"""You are a precise data-extraction assistant performing a CORRECTION.

The previous JSON output **failed** schema validation.  Fix the errors
described below and return **only** a corrected, valid JSON object.

TARGET SCHEMA:
{fields}

PREVIOUS (INVALID) OUTPUT:
{previous_json}

VALIDATION ERRORS:
{validation_errors}

ORIGINAL TEXT (for reference):
\"\"\"
{raw_text}
\"\"\"

RULES:
1. Output ONLY the corrected JSON — no explanation, no markdown fences.
2. Fix every listed validation error.
3. Keep all other fields that were already correct.
4. Ensure numeric totals are arithmetically consistent.

CORRECTED JSON OUTPUT:"""
