"""Voice messages from the bot → text (POST /transcribe).

The audio goes to a chat model that accepts audio input (OpenRouter `input_audio`), through the same `chat()` as every
other call: model chain, retries, usage accounting. Telegram voice notes are OGG/Opus; they are sent as they are, no
conversion. The transcript then goes into the dialog as an ordinary text question — retrieval and guardrails stay
the same.
"""

from __future__ import annotations

import base64
import logging
import time

from ..core.config import get_settings
from ..llm import LLMUnavailable, chat

log = logging.getLogger(__name__)

# mime of the file → `input_audio.format`
FORMATS = {
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/oga": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
}

# Up to ~10 minutes of a Telegram voice note (OGG/Opus ≈ 16–32 kbit/s) with a wide margin
MAX_AUDIO_BYTES = 20 * 1024 * 1024

SYSTEM = (
    "Ты расшифровываешь голосовое сообщение пользователя службы поддержки. Запиши дословно, что сказано, на языке "
    "оригинала, с обычной пунктуацией. Названия продуктов, кнопок, модулей и английские термины пиши так, как их "
    "принято писать (латиницей, если говорят по-английски). Ничего не добавляй, не отвечай на вопрос и не "
    "комментируй. Если речи нет или ничего не разобрать — верни пустую строку."
)


class AudioRejected(ValueError):
    """The file cannot be transcribed: unknown format or too large."""


def audio_format(mime: str) -> str:
    fmt = FORMATS.get((mime or "").split(";")[0].strip().lower())
    if fmt is None:
        raise AudioRejected(f"unsupported audio type: {mime!r}")
    return fmt


def transcribe(data_base64: str, mime: str) -> dict:
    """Transcript of one audio file: {"text", "model"}. `LLMUnavailable` — no model could do it."""
    s = get_settings()
    fmt = audio_format(mime)
    try:
        size = len(base64.b64decode(data_base64, validate=True))
    except ValueError as e:
        raise AudioRejected("audio is not valid base64") from e
    if not size:
        raise AudioRejected("empty audio")
    if size > MAX_AUDIO_BYTES:
        raise AudioRejected(f"audio is too large: {size} bytes")
    started = time.time()
    resp = chat(
        model=s.transcribe_model,
        retries=1,
        temperature=0,
        reasoning_effort=s.transcribe_reasoning_effort or None,
        deadline=started + s.transcribe_timeout_s,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": data_base64, "format": fmt}}]},
        ],
    )
    text = (resp.choices[0].message.content or "").strip()
    if text.startswith('"') and text.endswith('"') and len(text) > 1:
        text = text[1:-1].strip()  # some models quote the transcript
    model = getattr(resp, "_model_used", None)
    log.info("transcribed %s bytes of %s in %.1fs with %s: %s chars", size, fmt, time.time() - started, model, len(text))
    return {"text": text, "model": model}


__all__ = ["AudioRejected", "LLMUnavailable", "audio_format", "transcribe"]
