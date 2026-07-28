#!/usr/bin/env python3
"""Generate tool_definitions.json from per-tool JSON Schema files.

Reads all .json files from the schemas/ directory (excluding regions.json),
transforms each into OpenAI function-calling format ``{name, description, parameters}``,
and writes the aggregate tool_definitions.json to the schemas/ directory.
"""

from __future__ import annotations

import json
from pathlib import Path

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "src" / "cloudops_fc" / "schemas"
TOOL_DEFINITIONS_FILE = SCHEMAS_DIR / "tool_definitions.json"
EXCLUDED_FILES: set[str] = {"regions.json", "tool_definitions.json"}

# Keys that form the ``parameters`` envelope in OpenAI function-calling format.
_PARAMETER_KEYS = ("type", "properties", "required", "additionalProperties", "$defs")


def load_tool_schemas(schemas_dir: Path) -> list[dict]:
    """Load per-tool JSON Schema files and convert to OpenAI function-calling entries."""
    tools: list[dict] = []
    for json_path in sorted(schemas_dir.glob("*.json")):
        if json_path.name in EXCLUDED_FILES:
            continue
        name = json_path.stem
        with json_path.open("r", encoding="utf-8") as f:
            schema: dict = json.load(f)
        tools.append(
            {
                "name": name,
                "description": schema.get("description", ""),
                "parameters": {k: schema[k] for k in _PARAMETER_KEYS if k in schema},
            }
        )
    return tools


def main() -> None:
    tools = load_tool_schemas(SCHEMAS_DIR)
    with TOOL_DEFINITIONS_FILE.open("w", encoding="utf-8") as f:
        json.dump(tools, f, indent=2)
        f.write("\n")
    print(f"Generated {TOOL_DEFINITIONS_FILE} with {len(tools)} tool(s)")


if __name__ == "__main__":
    main()
