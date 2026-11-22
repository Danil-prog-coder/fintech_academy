"""PromptRegistry (FR-AGT-09, Miro S89): versioned system prompt file; version logged with every turn."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from ..config import get_settings


class PromptRegistry:
    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or get_settings().prompt_file)
        raw = self.path.read_text(encoding="utf-8")
        self.meta: dict[str, str] = {}
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.S)
        if m:
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    self.meta[k.strip()] = v.strip()
            raw = raw[m.end():]
        self.template = raw
        self.version = self.meta.get("version", "unversioned")

    def render(self, **kw: str) -> str:
        out = self.template
        for k, v in kw.items():
            out = out.replace("{" + k + "}", str(v))
        return out


@lru_cache
def get_prompts() -> PromptRegistry:
    return PromptRegistry()
