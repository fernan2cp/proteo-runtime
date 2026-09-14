"""Command-line entry point for Proteo Runtime."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from proteo_runtime import __version__


def main(argv: Sequence[str] | None = None) -> int:
    """Parse command-line arguments and return a process status code."""

    parser = argparse.ArgumentParser(prog="proteo-runtime", description="Proteo Runtime utilities")
    parser.add_argument("--version", action="version", version=__version__)
    parser.parse_args(argv)
    parser.print_help()
    return 0
