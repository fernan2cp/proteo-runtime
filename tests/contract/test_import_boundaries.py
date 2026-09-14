"""Static and dynamic import boundary tests."""

import ast
import sys
from pathlib import Path


def test_core_does_not_import_provider_sdk_or_frameworks() -> None:
    """Core imports remain provider-neutral at runtime and in source."""

    import proteo_runtime.core  # noqa: F401

    forbidden = {"openai_codex", "langgraph", "langsmith", "opentelemetry"}
    assert forbidden.isdisjoint(sys.modules)
    root = Path(__file__).parents[2] / "src" / "proteo_runtime" / "core"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert all(not any(item in module for item in forbidden) for module in names)
