"""Settings from environment (.env). One default project in V1 (RK-4, FR-ARCH-03)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]  # services/llm: prompts/, config/, data/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- project (FR-ARCH-01..03) ---
    default_project_id: str = "default"
    bot_name: str = "DocHelper"
    product_name: str = "вашей компании"

    # --- LLM (OpenAI-compatible API; base_url lets you point to any compatible endpoint) ---
    # LLM_PROVIDER: openrouter | gemini | openai (any OpenAI-compatible endpoint via LLM_BASE_URL).
    # A model in a chain may carry an explicit provider prefix, e.g. "gemini/gemini-3.5-flash" — that call goes to
    # Gemini with GEMINI_API_KEY (or EMBEDDING_API_KEY) even when the main provider is OpenRouter (cross-provider fallback).
    llm_provider: str = "openai"
    llm_api_key: str = ""
    llm_base_url: str | None = None
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_max_tokens: int = 8000  # cap per call (OpenRouter reserves credit for max_tokens; reasoning models need room)
    agent_model: str = "gpt-4.1-mini"
    agent_reasoning_effort: str | None = None  # e.g. "low" for reasoning models
    rerank_reasoning_effort: str | None = None  # reranker / classification / FAQ checks (GLM: reasoning is mandatory)
    rerank_model: str = "gpt-4.1-mini"
    vision_model: str = "gpt-4.1-mini"  # indexing-time image descriptions (FR-ING-04), cached on disk
    user_vision_model: str = ""  # user screenshots at question time (FR-VIS-03); empty → vision_model
    # reasoning effort of that call; empty → HEAVY_REASONING_EFFORT (as before). Inkling rejects «none» (400 «Reasoning is
    # mandatory») and the call falls back to the next model — e.g. «low» keeps Inkling
    user_vision_reasoning_effort: str = ""
    # >0: the first model of USER_VISION_MODEL has this long, then the rest of the chain runs in parallel (hedged request;
    # GLM's mandatory reasoning makes single readings 2–20 s). 0 = off: one call, fallback only on errors
    user_vision_hedge_after_s: float = 0.0
    # voice messages from the bot (POST /transcribe): a model chain that accepts audio input (OpenRouter `input_audio`)
    transcribe_model: str = "google/gemini-3.8-flash"
    transcribe_timeout_s: float = 60.0
    # Gemini rejects disabled reasoning («Reasoning is mandatory»), so RERANK_REASONING_EFFORT=none must not leak here
    transcribe_reasoning_effort: str = "low"
    summary_model: str = "gpt-4.1-mini"
    llm_timeout_s: float = 40.0
    llm_max_retries: int = 2
    # latency (Docs/latency-2026-11-15.md): a stalled provider must not hold the turn. >0: no byte from the provider for this
    # long (streamed or not) → the call is dropped and the next model of the chain answers, without a retry on the same one.
    # On by default since the confirmation run (Docs/latency-2026-11-15.md, «Подтверждение»); 0 = off
    llm_stall_timeout_s: float = 10.0
    llm_deadline_cap: bool = True  # every call of a turn is cut at the turn's deadline (streams too), not only checked between steps
    llm_rpm: int = 0  # client-side requests/minute per model (0 = unlimited)
    vision_workers: int = 4
    vision_retries: int = 5

    # --- embeddings (FR-RET-05) ---
    embedding_provider: str = "openai"  # openai | openrouter | fastembed
    embedding_model: str = "text-embedding-3-small"
    embedding_api_key: str = ""
    embedding_base_url: str | None = None
    embedding_dim: int | None = None  # requested output dimensionality (if supported)
    embedding_items_per_min: int = 0  # client-side limiter (0 = off); e.g. 90 for free-tier Gemini

    # --- storage ---
    qdrant_url: str | None = None  # server mode, e.g. http://qdrant:6333
    qdrant_path: str = str(ROOT / "var" / "qdrant")  # local mode fallback (dev/tests)
    qdrant_collection: str = "kb_chunks"
    # --- model routing via OpenRouter (agent/router.py). Chain entries «model@Provider» pin one provider
    # ({"only": [Provider], "sort": "throughput", "allow_fallbacks": false}); the next entry is the fallback.
    routing_enabled: bool = True
    fast_model: str = "deepseek/deepseek-v4.1-flash-1017@Baseten,deepseek/deepseek-v4.1-flash-1017@Wafer,z-ai/glm-5.3-flash"
    fast_reasoning_effort: str = "none"
    heavy_model: str = "thinkingmachines/inkling-2-small,z-ai/glm-5.3-flash"
    heavy_reasoning_effort: str = "low"
    route_fast_max_chars: int = 120
    route_fast_max_words: int = 16
    route_fast_min_score: float = 0.7  # reranker score (0..1) of the best fragment
    route_fast_min_gap: float = 0.15  # top1 − top2 when several fragments look relevant
    allow_collection_recreate: bool = False  # a dim change drops ALL projects' vectors — only on explicit consent
    redis_url: str | None = None  # redis://redis:6379/0 ; empty -> in-process memory store
    session_ttl_s: int = 6 * 3600
    state_dir: str = str(ROOT / "var")
    kb_dir: str = str(ROOT / "var" / "uploads")
    # Confluence adapter sources: JSON {source_id: {"project_id": ...}} (Docs/contract/confluence-batches.md)
    confluence_sources: str = ""
    confluence_control_url: str = ""
    confluence_control_token: str = ""
    confluence_import_timeout_s: float = 900.0
    vision_cache_dir: str = str(ROOT / "data" / "vision_cache")
    # descriptions cached before the model became part of the cache key: true = use them whatever model wrote
    # them; false = only if that model is in the VISION_MODEL chain (otherwise the image is described again)
    vision_cache_legacy: bool = False
    # how a knowledge-base picture becomes text (ingest/vision.py): vlm — vision model only; vlm+ocr — plus the verbatim
    # lines of classic OCR (ingest/ocr.py, PP-OCRv5 eslav, CPU); ocr — OCR only, no vision model
    vision_mode: str = "vlm"
    vision_prompt: str = "v1"  # v1 | v2 (diagram: every transition, both branches of each decision)
    ocr_models_dir: str | None = None  # PP-OCRv5 files (ingest/ocr.py MODEL_FILES); None → the rapidocr package folder

    # --- chunking ---
    chunk_max_tokens: int = 650
    chunk_target_tokens: int = 420
    table_max_tokens: int = 500

    # --- retrieval (FR-RET-03/04) ---
    candidate_k: int = 12  # 24 → 12: the same retrieval quality on the bench, half the reranker's input
    context_top_k: int = 6
    rrf_k: int = 60
    rerank_mode: str = "llm"  # llm | none
    rerank_timeout_s: float = 4.0  # past this the search keeps the fused order (0 = wait for the reranker)
    # >0: the reranker's first model has this long; then the rest of the chain is asked in parallel and the first valid answer
    # wins (hedged request; the slower call's result is dropped). 0 = off (one call, chain fallback only on errors)
    rerank_hedge_after_s: float = 1.5
    # >0: the query embedding gets this timeout (2 attempts) and, if it still fails, the search runs on BM25 only instead of
    # waiting up to minutes for the embedding API (14–15.11: one search took 246 s). 0 = as before (60 s, 6 attempts)
    retrieval_dense_timeout_s: float = 4.0

    # --- agent limits (FR-AGT-04) ---
    max_tool_calls_per_turn: int = 4
    pre_search: bool = False  # retrieval-first search before the first LLM step (off: eval showed less complete answers)
    max_llm_steps_per_turn: int = 6
    agent_temperature: float = 0.1  # agent LLM steps (eval 15.11: 0.0 vs 0.1, see Docs/overnight-2026-11-15.md)
    agent_search_before_no_facts: bool = True  # a domain question answered «no_facts» / clarified before any search → one retry with search
    # FR-GEN-06: a condition / route question citing a process diagram must name its decisions (guardrails.branch_gap);
    # otherwise one retry with the missing ones
    answer_branch_check: bool = True
    turn_timeout_s: float = 45.0
    turn_token_budget: int = 150000
    dialog_token_budget: int = 400000
    history_verbatim_messages: int = 8

    # --- confidence (FR-CONF) ---
    min_evidence_score: float = 0.35  # minimal rerank score (0..1) for any factual answer
    conf_high: float = 0.7
    conf_medium: float = 0.45

    # --- support shift (FR-ESC-05): out-of-hours behaviour of escalation and low-confidence answers ---
    support_hours: str = "mon-fri 09:00-18:00"
    support_tz: str = "Europe/Moscow"

    # --- answer cache (NFR-01, FR-FAQ-04 level 1: exact match, invalidated by generation) ---
    answer_cache_enabled: bool = True
    answer_cache_ttl_s: int = 24 * 3600

    # --- semantic FAQ cache, level 2 (FR-FAQ-01..08) ---
    faq_enabled: bool = True
    faq_collection: str = "faq_cache"  # Qdrant collection: one point per question formulation
    faq_window_days: int = 14  # FR-FAQ-01: sliding window of questions
    faq_top_k: int = 20  # FR-FAQ-01: K
    faq_min_cluster_size: int = 2  # a cluster needs at least N questions to be «frequent»
    # gemini-embedding-001 (1536): paraphrases 0.82–0.99, «same words, different object» up to 0.86 — so the cosine
    # only shortlists; the key-entity check and a cheap LLM equivalence check decide (calibrated, see Docs/faq-cache.md)
    faq_cluster_threshold: float = 0.88  # cosine to join a cluster without a check (FR-FAQ-01)
    faq_cluster_grey: float = 0.82  # grey zone [grey, threshold): join only if the LLM confirms equivalence
    faq_match_threshold: float = 0.84  # cosine for a cache candidate (FR-FAQ-04 step 2)
    faq_half_life_days: float = 7.0  # time decay of frequency (FR-FAQ-01)
    faq_auto_ttl_s: int = 7 * 24 * 3600  # FR-FAQ-05: auto entries live no longer than TTL
    faq_dislike_threshold: int = 3  # FR-FAQ-05: 👎 on cache answers → entry disabled
    faq_verify_llm: bool = True  # FR-FAQ-04 step 3: cheap model confirms equivalence
    faq_verify_model: str = ""  # empty → rerank_model
    faq_canonical_llm: bool = True  # FR-FAQ-01: LLM phrases the canonical question of a cluster
    faq_recompute_interval_s: int = 0  # background recompute (e.g. 3600); 0 = only on demand (POST /faq/recompute)

    # --- analytics (FR-AN-02..05) ---
    classify_enabled: bool = True  # FR-AN-04: async LLM classification of each request
    classify_model: str = ""  # empty → summary_model
    classify_prompt: str = "v2"  # v1 (old) | v2: topic descriptions + explicit off-topic rule (eval/clustering/unsure_llm.py)
    classify_batch: int = 20
    classify_interval_s: int = 120  # background worker period; 0 = only on demand
    llm_price_in_per_mtok: float = 0.0  # USD per 1M prompt tokens (cost estimate; free tier = 0)
    llm_price_out_per_mtok: float = 0.0

    # --- question classification + clustering (analytics/questions.py): intent / topic / complexity / on-topic
    # without an extra LLM call; cluster assigned right after the turn (nearest centroid), rebuilt in the background
    questions_enabled: bool = True
    # thresholds calibrated on 518 synthetic questions, 6 seeds + 259 through the live pipeline: eval/clustering/report.md
    question_assign_threshold: float = 0.82  # cosine to the nearest cluster centroid; below → «unclustered» until the rebuild
    question_cluster_threshold: float = 0.82  # rebuild: cosine to join a cluster (0.80 → 0.82 on the golden-set log, eval/clustering/report.md)
    question_merge_threshold: float = 0.86  # rebuild: clusters with closer centroids are merged
    question_pair_threshold: float = 0.0  # 2nd pass: mutual-nearest unclustered pairs at cos ≥ this (gemini: 0.80 = SO recall +7 pp, golden −1 pure cluster); 0 = off
    question_min_cluster_size: int = 2  # smaller groups stay unclustered
    question_refine_passes: int = 2  # rebuild: reassignment passes to the nearest centroid
    question_id_share: float = 0.5  # rebuild: a cluster keeps an old id when ≥ this share of its members carried it
    question_id_centroid: float = 0.9  # … or when the old centroid is at least this close (cosine)
    question_entity_guard: bool = True  # questions with different error codes (BKS-1001 / BKS-1002) never share a cluster
    question_gap_share: float = 0.5  # a cluster «needs docs» when ≥ this share of its questions got no good answer / 👎
    # answer clusters (analytics/answers.py, eval/clustering/answer_clusters.py): questions grouped by question + answer + cited
    # sections → FAQ / cache candidates, documentation gaps, merge suggestions, answer consistency in the digest and the panel
    answer_clusters_enabled: bool = False
    answer_cluster_question_weight: float = 0.7  # share of the question embedding; the rest: answer text and sections, half each
    answer_cluster_threshold: float = 0.84  # gemini-embedding-001, 2-fold CV on the golden log (eval/clustering/answer_clusters.py); 0 = question threshold
    answer_faq_min_size: int = 3
    answer_faq_min_answered: float = 0.8
    answer_faq_min_consistency: float = 0.5  # mean pairwise Jaccard of cited sections inside the cluster
    # input guardrails (rag_service/guard.py, Docs/guardrails.md): what reaches the agent at all
    guard_enabled: bool = True
    guard_max_chars: int = 2000  # longer messages are refused (golden max ≈ 230; jailbreak prompts: median ≈ 1500)
    guard_flood_window_s: int = 60
    guard_flood_max: int = 12  # more messages per session per window → «flood»
    guard_flood_repeat: int = 3  # the same text more often per window → «flood»
    guard_embed_timeout_s: float = 2.0  # L2 is skipped if the embedder is slower (the answer path must not wait)
    guard_attack_margin: float = 0.15  # L2 (calibrated on the dev split, eval/guard): max cos to known attacks − max cos to normal questions; ≥ this → block
    guard_attack_margin_doubt: float = -0.03  # ≥ this → ask the LLM (L3); eval/guard/llm_layer.py (was 0.0)
    guard_offtopic_conf: float = 0.97  # L2: classifier P(off-topic) ≥ this and no subject words → block; 0 = never block off-topic
    guard_offtopic_doubt: float = 0.85  # ≥ this → ask the LLM (L3)
    guard_llm_enabled: bool = True  # L3 only for the doubtful band
    guard_llm_model: str = ""  # empty → classify_model → summary_model
    guard_llm_timeout_s: float = 6.0
    guard_llm_prompt: str = "v1"  # v1 | v2 (guard.LLM_PROMPTS; eval/guard/llm_layer.py)
    question_model_enabled: bool = True  # trained classifier (analytics/qmodel.npz) on top of the rules; skipped for another embedder
    question_model_min_conf: float = 0.5  # intent / on_topic from the model only with probability ≥ this
    question_model_topic_conf: float = 0.5  # topic from the model at ≥ this, else the LLM classifier (rag_classes) / rules
    question_model_unsure_conf: float = 0.7  # on_topic below this probability is «unsure»: the async LLM classifier decides (0 = off); eval/clustering/unsure_llm.py
    question_llm_topic_over_rules: bool = False  # when the model is unsure of the topic: keyword topic (False) or the LLM classifier's (True); without the model the LLM's is used
    question_urgent_rule: bool = True  # an explicit urgency marker (qmodel._URGENT) makes a question urgent even if the model says normal (eval/clustering/exp_tone.py)
    question_spike_z: float = 3.0  # trends: a day is a spike at Poisson z ≥ this over the previous 7 days' mean …
    question_spike_min: int = 4  # … and at least this many questions that day
    # analytics embedder: thresholds above are for EMBEDDING_MODEL; another model (fallback / a change) takes its own
    # calibrated thresholds from analytics/embedder.py (THRESHOLDS) and logs a warning when it has none
    question_fallback_embedder: str = "BAAI/bge-m3"  # local ONNX (fastembed) when the main embedder fails / 429; "" = off
    question_fallback_cache_dir: str | None = None  # model files (Docker image: /opt/models); None → fastembed default
    question_fallback_cooldown_s: int = 900
    question_embed_timeout_s: float = 8  # analytics waits for the main embedder this long (per 32 texts), then falls back; 0 = wait  # after a failure of the main embedder, analytics uses the fallback this long
    question_cluster_days: int = 30  # rebuild window
    question_cluster_interval_s: int = 3600  # background rebuild period; 0 = only on demand
    question_label_llm: bool = True  # short Russian label of a new / changed cluster (cheap model, only on rebuild)
    question_label_model: str = ""  # empty → classify_model → summary_model
    question_label_prompt: str = "v2"  # v1 | v2 (analytics/questions.LABEL_PROMPTS; eval/clustering/labels_eval.py)
    question_label_max: int = 30  # LLM labels per rebuild (the rest get the medoid question)
    # optional `user_ref` on /ask: a salted hash made by the bot (never a Telegram ID, NFR-05). Used only to count
    # distinct people per cluster / cached answer and to spot repeated questions; no per-user profiles
    question_user_ref_enabled: bool = False
    question_repeat_hours: float = 24  # the same person asks again in the same cluster → the answer did not help
    question_digest_tz: str = "Europe/Moscow"  # GET /analytics/daily-digest: calendar day in this zone
    digest_webhook_url: str = ""  # optional end-of-day push of the digest (panel events endpoint); empty = off
    digest_webhook_token: str = ""  # sent as X-Service-Token
    docs_webhook_url: str = ""  # FR-ADM-05: `docs.updated` event after a Git sync changed documents (rag_service/notify.py); empty = off
    docs_webhook_token: str = ""  # sent as X-Service-Token
    question_digest_delay_min: int = 10  # push yesterday's digest this many minutes after midnight
    # level-1 cache: hits are counted, a hit extends the TTL (hot answers stay), size is bounded (cold ones go first)
    answer_cache_max_entries: int = 2000
    answer_cache_sliding_ttl: bool = True

    # --- Git repositories as a knowledge source (FR-GIT-01..07) ---
    git_max_file_bytes: int = 5_000_000  # FR-GIT-07: per-file limit
    git_max_files: int = 500  # FR-GIT-07: files per import
    git_poll_interval_s: int = 0  # FR-GIT-03: polling when webhooks are unavailable; 0 = off
    git_timeout_s: float = 30.0
    public_base_url: str = "http://localhost:8080"  # used to show the webhook URL (FR-GIT-05) and in document links (FR-GEN-02)
    doc_links: bool = True  # FR-GEN-02: sources of uploaded documents link to /documents/{id}/view#section or the PDF page
    doc_link_secret: str = ""  # HMAC key for document links (empty: derived from SERVICE_API_TOKEN)

    # --- retrieval / visual extras ---
    retrieval_neighbors: bool = True  # FR-RET-07: add steps N−1 / N+1 of the same section
    # FR-RET-07: a found subsection brings the first fragments of a sibling subsection (same parent) whose title shares a
    # word stem with the query — a broad question («как работает фильтр») sees every described way, not only one
    retrieval_siblings: bool = True
    retrieval_sibling_chunks: int = 2  # fragments taken from each matching sibling
    user_image_prepass: bool = True  # FR-VIS-03: VLM reads the user's screenshot → search query
    user_image_ocr: bool = False  # + verbatim lines of classic OCR (ingest/ocr.py) next to the VLM reading

    prompt_file: str = str(ROOT / "prompts" / "agent_system.md")
    product_file: str = str(ROOT / "config" / "product.yaml")  # product-specific reference data (FR-ARCH-03)
    max_images_per_answer: int = 3
    attach_cited_images: bool = True  # FR-VIS-02: an answer citing an image fragment carries that image

    # --- auth: every endpoint except /health needs a token (fail closed) ---
    service_api_token: str = ""  # bot -> /ask, /feedback, /knowledge, /images, /sessions
    admin_api_token: str = ""  # panel -> documents, indexing, journal, analytics (also accepted on service endpoints)
    auth_disabled: bool = False  # explicit opt-out for local development only

    # --- relational storage: turns, feedback, jobs (FR-AN-01, FR-AGT-05). Postgres in compose, sqlite in dev ---
    database_url: str | None = None  # postgresql+pg8000://user:pass@postgres:5432/rag ; empty -> sqlite in STATE_DIR

    # --- streaming (NFR-01): the final answer is checked and emitted paragraph by paragraph ---
    agent_streaming: bool = True
    llm_stream_usage: bool = True  # ask the provider for token usage in the last stream chunk

    # --- start-up (FR-ADM-02) and persistent indexing jobs ---
    auto_index_on_start: bool = False
    resume_jobs_on_start: bool = True

    # --- cost of a turn when the provider does not report it: per-model prices (overrides LLM_PRICE_* below) ---
    model_prices: str = ""  # JSON: {"model": [usd_per_1M_input_tokens, usd_per_1M_output_tokens], ...}

    # --- knowledge from operators' answers (FR-ESC-06) and screenshot fragments (FR-ING-06) ---
    support_answers_dir: str = "support-answers"  # default section for answers saved from support (FR-ESC-06)


@lru_cache
def get_settings() -> Settings:
    return Settings()
