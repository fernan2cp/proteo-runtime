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
    language: str = "en",
) -> int:
    """Prompt the human user interactively for a discount percentage (0..30).

    Args:
        subtotal_cents: Quote subtotal in integer cents.
        input_func: Input callable for testing or console interaction.
        language: Stable interaction language (`es` or `en`).

    Returns:
        Whole discount percentage in range 0..30.
    """
    is_spanish = language == "es"
    print(f"\nSubtotal: {format_currency(subtotal_cents)}")
    apply_prompt = "¿Aplicar descuento? [s/N]: " if is_spanish else "Apply discount? [y/N]: "
    apply_resp = input_func(apply_prompt).strip().lower()
    affirmative = ("s", "si", "sí", "y", "yes") if is_spanish else ("y", "yes")
    if apply_resp not in affirmative:
        return 0

    while True:
        percentage_prompt = (
            "Porcentaje de descuento [0-30, predeterminado 0]: "
            if is_spanish
            else "Discount percentage [0-30, default 0]: "
        )
        raw = input_func(percentage_prompt).strip()
        if not raw:
            return 0
        try:
            val = int(raw)
            if 0 <= val <= 30:
                return val
            print(
                "Porcentaje inválido. Debe ser un número entero entre 0 y 30."
                if is_spanish
                else "Invalid percentage. Must be a whole number between 0 and 30."
            )
        except ValueError:
            print(
                "Entrada inválida. Ingresa un número entero entre 0 y 30."
                if is_spanish
                else "Invalid input. Please enter a whole number between 0 and 30."
            )


class ConsoleApprovalHandler(ApprovalHandler):
    """Phase 5 ApprovalHandler prompting the console user for final write approval."""

    def __init__(
        self,
        *,
        input_func: Callable[[str], str] = input,
        language: str = "en",
    ) -> None:
        """Configure the console approval handler.

        Args:
            input_func: Callable for interactive input (defaults to builtin input).
            language: Stable interaction language (`es` or `en`).
        """
        self._input_func = input_func
        self._language = language

    def set_language(self, language: str) -> None:
        """Set the language used by the next approval prompt.

        Args:
            language: Stable interaction language (`es` or `en`).
        """
        self._language = language

    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        """Prompt the user interactively before allowing a tool with write side-effects.

        Args:
            request: The validated tool execution request.

        Returns:
            ApprovalDecision.APPROVE or ApprovalDecision.DENY.
        """
        is_spanish = self._language == "es"
        prefix = (
            "[APROBACIÓN REQUERIDA] Acción solicitada"
            if is_spanish
            else "[APPROVAL REQUIRED] Tool execution requested"
        )
        print(f"\n{prefix}: {request.tool_name}")
        args = request.arguments
        if request.tool_name == "create_quote":
            customer_label = "ID de cliente" if is_spanish else "Customer ID"
            discount_label = "Descuento" if is_spanish else "Discount"
            print(f"{customer_label}: {args.get('customer_id')}")
            print(f"{discount_label}: {args.get('discount_percent', 0)}%")

        prompt = (
            "\n¿Aprobar la creación de la cotización? [s/N]: "
            if is_spanish
            else "\nApprove quote creation? [y/N]: "
        )
        resp = await asyncio.to_thread(self._input_func, prompt)
        clean = resp.strip().lower()
        if clean in (("s", "si", "sí", "y", "yes") if is_spanish else ("y", "yes")):
            print("[APROBADO] Acción aprobada." if is_spanish else "[APPROVED] Action approved.")
            return ApprovalDecision.APPROVE

        print(
            "[RECHAZADO] Acción rechazada por el usuario."
            if is_spanish
            else "[DENIED] Action denied by user."
        )
        return ApprovalDecision.DENY
