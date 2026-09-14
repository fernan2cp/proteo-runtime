"""Security policy vocabulary."""

from enum import StrEnum


class SecurityPolicy(StrEnum):
    """Initial provider-neutral security policy names."""

    ISOLATED = "isolated"
    READ_ONLY = "read_only"
    CONTROLLED_TOOLS = "controlled_tools"
    NATIVE = "native"
