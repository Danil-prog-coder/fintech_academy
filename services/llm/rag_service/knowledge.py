"""KnowledgeWriter (FR-ESC-06): a question answered by a duty operator becomes part of the knowledge base.

The pair is written as a small Markdown document into the knowledge-base folder (source «Ответ
поддержки, <дата>») and goes through the ordinary indexing pipeline, so it is searched, cited and
versioned like any other document. Image descriptions and embeddings of unchanged documents come
from the caches, so the re-index is cheap.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import sqlalchemy as sa

from . import db, jobs
from .config import get_settings
from .ingest.util import slugify


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def save_knowledge(project_id: str, question: str, answer: str, author: str | None = None, wait: bool = False) -> dict:
    s = get_settings()
    q, a = _one_line(question), (answer or "").strip()
    if not q or not a:
        raise ValueError("question and answer are required")
    now = time.time()
    day = time.strftime("%d.%m.%Y", time.localtime(now))
    folder = Path(s.kb_dir) / s.support_answers_dir
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}-{slugify(q, 40)}.md"
    title = f"Ответ поддержки, {day}"
    # a heading must not start a new front matter or break the Markdown structure
    heading = q.replace("#", "").strip()
    body = "\n".join(line if not line.startswith("#") else line.lstrip("# ") for line in a.splitlines())
    (folder / name).write_text(
        f"---\ntitle: {title}\nsource_type: support\nanswered_at: {day}\n---\n# {heading}\n\n"
        f"Вопрос пользователя: {q}\n\nОтвет специалиста поддержки ({day}):\n\n{body}\n", encoding="utf-8")
    job = jobs.start("knowledge", [s.kb_dir], project_id, wait=wait)
    db.execute(sa.insert(db.knowledge).values(ts=now, project_id=project_id, question=q, answer=a, author=(author or "")[:128] or None,
                                              file=f"{s.support_answers_dir}/{name}", job_id=job.get("job_id")))
    return {"file": f"{s.support_answers_dir}/{name}", "title": title, "job": job}
