import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# unit tests never touch real services
os.environ["REDIS_URL"] = ""  # forced: a sourced .env must never point tests at real services
os.environ["QDRANT_URL"] = ""
import tempfile  # noqa: E402

_tmp = tempfile.mkdtemp(prefix="rag_service_test_")
os.environ["STATE_DIR"] = os.path.join(_tmp, "var")
os.environ["DATABASE_URL"] = ""
os.environ["AUTH_DISABLED"] = "true"  # token checks are covered explicitly in test_api.py
os.environ["CLASSIFY_INTERVAL_S"] = "0"
os.environ["QUESTIONS_ENABLED"] = "false"  # question clustering is switched on in test_questions.py only
os.environ["QUESTION_FALLBACK_EMBEDDER"] = ""  # no local model download in tests (test_insights.py fakes it)
os.environ["GUARD_ENABLED"] = "false"  # input guardrails are tested in test_guard.py
os.environ["PRODUCT_FILE"] = str(ROOT / "config" / "product.demo-bars.yaml")  # tests run against the demo knowledge base
os.environ["SUPPORT_HOURS"] = "mon-fri 09:00-18:00"
os.environ["QDRANT_PATH"] = os.path.join(_tmp, "qdrant")
os.environ["KB_DIR"] = os.path.join(_tmp, "kb")
os.environ["FAQ_VERIFY_LLM"] = "false"
os.environ["FAQ_CANONICAL_LLM"] = "false"
os.environ["CLASSIFY_INTERVAL_S"] = "0"
os.environ["LLM_PROVIDER"] = "openai"
os.environ["LLM_API_KEY"] = "test"
# latency flags are on by default in production; unit tests pin them off and switch them on explicitly (test_latency_flags.py)
os.environ["LLM_STALL_TIMEOUT_S"] = "0"
os.environ["LLM_DEADLINE_CAP"] = "false"
os.environ["RETRIEVAL_DENSE_TIMEOUT_S"] = "0"
os.environ["RERANK_HEDGE_AFTER_S"] = "0"
