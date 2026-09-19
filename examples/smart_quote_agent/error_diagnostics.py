"""Privacy-preserving exception metadata helpers for the example host."""

from __future__ import annotations

import re
import traceback
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,119}$")
_SAFE_ERROR_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
_SAFE_PROVIDER_CODES = frozenset(
    {
        "contextWindowExceeded",
        "sessionBudgetExceeded",
        "usageLimitExceeded",
        "serverOverloaded",
        "cyberPolicy",
        "internalServerError",
        "unauthorized",
        "badRequest",
        "threadRollbackFailed",
        "sandboxError",
        "other",
        "httpConnectionFailed",
        "responseStreamConnectionFailed",
        "responseStreamDisconnected",
        "responseTooManyFailedAttempts",
        "activeTurnNotSteerable",
    }
)


def sanitize_exception(
    error: BaseException,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Return a bounded exception summary without messages or local variables.

    Args:
        error: Exception to describe structurally.
        repository_root: Root used to make in-repository traceback paths relative.

    Returns:
        JSON-compatible exception type, safe code, cause types, and frames.
    """
    error_type = type(error)
    module = _safe_identifier(error_type.__module__)
    type_name = _safe_identifier(error_type.__name__)
    summary: dict[str, Any] = {
        "exception_module": module,
        "exception_type": type_name,
        "cause_types": _cause_types(error),
        "frames": _traceback_frames(error, repository_root),
    }

    code = _stable_error_code(error)
    if code is not None:
        summary["code"] = code
    summary.update(_safe_provider_diagnostics(error))
    return summary


def _safe_identifier(value: str) -> str:
    """Return a safe bounded Python identifier-like value."""
    return value if _SAFE_IDENTIFIER.fullmatch(value) else "unknown"


def _stable_error_code(error: BaseException) -> str | None:
    """Read only a bounded, machine-like stable code from an exception."""
    for attribute in ("error_code", "code"):
        try:
            value = getattr(error, attribute, None)
        except Exception:
            continue
        if isinstance(value, str) and _SAFE_ERROR_CODE.fullmatch(value):
            return value
    return None


def _safe_provider_diagnostics(error: BaseException) -> dict[str, str | int]:
    """Copy only known-safe Codex status fields from runtime error details."""
    details = getattr(error, "details", None)
    if not isinstance(details, Mapping):
        return {}

    safe: dict[str, str | int] = {}
    status = details.get("provider_status")
    if isinstance(status, str) and status in {"failed", "interrupted"}:
        safe["provider_status"] = status
    provider_code = details.get("provider_error_code")
    if isinstance(provider_code, str) and provider_code in _SAFE_PROVIDER_CODES:
        safe["provider_error_code"] = provider_code
    http_status = details.get("provider_http_status")
    if (
        isinstance(http_status, int)
        and not isinstance(http_status, bool)
        and 100 <= http_status <= 599
    ):
        safe["provider_http_status"] = http_status
    return safe


def _cause_types(error: BaseException) -> list[str]:
    """Return exception type names from the explicit or implicit cause chain."""
    result: list[str] = []
    seen: set[int] = {id(error)}
    current = error
    for _ in range(8):
        cause = current.__cause__
        if cause is None and not current.__suppress_context__:
            cause = current.__context__
        if cause is None or id(cause) in seen:
            break
        seen.add(id(cause))
        result.append(
            f"{_safe_identifier(type(cause).__module__)}.{_safe_identifier(type(cause).__name__)}"
        )
        current = cause
    return result


def _traceback_frames(error: BaseException, repository_root: Path) -> list[dict[str, str | int]]:
    """Return only bounded, redacted traceback location fields."""
    root = repository_root.resolve()
    extracted = traceback.extract_tb(error.__traceback__)[-40:]
    frames: list[dict[str, str | int]] = []
    for frame in extracted:
        filename = frame.filename
        if filename.startswith("<") and filename.endswith(">"):
            safe_file = filename[:80]
        else:
            path = Path(filename)
            try:
                safe_file = path.resolve().relative_to(root).as_posix()
            except (OSError, ValueError):
                safe_file = f"<external>/{path.name[:120]}"
        location: dict[str, str | int] = {
            "file": safe_file,
            "function": _safe_identifier(frame.name),
        }
        if isinstance(frame.lineno, int):
            location["line"] = frame.lineno
        frames.append(location)
    return frames
