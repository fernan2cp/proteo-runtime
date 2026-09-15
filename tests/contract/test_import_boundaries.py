"""Static and dynamic import boundary tests."""

import ast
import sys
from pathlib import Path


def test_core_does_not_import_provider_sdk_or_frameworks() -> None:
    """Core and testing imports remain provider-neutral at runtime and in source."""

    forbidden = {
        "openai_codex",
        "langgraph",
        "langsmith",
        "opentelemetry",
    }
    imported_before = {name for name in forbidden if name in sys.modules}
    import proteo_runtime.core as core
    import proteo_runtime.testing as testing

    assert hasattr(core, "Runtime")
    assert hasattr(testing, "FakeRuntime")
    assert imported_before == {name for name in forbidden if name in sys.modules}
    roots = [
        Path(__file__).parents[2] / "src" / "proteo_runtime" / "core",
        Path(__file__).parents[2] / "src" / "proteo_runtime" / "testing",
    ]
    for root in roots:
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported.append(node.module or "")
            assert all(
                not any(module == item or module.startswith(item + ".") for item in forbidden)
                for module in imported
            )
