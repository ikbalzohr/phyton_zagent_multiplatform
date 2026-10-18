import json
from pathlib import Path

SCHEMA_VERSION = "2.0"
_DIR = Path(__file__).resolve().parent

def load_schema(name):
    path = _DIR / name
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)

def available_schemas():
    return {
        "goal": load_schema("goal.schema.json"),
        "context": load_schema("context.schema.json"),
        "plan": load_schema("plan.schema.json"),
        "result": load_schema("result.schema.json"),
        "validation": load_schema("validation.schema.json"),
    }
