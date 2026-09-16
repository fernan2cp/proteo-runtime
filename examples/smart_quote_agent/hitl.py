"""Human-in-the-loop (HITL) discount prompt and Phase 5 approval handler."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from database import format_currency

from proteo_runtime.tools import (
    ApprovalDecision,
    ApprovalHandler,
    ApprovalRequest,
)


def prompt_discount_interactive(
    subtotal_cents: int,
    *,
    input_func: Callable[[str], str] = input,
) -> int:
    """Prompt the human user interactively for a discount percentage (0..30).

    Args:
        subtotal_cents: Quote subtotal in integer cents.
        input_func: Input callable for testing or console interaction.

    Returns:
        Whole discount percentage in range 0..30.
    """
    print(f"\nSubtotal: {format_currency(subtotal_cents)}")
    apply_resp = input_func("Apply discount? [y/N]: ").strip().lower()
    if apply_resp not in ("y", "yes"):
        return 0

    while True:
        raw = input_func("Discount percentage [0-30, default 0]: ").strip()
        if not raw:
            return 0
        try:
            val = int(raw)
            if 0 <= val <= 30:
                return val
            print("Invalid percentage. Must be a whole number between 0 and 30.")
        except ValueError:
            print("Invalid input. Please enter a whole number between 0 and 30.")


class ConsoleApprovalHandler(ApprovalHandler):
    """Phase 5 ApprovalHandler prompting the console user for final write approval."""

    def __init__(
        self,
        *,
        input_func: Callable[[str], str] = input,
    ) -> None:
        """Configure the console approval handler.

        Args:
            input_func: Callable for interactive input (defaults to builtin input).
        """
        self._input_func = input_func

    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        """Prompt the user interactively before allowing a tool with write side-effects.

        Args:
            request: The validated tool execution request.

        Returns:
            ApprovalDecision.APPROVE or ApprovalDecision.DENY.
        """
        print(f"\n[APPROVAL REQUIRED] Tool execution requested: {request.tool_name}")
        args = request.arguments
        if request.tool_name == "create_quote":
            print(f"Customer ID: {args.get('customer_id')}")
            print(f"Discount: {args.get('discount_percent', 0)}%")

        resp = await asyncio.to_thread(self._input_func, "\nApprove quote creation? [y/N]: ")
        clean = resp.strip().lower()
        if clean in ("y", "yes"):
            print("[APPROVED] Action approved.")
            return ApprovalDecision.APPROVE

        print("[DENIED] Action denied by user.")
        return ApprovalDecision.DENY
