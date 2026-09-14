"""Provider-neutral input message contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class TextContent:
    """A text content block."""

    text: str


@dataclass(frozen=True, slots=True)
class RuntimeMessage:
    """A role-labelled immutable message."""

    role: Literal["system", "user", "assistant", "tool"]
    content: tuple[TextContent, ...]

    def __post_init__(self) -> None:
        """Normalize content to a tuple and reject empty messages."""

        if not self.content:
            raise ValueError("A runtime message must contain content")
        if any(not isinstance(item, TextContent) for item in self.content):
            raise TypeError("RuntimeMessage content must contain TextContent blocks")
        object.__setattr__(self, "content", tuple(self.content))


@dataclass(frozen=True, slots=True)
class RuntimeInput:
    """Immutable sequence of runtime messages."""

    messages: tuple[RuntimeMessage, ...]

    def __post_init__(self) -> None:
        """Normalize messages to tuples and reject an empty input."""

        if not self.messages:
            raise ValueError("RuntimeInput requires at least one message")
        object.__setattr__(self, "messages", tuple(self.messages))

    @classmethod
    def from_value(cls, value: str | RuntimeInput) -> RuntimeInput:
        """Normalize a string or existing input; reject arbitrary objects."""

        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls((RuntimeMessage("user", (TextContent(value),)),))
        raise TypeError("RuntimeInput accepts only str or RuntimeInput")

    @property
    def text(self) -> str:
        """Return the concatenated text content for deterministic fakes."""

        return "".join(block.text for message in self.messages for block in message.content)
