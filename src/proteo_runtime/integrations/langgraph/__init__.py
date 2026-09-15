"""Optional LangGraph integration for provider-neutral Proteo runtime nodes."""

try:
    from .node import RuntimeNode
except ModuleNotFoundError as exc:
    if exc.name is not None and (
        exc.name == "langgraph"
        or exc.name.startswith("langgraph.")
        or exc.name == "langchain_core"
        or exc.name.startswith("langchain_core.")
    ):
        raise ModuleNotFoundError(
            "LangGraph integration requires the optional dependency; "
            "install proteo-runtime[langgraph]."
        ) from exc
    raise

__all__ = ["RuntimeNode"]
