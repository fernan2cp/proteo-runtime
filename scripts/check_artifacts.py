"""Validate wheel and source distribution contents for safe release artifacts."""

from __future__ import annotations

import argparse
import tarfile
from pathlib import Path
from zipfile import ZipFile

_FORBIDDEN_MARKERS = (
    ".import_linter_cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".uv-cache",
    "__pycache__",
    ".coverage",
    "auth.json",
    ".codex",
    ".openai",
    "credentials",
)


def _assert_safe(names: list[str], artifact: Path) -> None:
    """Assert that an artifact contains no local caches or credential files."""

    lowered = [name.casefold() for name in names]
    unsafe = [
        name
        for name, normalized in zip(names, lowered, strict=True)
        if any(marker in normalized for marker in _FORBIDDEN_MARKERS)
    ]
    if unsafe:
        raise SystemExit(f"Unsafe paths in {artifact.name}: {unsafe}")


def _check_wheel(path: Path) -> None:
    """Validate package, typing marker, metadata, license, and entry point in a wheel."""

    with ZipFile(path) as archive:
        names = archive.namelist()
        _assert_safe(names, path)
        required = (
            "proteo_runtime/__init__.py",
            "proteo_runtime/py.typed",
            "proteo_runtime/integrations/langgraph/__init__.py",
        )
        for item in required:
            if not any(name.endswith(item) for name in names):
                raise SystemExit(f"Missing {item} in {path.name}")
        metadata = next((name for name in names if name.endswith(".dist-info/METADATA")), None)
        if metadata is None:
            raise SystemExit(f"Missing wheel metadata in {path.name}")
        metadata_text = archive.read(metadata).decode()
        if "Provides-Extra: langgraph" not in metadata_text:
            raise SystemExit(f"Missing langgraph extra metadata in {path.name}")
        if "Requires-Dist: langgraph" not in metadata_text:
            raise SystemExit(f"Missing langgraph dependency metadata in {path.name}")
        entry_points = next(
            (name for name in names if name.endswith(".dist-info/entry_points.txt")), None
        )
        if entry_points is None or "proteo-runtime" not in archive.read(entry_points).decode():
            raise SystemExit(f"Missing proteo-runtime entry point in {path.name}")
        if not any(name.casefold().endswith("license") for name in names):
            raise SystemExit(f"Missing license in {path.name}")


def _check_sdist(path: Path) -> None:
    """Validate source distribution package, typing marker, project metadata, and license."""

    with tarfile.open(path) as archive:
        names = archive.getnames()
        _assert_safe(names, path)
        required = (
            "/src/proteo_runtime/__init__.py",
            "/src/proteo_runtime/py.typed",
            "/src/proteo_runtime/integrations/langgraph/__init__.py",
            "/pyproject.toml",
            "/LICENSE",
        )
        for item in required:
            if not any(name.endswith(item) for name in names):
                raise SystemExit(f"Missing {item} in {path.name}")


def main(argv: list[str] | None = None) -> int:
    """Validate exactly one wheel and one source distribution under a directory."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path)
    args = parser.parse_args(argv)
    wheels = sorted(args.dist.glob("*.whl"))
    sdists = sorted(args.dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit(f"Expected one wheel and one sdist, found {len(wheels)} and {len(sdists)}")
    _check_wheel(wheels[0])
    _check_sdist(sdists[0])
    print(f"Validated {wheels[0].name} and {sdists[0].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
