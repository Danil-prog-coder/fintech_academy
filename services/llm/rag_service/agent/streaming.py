"""StreamingGuard (NFR-01): the final answer reaches the user paragraph by paragraph, each one checked first.

The agent finishes a turn with the `final_answer` tool call, whose arguments arrive as a growing JSON
string. The schema asks for `kind`, `coverage` and `citations` before `text`, so by the time the text
starts, the guard already knows what the answer cites. Every complete paragraph is validated with the
same deterministic rules as the whole answer (markers point to real sources of this dialog, numbers
come from the sources) and only then emitted as a `delta` event.

Nothing unverified is shown. If a later paragraph or the whole-answer check fails after something was
emitted, the loop sends a `reset` event: the client discards the shown text and waits for the checked one.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from . import guardrails as gr

_WS = " \t\r\n"


def _decode_partial_string(raw: str) -> str:
    """Decode the body of an unfinished JSON string (no closing quote yet)."""
    # an unfinished escape at the very end cannot be decoded yet
    m = re.search(r"\\(u[0-9a-fA-F]{0,3})?$", raw)
    if m and (len(raw) - len(raw.rstrip("\\"))) % 2 == 1 or (m and m.group(1) is not None):
        raw = raw[: m.start()]
    try:
        return json.loads('"' + raw + '"')
    except json.JSONDecodeError:
        return ""


def partial_json_object(buf: str) -> tuple[dict[str, Any], str | None, str]:
    """Parse a possibly unfinished top-level JSON object.

    Returns (complete top-level values, key of an unfinished string value, its decoded text so far)."""
    done: dict[str, Any] = {}
    i = buf.find("{")
    if i < 0:
        return done, None, ""
    i += 1
    n = len(buf)
    dec = json.JSONDecoder()
    while i < n:
        while i < n and buf[i] in _WS + ",":
            i += 1
        if i >= n or buf[i] == "}":
            break
        if buf[i] != '"':
            break
        try:
            key, i = dec.raw_decode(buf, i)
        except json.JSONDecodeError:
            break  # the key itself is unfinished
        while i < n and buf[i] in _WS:
            i += 1
        if i >= n or buf[i] != ":":
            break
        i += 1
        while i < n and buf[i] in _WS:
            i += 1
        if i >= n:
            break
        try:
            value, j = dec.raw_decode(buf, i)
        except json.JSONDecodeError:
            if buf[i] == '"':
                return done, key, _decode_partial_string(buf[i + 1:])
            break
        # a number/literal at the very end of the buffer may still grow («12» → «123»)
        if j >= n and not isinstance(value, (str, list, dict)):
            break
        done[key] = value
        i = j
    return done, None, ""


class StreamingGuard:
    """Feeds on growing `final_answer` arguments and emits verified paragraphs through `emit`."""

    def __init__(self, registry: dict, user_text: str, min_evidence: float, emit: Callable[[dict], None]) -> None:
        self.registry = registry
        self.min_evidence = min_evidence
        self.emit = emit
        self.emitted = ""  # exactly the text already sent as deltas
        self.held = False  # stop streaming: the full check after the call decides what the user sees
        self._allowed: set[str] | None = None
        self._user_text = user_text
        self._citations_ok: bool | None = None
        self._by_n: dict[int, str] = {}

    # -- checks
    def _precheck(self, citations: Any) -> bool:
        """Whole-answer conditions that are known before the text starts."""
        if not self.registry or not isinstance(citations, list) or not citations:
            return False
        valid = []
        for c in citations:
            try:
                n, sid = int(c.get("n")), str(c.get("source_id", "")).strip()
            except (AttributeError, TypeError, ValueError):
                return False
            if sid not in self.registry:
                return False
            self._by_n[n] = sid
            valid.append({"n": n, "source_id": sid})
        if not any(self.registry[c["source_id"]].get("kind") == "chunk" for c in valid):
            return False
        return gr.max_evidence(valid, self.registry) >= self.min_evidence

    def _paragraph_ok(self, para: str, grounded: bool) -> bool:
        markers = [int(x) for x in gr.CITE_RE.findall(para)]
        if not grounded:
            return not markers and not re.search(r"\[[ST]\d", para)
        if re.search(r"\[[ST]\d", para) or any(n not in self._by_n for n in markers):
            return False
        if self._allowed is None:
            self._allowed = gr.numbers_in_sources([v.get("text", "") for v in self.registry.values()] + [self._user_text])
        return not gr.ungrounded_numbers(para, self._allowed)

    # -- stream events
    def on_delta(self, ev: dict) -> None:
        if ev.get("type") == "restart":
            self.reset()
            return
        if self.held or ev.get("type") != "tool" or ev.get("name") != "final_answer":
            return
        fields, open_key, partial = partial_json_object(ev.get("arguments") or "")
        kind = fields.get("kind")
        if kind not in ("grounded", "no_facts"):
            return
        complete = "text" in fields
        text = fields["text"] if complete else (partial if open_key == "text" else None)
        if not isinstance(text, str) or not text:
            return
        grounded = kind == "grounded"
        if grounded:
            if self._citations_ok is None:
                if "citations" not in fields:
                    if complete:
                        self.held = True  # text came before citations: nothing can be checked on the fly
                    return
                self._citations_ok = self._precheck(fields["citations"])
            if not self._citations_ok:
                self.held = True
                return
        if not text.startswith(self.emitted):
            self.held = True
            return
        end = len(text) if complete else text.rfind("\n\n") + 2
        if end <= len(self.emitted) or (not complete and end < 2):
            return
        for para in re.findall(r".*?(?:\n\n|\Z)", text[len(self.emitted):end], re.S):
            if not para:
                continue
            if not self._paragraph_ok(para, grounded):
                self.held = True
                return
            self.emitted += para
            self.emit({"type": "delta", "text": para})

    def reset(self) -> None:
        """Discard what was shown (failed check, retry, another model of the chain took over)."""
        if self.emitted:
            self.emit({"type": "reset"})
        self.emitted = ""
        self.held = False
        self._citations_ok = None
        self._by_n = {}
