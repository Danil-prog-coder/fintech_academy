"""EMBEDDING_PROVIDER=openrouter: OpenRouter key / URL by default and the same cache keys as the direct OpenAI-compatible call."""

from rag_service.config import get_settings
from rag_service.index.embeddings import Embedder


def test_openrouter_provider_shares_cache_keys(monkeypatch, tmp_path):
    s = get_settings()
    for k, v in {"state_dir": str(tmp_path), "embedding_provider": "openrouter", "embedding_model": "google/gemini-embedding-001",
                 "embedding_api_key": "", "embedding_base_url": None, "openrouter_api_key": "test-key",
                 "openrouter_base_url": "https://openrouter.ai/api/v1", "embedding_dim": 1536}.items():
        monkeypatch.setattr(s, k, v)
    e = Embedder()
    assert str(e._client.base_url).startswith("https://openrouter.ai/api/v1")
    monkeypatch.setattr(s, "embedding_provider", "openai")
    monkeypatch.setattr(s, "embedding_model", "gemini-embedding-001")
    monkeypatch.setattr(s, "embedding_base_url", "https://generativelanguage.googleapis.com/v1beta/openai/")
    assert Embedder()._key("вопрос") == e._key("вопрос")  # Gemini direct and OpenRouter share the disk cache
