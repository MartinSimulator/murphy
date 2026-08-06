# Schema.py validates tool arguments against checked-in JSON Schemas before an ActionIntent is built

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

class SchemaValidationError(Exception):
    """Raised when a tool is unknown or its arguments fail schema validation."""

# default to config/schemas
def _default_schemas_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "schemas"

# load all schemas from the schemas directory
def load_schemas(schemas_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    # if no schemas_dir is provided, use the default schemas directory
    directory = schemas_dir or _default_schemas_dir()
    if not directory.is_dir():
        raise FileNotFoundError(f"schemas directory not found: {directory}")
    # load all schemas from the schemas directory
    schemas: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        schemas[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return schemas

# loaded schemas are cached in a global variable
_SCHEMAS: dict[str, dict[str, Any]] | None = None

# get the cached schemas
def get_schemas() -> dict[str, dict[str, Any]]:
    global _SCHEMAS
    if _SCHEMAS is None:
        _SCHEMAS = load_schemas()
    return _SCHEMAS

# validate the arguments for a given server and tool
def validate_tool_args(
    server: str,
    tool: str,
    args: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Returns a plain dict copy of the args on success.
    Raises SchemaValidationError for unknown tools or invalid args.
    """
    key = f"{server}.{tool}"
    schemas = get_schemas()
    schema = schemas.get(key)
    if schema is None:
        raise SchemaValidationError(f"unknown tool: {key}")

    payload = dict(args)
    validator = Draft202012Validator(schema)
    try:
        validator.validate(payload)
    except JsonSchemaValidationError as exc:
        raise SchemaValidationError(f"{key}: {exc.message}") from exc

    return payload
