"""Evidence redaction: strip secrets/PII from request/response evidence."""

from __future__ import annotations

import copy
import re
from typing import Any

from pydantic import BaseModel, Field

_MASK_LITERAL = "«redacted»"


def _mask_named(name: str) -> str:
    return f"«redacted:{name}»"


_BUILTIN_PATTERNS: list[tuple[str, str]] = [
    ("api_key", r"sk-[A-Za-z0-9_-]{8,}"),
    ("bearer", r"Bearer\s+[A-Za-z0-9._-]+"),
    ("email", r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    ("iban", r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}"),
    ("card", r"\b(?:\d[ -]*?){13,16}\b"),
    ("account", r"\b\d{8,17}\b"),
    ("phone", r"\+?\d[\d ()-]{7,}\d"),
]


class RedactionPattern(BaseModel):
    name: str
    regex: str


class RedactionConfig(BaseModel):
    patterns: list[RedactionPattern] = Field(default_factory=list)
    literals: list[str] = Field(default_factory=list)
    use_builtins: bool = True


class EvidencePolicy(BaseModel):
    store_request: bool = True
    store_response: bool = True
    redact: RedactionConfig = Field(default_factory=RedactionConfig)


class Redactor:
    def __init__(self, config: RedactionConfig):
        self._literals = list(config.literals)
        self._compiled: list[tuple[str, re.Pattern[str]]] = []

        if config.use_builtins:
            for name, pattern in _BUILTIN_PATTERNS:
                self._compiled.append((name, self._compile(name, pattern)))

        for p in config.patterns:
            self._compiled.append((p.name, self._compile(p.name, p.regex)))

    @staticmethod
    def _compile(name: str, pattern: str) -> re.Pattern[str]:
        try:
            return re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"invalid redaction pattern '{name}': {exc}") from exc

    def redact_text(self, text: str) -> str:
        result = text
        for literal in self._literals:
            if literal:
                result = result.replace(literal, _MASK_LITERAL)
        for name, regex in self._compiled:
            result = regex.sub(_mask_named(name), result)
        return result

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, dict):
            return {k: self.redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(v) for v in value]
        return copy.deepcopy(value)
