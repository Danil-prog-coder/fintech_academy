"""Thin wrapper over an OpenAI-compatible Chat Completions API with retries/backoff (NFR-04)."""

from __future__ import annotations

import contextvars
import logging
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from functools import lru_cache
from types import SimpleNamespace
from typing import Any, Callable, Iterator

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

from ..config import get_settings

log = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    pass


class StallTimeout(TimeoutError):
    """The provider sent nothing for LLM_STALL_TIMEOUT_S, or the turn's deadline passed mid-stream."""


def provider_endpoint(provider: str | None = None) -> tuple[str | None, str | None]:
    """(api_key, base_url) of a provider: openrouter | gemini | openai/other (LLM_API_KEY + LLM_BASE_URL)."""
    s = get_settings()
    p = (provider or s.llm_provider or "openai").lower()
    if p == "openrouter":
        return (s.openrouter_api_key or s.llm_api_key or None), (s.llm_base_url if s.llm_provider == "openrouter" and s.llm_base_url else s.openrouter_base_url)
    if p == "gemini":
        key = s.gemini_api_key or (s.llm_api_key if s.llm_provider == "gemini" else "") or s.embedding_api_key
        return key or None, s.gemini_base_url
    return s.llm_api_key or None, s.llm_base_url or None


@lru_cache
def client(provider: str | None = None) -> OpenAI:
    s = get_settings()
    key, base = provider_endpoint(provider)
    headers = {"X-Title": "BARS RAG"} if (provider or s.llm_provider) == "openrouter" else None
    return OpenAI(api_key=key, base_url=base, timeout=s.llm_timeout_s, max_retries=0, default_headers=headers)


def split_model(m: str) -> tuple[str | None, str]:
    """'gemini/gemini-3.5-flash' → ('gemini', 'gemini-3.5-flash'); OpenRouter ids like 'z-ai/glm-5.3' keep their slash."""
    head, _, rest = m.partition("/")
    if rest and head in ("gemini", "openrouter", "openai"):
        return head, rest
    return None, m


_rl_lock = threading.Lock()
_calls: dict[str, deque] = defaultdict(deque)


def _try_acquire(model: str) -> float:
    """Client-side requests-per-minute limiter (LLM_RPM per model, 0 = off). Returns 0 if a slot was taken,
    otherwise the number of seconds until a slot frees up."""
    rpm = get_settings().llm_rpm
    if not rpm:
        return 0.0
    with _rl_lock:
        q = _calls[model]
        now = time.time()
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) < rpm:
            q.append(now)
            return 0.0
        return 60 - (now - q[0]) + 0.05


def _rate_limit(model: str, deadline: float | None = None) -> None:
    while True:
        wait = _try_acquire(model)
        if wait <= 0:
            return
        if deadline is not None and time.time() + wait > deadline:
            raise TimeoutError("rate limit wait exceeds deadline")
        time.sleep(min(wait, 5.0))


def _pick_order(chain: list[str]) -> list[str]:
    """Models with a free RPM slot first (spreads load over per-model free-tier quotas), keeping chain order."""
    rpm = get_settings().llm_rpm
    if not rpm:
        return chain
    now = time.time()
    with _rl_lock:
        free = [m for m in chain if sum(1 for t in _calls[m] if now - t <= 60) < rpm]
    return free + [m for m in chain if m not in free]


_exhausted: set[str] = set()
_cooldown: dict[str, float] = {}  # model -> unix time until which it is skipped (per-minute 429 / 5xx overload)


def _is_daily_quota(e: Exception) -> bool:
    body = str(getattr(getattr(e, "response", None), "text", "") or e)
    return "PerDay" in body or "per day" in body.lower()


def _gemini_compatible(messages: list[dict]) -> list[dict]:
    """Cross-provider fallback mid-turn: Gemini 3 rejects function-call history without thought signatures
    (produced by another model). Google documents a dummy signature that skips the validation."""
    out = []
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            m = dict(m)
            tcs = []
            for tc in m["tool_calls"]:
                if isinstance(tc, dict) and not tc.get("extra_content"):
                    tc = dict(tc, extra_content={"google": {"thought_signature": "skip_thought_signature_validator"}})
                tcs.append(tc)
            m["tool_calls"] = tcs
        out.append(m)
    return out


def _is_credit_error(e: Exception) -> bool:
    return getattr(e, "status_code", None) == 402


# ---- usage metering: every chat() inside `usage_scope()` adds its tokens to one per-model meter (FR-AN-01) ----
_meter: contextvars.ContextVar[dict | None] = contextvars.ContextVar("llm_usage_meter", default=None)
_meter_lock = threading.Lock()


@contextmanager
def usage_scope() -> Iterator[dict]:
    """Collect token usage of all LLM calls made in this context: {model: {prompt_tokens, completion_tokens, calls, cost?}}.

    Worker threads see the meter when started through `contextvars.copy_context().run`."""
    meter: dict = {}
    token = _meter.set(meter)
    try:
        yield meter
    finally:
        _meter.reset(token)


def _record_usage(model: str, usage: Any, cost: float = 0.0) -> None:
    meter = _meter.get()
    if meter is None:
        return
    with _meter_lock:
        m = meter.setdefault(model, {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0})
        m["calls"] += 1
        if cost:
            m["cost"] = round(m.get("cost", 0.0) + cost, 6)  # reported by the provider (OpenRouter)
        if usage is not None:
            m["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
            m["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0


def _read_stream(stream: Any, on_delta: Callable[[dict], None], content: list[str], calls: dict[int, dict],
                 usage_box: list, state: dict | None = None) -> None:
    for chunk in stream:
        if state is not None:
            if state.get("abandoned"):
                return  # the waiting thread gave up on this call
            state["last"] = time.time()
        if getattr(chunk, "usage", None):
            usage_box[0] = chunk.usage
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        if delta is None:
            continue
        if getattr(delta, "content", None):
            content.append(delta.content)
            on_delta({"type": "content", "text": "".join(content)})
        for tc in getattr(delta, "tool_calls", None) or []:
            idx = getattr(tc, "index", None)
            idx = len(calls) if idx is None else idx
            c = calls.setdefault(idx, {"id": None, "name": "", "arguments": "", "extra_content": None})
            if getattr(tc, "id", None):
                c["id"] = tc.id
            fn = getattr(tc, "function", None)
            if fn is not None:
                if getattr(fn, "name", None):
                    c["name"] = fn.name
                if getattr(fn, "arguments", None):
                    c["arguments"] += fn.arguments
            extra = getattr(tc, "extra_content", None) or (getattr(tc, "model_extra", None) or {}).get("extra_content")
            if extra:
                c["extra_content"] = extra  # provider extras (e.g. Gemini thought signatures) must be echoed back
            on_delta({"type": "tool", "index": idx, "name": c["name"], "arguments": c["arguments"]})


def _consume_stream(stream: Any, on_delta: Callable[[dict], None], state: dict | None = None) -> Any:
    """Read a streamed completion, forward progress to `on_delta` and assemble a response-like object.

    on_delta events: {"type": "content", "text": <all content so far>} and
    {"type": "tool", "index": i, "name": <tool name>, "arguments": <all argument text so far>}.
    `state["last"]` (if given) gets the time of the latest chunk — the watchdog of `_guarded_stream` reads it."""
    content: list[str] = []
    calls: dict[int, dict] = {}
    usage_box: list = [None]
    _read_stream(stream, on_delta, content, calls, usage_box, state)
    usage = usage_box[0]
    ordered = [calls[i] for i in sorted(calls)]
    tool_calls = [SimpleNamespace(id=c["id"] or f"call_{i}", type="function",
                                  function=SimpleNamespace(name=c["name"], arguments=c["arguments"] or "{}"))
                  for i, c in enumerate(ordered)]
    dump = {"content": "".join(content),
            "tool_calls": [{"extra_content": c["extra_content"]} if c["extra_content"] else {} for c in ordered]}
    msg = SimpleNamespace(content="".join(content), tool_calls=tool_calls or None, model_dump=lambda **kw: dump)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)


def _guarded_stream(open_stream: Callable[[], Any], on_delta: Callable[[dict], None], until: float | None,
                    stall: float) -> Any:
    """LLM_STALL_TIMEOUT_S / LLM_DEADLINE_CAP for a streamed call. The request runs in a worker thread and this one
    watches it: no chunk for `stall` s (OpenRouter keeps an idle stream alive with SSE comments, so the HTTP read
    timeout may never fire) or the turn's deadline → the call is abandoned at once (its late output is dropped,
    the connection is closed in the background) and StallTimeout goes to the fallback logic of `chat`."""
    state: dict = {"last": time.time(), "stream": None, "resp": None, "err": None}
    done, abandoned = threading.Event(), threading.Event()

    def fwd(ev: dict) -> None:
        if not abandoned.is_set():
            on_delta(ev)

    def work() -> None:
        try:
            st = open_stream()
            state["stream"], state["last"] = st, time.time()
            state["resp"] = _consume_stream(st, fwd, state)
        except BaseException as e:  # noqa: BLE001  (handed to the waiting thread)
            state["err"] = e
        finally:
            if state.get("abandoned") and state["stream"] is not None:
                _close_quietly(state["stream"])
            done.set()

    threading.Thread(target=contextvars.copy_context().run, args=(work,), daemon=True).start()
    while not done.wait(0.2):
        now = time.time()
        if until is not None and now > until:
            why = "deadline: the stream passed the turn's deadline"
        elif stall and now - state["last"] > stall:
            why = f"stall: no data for {stall:.0f} s"
        else:
            continue
        # the worker closes its stream itself at its next chunk (closing an httpx stream from another thread can block
        # the shared connection pool — in a test run that froze every LLM call of the process for 6 minutes)
        abandoned.set()
        state["abandoned"] = True
        raise StallTimeout(why)
    if state["err"] is not None:
        raise state["err"]
    return state["resp"]


def _close_quietly(stream: Any) -> None:
    try:
        stream.close()
    except Exception:  # noqa: BLE001
        pass


def chat(*, model: str, messages: list[dict], retries: int | None = None, deadline: float | None = None,
         on_delta: Callable[[dict], None] | None = None, **kwargs: Any):
    """Chat completion with backoff on transient errors/429 (NFR-04).

    `model` may be a comma-separated fallback chain ("gemini-3.5-flash,gemma-4-31b-it"): a model whose
    daily quota is exhausted is skipped for the rest of the process.
    With `on_delta` the completion is streamed: progress goes to the callback (see `_consume_stream`), and
    {"type": "restart"} is sent when a failed attempt is repeated after some output was already forwarded.
    """
    s = get_settings()
    retries = s.llm_max_retries if retries is None else retries
    chain = _pick_order([m.strip() for m in model.split(",") if m.strip()])
    last: Exception | None = None
    for idx, m in enumerate(chain):
        is_last = idx == len(chain) - 1
        if not is_last and (m in _exhausted or _cooldown.get(m, 0) > time.time()):
            continue
        kw = dict(kwargs)
        base_m, _, pin = m.partition("@")  # «model@Provider»: pin one OpenRouter provider (no silent fallback)
        prov, model_name = split_model(base_m)
        if s.llm_max_tokens and "max_tokens" not in kw:
            kw["max_tokens"] = s.llm_max_tokens
        if "reasoning_effort" not in kw and s.rerank_reasoning_effort:
            kw["reasoning_effort"] = s.rerank_reasoning_effort  # default for auxiliary calls (rerank, FAQ, classification)
        if "glm" in model_name and not kw.get("reasoning_effort"):
            kw.pop("reasoning_effort", None)  # GLM: reasoning is always on; provider default effort applies
        if "reasoning_effort" in kw and kw["reasoning_effort"] and "gemma" in m:
            kw["reasoning_effort"] = "minimal"  # gemma accepts only 'minimal' (disables thought output)
        if "gemma" in m:
            kw.setdefault("reasoning_effort", "minimal")
            kw.pop("response_format", None)  # JSON mode is not supported for gemma; prompts ask for JSON anyway
        if (prov or s.llm_provider) == "openrouter":
            # OpenRouter: unified `reasoning` object and provider preferences go into the request body
            extra = dict(kw.pop("extra_body", None) or {})
            effort = kw.pop("reasoning_effort", None)
            if effort and not ("glm" in model_name and effort in ("none", "minimal")):
                extra["reasoning"] = {"effort": effort}
            if pin:
                extra["provider"] = {"only": [pin], "sort": "throughput", "allow_fallbacks": False}
            if extra:
                kw["extra_body"] = extra
        delay = 1.0
        for attempt in range(retries + 1):
            until = None
            ckw = kw
            stall = s.llm_stall_timeout_s if on_delta is not None else 0.0  # only streams: a long non-streamed answer is not a stall
            if stall or (s.llm_deadline_cap and deadline is not None):
                import httpx

                read = stall or s.llm_timeout_s
                if s.llm_deadline_cap and deadline is not None:
                    until = deadline
                    left = deadline - time.time()
                    if left <= 0.3:
                        raise LLMUnavailable("turn deadline reached")
                    read = min(read, left)
                ckw = dict(kw, timeout=httpx.Timeout(read, connect=min(5.0, read)))
            try:
                try:
                    _rate_limit(m, deadline)
                except TimeoutError as e:
                    last = e
                    break
                msgs = _gemini_compatible(messages) if (prov == "gemini" or model_name.startswith("gemini")) else messages
                if on_delta is not None:
                    skw = dict(ckw, stream=True)
                    if s.llm_stream_usage:
                        skw["stream_options"] = {"include_usage": True}
                    forwarded = False

                    def _fwd(ev: dict) -> None:
                        nonlocal forwarded
                        forwarded = True
                        on_delta(ev)

                    try:
                        if until is None and not stall:
                            resp = _consume_stream(client(prov).chat.completions.create(model=model_name, messages=msgs, **skw), _fwd)
                        else:
                            resp = _guarded_stream(lambda: client(prov).chat.completions.create(model=model_name, messages=msgs, **skw),
                                                   _fwd, until, stall)
                    except Exception:
                        if forwarded:
                            on_delta({"type": "restart"})
                        raise
                else:
                    resp = client(prov).chat.completions.create(model=model_name, messages=msgs, **ckw)
                resp._model_used = m  # type: ignore[attr-defined]
                _record_usage(m, getattr(resp, "usage", None), usage_cost(resp))
                return resp
            except RateLimitError as e:
                last = e
                if _is_daily_quota(e):
                    log.warning("daily quota exhausted for %s, falling back", m)
                    _exhausted.add(m)
                    break
                log.warning("429 (attempt %s, %s)", attempt + 1, m)
                if not is_last:
                    # single-provider models (OpenRouter GLM): one short backoff retry, then the next model of the chain
                    if attempt == 0 and (deadline is None or time.time() + 2 < deadline):
                        time.sleep(2.0)
                        continue
                    _cooldown[m] = time.time() + 30
                    break
                pause = delay * 4
                if attempt >= retries or (deadline is not None and time.time() + pause > deadline):
                    break
                time.sleep(pause)
                delay *= 2
            except (APIConnectionError, APITimeoutError, InternalServerError, StallTimeout) as e:  # transient
                last = e
                log.warning("llm transient error (attempt %s, %s): %s", attempt + 1, m, str(e)[:200])
                stalled = isinstance(e, (APITimeoutError, StallTimeout)) and ckw is not kw
                if stalled and ((isinstance(e, StallTimeout) and str(e).startswith("deadline"))
                                or (s.llm_deadline_cap and deadline is not None and time.time() >= deadline - 0.5)):
                    raise LLMUnavailable("turn deadline reached") from e  # the turn's time is over, not the provider's fault
                if stalled:
                    # a stalled provider: no second wait on the same one — the next model of the chain (or give up)
                    _cooldown[m] = time.time() + 60
                    break
                if not is_last:
                    # 502 upstream / timeouts: one quick retry on the same model before falling back
                    if attempt == 0 and (deadline is None or time.time() + 1 < deadline):
                        time.sleep(1.0)
                        continue
                    _cooldown[m] = time.time() + 20
                    break
                if attempt >= retries or (deadline is not None and time.time() + delay > deadline):
                    break
                time.sleep(delay)
                delay *= 2
            except Exception as e:  # auth / bad request etc.
                last = e
                if _is_credit_error(e) and "in-flight" in str(e) and attempt == 0 and (deadline is None or time.time() + 2 < deadline):
                    time.sleep(2.0)  # OpenRouter: credit reserved by parallel requests — retry once after they settle
                    continue
                log.warning("llm error (%s): %s", m, str(e)[:300])
                break
    raise LLMUnavailable(str(last)[:300] if last else "no model available")


def json_content(resp) -> dict:
    """JSON object from a chat response (tolerates ```json fences / text around it)."""
    import json
    import re

    raw = (resp.choices[0].message.content or "").strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise json.JSONDecodeError("no JSON object", raw, 0)
    return json.loads(m.group(0))


def usage_cost(resp) -> float:
    """USD cost of a response as reported by OpenRouter (`usage.cost`); 0 when the provider does not report it."""
    u = getattr(resp, "usage", None)
    try:
        return float(getattr(u, "cost", None) or (u.model_extra or {}).get("cost") or 0.0) if u else 0.0
    except (TypeError, ValueError, AttributeError):
        return 0.0


def reasoning_kwargs(effort: str | None) -> dict:
    return {"reasoning_effort": effort} if effort else {}


def hedged_call(call: Callable[[str], Any], chain: list[str], after: float, budget: float, pool: Any = None,
                what: str = "llm") -> Any:
    """Hedged request (RERANK_HEDGE_AFTER_S, USER_VISION_HEDGE_AFTER_S): `call(chain[0])` alone for `after` s, then
    `call(<rest of the chain>)` in parallel; the first valid answer within `budget` s wins, the slower one is dropped.
    A provider that stalls costs `after` seconds instead of the whole budget. None — nothing in time."""
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    global _hedge_pool
    if pool is None:
        if _hedge_pool is None:
            _hedge_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="hedge")
        pool = _hedge_pool
    end = time.time() + (budget if budget and budget > 0 else 60.0)

    def first_ok(done) -> Any:
        for f in done:
            try:
                return f.result()
            except LLMUnavailable as e:  # this call failed: the other one may still answer
                log.warning("hedged %s call failed: %s", what, str(e)[:120])
        return None

    pending = {pool.submit(contextvars.copy_context().run, call, chain[0])}
    done, pending = wait(pending, timeout=max(0.0, min(after, end - time.time())))
    r = first_ok(done)
    if r is not None:
        return r
    if time.time() < end and len(chain) > 1:
        pending.add(pool.submit(contextvars.copy_context().run, call, ",".join(chain[1:])))
    while pending and time.time() < end:
        done, pending = wait(pending, timeout=max(0.0, end - time.time()), return_when=FIRST_COMPLETED)
        r = first_ok(done)
        if r is not None:
            return r
    log.warning("%s exceeded %.1f s (hedged)", what, budget)
    return None


_hedge_pool = None
