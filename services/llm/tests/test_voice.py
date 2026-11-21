"""Voice messages (POST /transcribe): audio goes to the model as `input_audio`, the transcript comes back as text."""

import base64
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import rag_service.api.app as app_mod
import rag_service.voice as voice
from rag_service.llm import LLMUnavailable

OGG = base64.b64encode(b"OggS" + b"\x00" * 200).decode()


def _resp(text, model="google/gemini-3.8-flash"):
    r = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
    r._model_used = model
    return r


@pytest.fixture
def client():
    return TestClient(app_mod.app)


def test_voice_is_sent_as_input_audio(monkeypatch):
    calls = []

    def fake_chat(**kw):
        calls.append(kw)
        return _resp("  Как перевести сделку на стадию «Пауза»?  ")

    monkeypatch.setattr(voice, "chat", fake_chat)
    out = voice.transcribe(OGG, "audio/ogg")
    assert out == {"text": "Как перевести сделку на стадию «Пауза»?", "model": "google/gemini-3.8-flash"}
    part = calls[0]["messages"][1]["content"][0]
    assert part == {"type": "input_audio", "input_audio": {"data": OGG, "format": "ogg"}}
    assert calls[0]["temperature"] == 0
    assert calls[0]["reasoning_effort"] == "low", "RERANK_REASONING_EFFORT=none Gemini отвергает"


@pytest.mark.parametrize(("mime", "fmt"), [("audio/ogg", "ogg"), ("audio/mpeg", "mp3"), ("audio/x-m4a", "m4a"),
                                           ("audio/wav", "wav"), ("audio/ogg; codecs=opus", "ogg")])
def test_formats(mime, fmt):
    assert voice.audio_format(mime) == fmt


def test_quoted_transcript_is_unquoted(monkeypatch):
    monkeypatch.setattr(voice, "chat", lambda **kw: _resp('"Где отчёт по воронке?"'))
    assert voice.transcribe(OGG, "audio/ogg")["text"] == "Где отчёт по воронке?"


def test_endpoint_returns_text(monkeypatch, client):
    monkeypatch.setattr(voice, "chat", lambda **kw: _resp("Где отчёт?"))
    r = client.post("/transcribe", json={"mime": "audio/ogg", "data_base64": OGG})
    assert r.status_code == 200 and r.json()["text"] == "Где отчёт?"


@pytest.mark.parametrize("body", [{"mime": "video/mp4", "data_base64": OGG},
                                  {"mime": "audio/ogg", "data_base64": "не base64!"},
                                  {"mime": "audio/ogg", "data_base64": ""}])
def test_unreadable_audio_is_422(monkeypatch, client, body):
    monkeypatch.setattr(voice, "chat", lambda **kw: pytest.fail("the model must not be called"))
    assert client.post("/transcribe", json=body).status_code == 422


def test_too_large_audio_is_422(monkeypatch, client):
    monkeypatch.setattr(voice, "MAX_AUDIO_BYTES", 10)
    monkeypatch.setattr(voice, "chat", lambda **kw: pytest.fail("the model must not be called"))
    assert client.post("/transcribe", json={"mime": "audio/ogg", "data_base64": OGG}).status_code == 422


def test_no_model_is_503(monkeypatch, client):
    def down(**kw):
        raise LLMUnavailable("all models failed")

    monkeypatch.setattr(voice, "chat", down)
    assert client.post("/transcribe", json={"mime": "audio/ogg", "data_base64": OGG}).status_code == 503


def test_token_required(monkeypatch, client):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("SERVICE_API_TOKEN", "svc")
    from rag_service.config import get_settings

    get_settings.cache_clear()
    try:
        r = client.post("/transcribe", json={"mime": "audio/ogg", "data_base64": OGG})
        assert r.status_code == 401
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
