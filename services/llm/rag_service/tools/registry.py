"""Tools (Miro S95, FR-AGT-02): JSON schemas for function calling + executors bound to a session.

Every fragment returned to the agent gets a session-local source id (S1, S2… for KB chunks; T1… for
deterministic tool results), stored in the session registry so the Guardrails can verify citations.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..config import get_settings
from ..retrieval.kb import get_kb, known_names, match_document, section_chunks
from ..retrieval.search import HybridRetriever
from .bo_link import parse_bo_link
from .filter_syntax import reference as filter_reference
from .filter_syntax import validate_filter

FINAL_TOOLS = {"final_answer", "ask_clarification", "offer_operator", "escalate_to_operator"}

SCHEMAS: list[dict] = [
    {"type": "function", "function": {
        "name": "search_docs",
        "description": "Гибридный поиск (смысловой + по точным словам) с реранкингом по базе знаний. Возвращает фрагменты с source_id, документом, разделом, типом (text/table/image/callout), скором и image_ids, а также сигналы уверенности.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Самостоятельный поисковый запрос на русском; точные токены (номера, операторы, коды) — без изменений"},
            "document": {"type": "string", "description": "Ограничить поиск документом (название или его часть), необязательно"},
            "section": {"type": "string", "description": "Предпочесть раздел (часть пути раздела), необязательно"},
            "chunk_types": {"type": "array", "items": {"type": "string", "enum": ["text", "table", "image", "callout"]}, "description": "Типы фрагментов; image — описания скриншотов и схем"},
            "top_k": {"type": "integer", "description": "Сколько фрагментов вернуть (по умолчанию 6, максимум 8)"},
        }, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "list_documents",
        "description": "Перечень документов базы знаний и их разделов. Используй, чтобы проверить, существует ли в базе объект, названный в вопросе.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_section",
        "description": "Получить раздел документа целиком (все шаги, таблицы, описания картинок) — для вопросов «опиши поэтапно», «все шаги».",
        "parameters": {"type": "object", "properties": {
            "document": {"type": "string", "description": "Название документа"},
            "section_path": {"type": "string", "description": "Номер раздела (как в оглавлении документа) или его название"},
        }, "required": ["document", "section_path"]}}},
    {"type": "function", "function": {
        "name": "attach_image",
        "description": "Приложить к ответу скриншот или схему по image_id из найденных фрагментов (не больше 3 на ответ).",
        "parameters": {"type": "object", "properties": {"image_id": {"type": "string"}}, "required": ["image_id"]}}},
    {"type": "function", "function": {
        "name": "validate_filter",
        "description": "Детерминированная проверка выражения фильтра по справочнику документированного синтаксиса (операторы сравнения, ручной фильтр списком, формат дат). Возвращает проблемы и исправления только из документированного синтаксиса.",
        "parameters": {"type": "object", "properties": {"expression": {"type": "string", "description": "Выражение фильтра из вопроса дословно"}}, "required": ["expression"]}}},
    {"type": "function", "function": {
        "name": "parse_bo_link",
        "description": "Детерминированный разбор внутренней ссылки продукта: документ (транслит → название из базы знаний), ID записи, повреждения (лишние слэши, сломанные параметры, кириллица в ID) и исправленная ссылка.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    # ---- final actions (exactly one per turn) ----
    {"type": "function", "function": {
        "name": "final_answer",
        "description": "Финальный ответ пользователю. Заполняй поля строго в порядке: kind, coverage, citations, image_ids, text — "
                       "сначала источники, потом текст. Для фактов обязательны маркеры [N] в тексте и citations с дословными цитатами.",
        "parameters": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["grounded", "no_facts"], "description": "grounded — ответ с фактами из базы; no_facts — приветствие, small talk, вежливый отказ на вопрос вне тематики"},
            "coverage": {"type": "string", "enum": ["full", "partial", "none"], "description": "Ответ полностью содержится в найденном: full / частично: partial / нет: none"},
            "citations": {"type": "array", "items": {"type": "object", "properties": {
                "n": {"type": "integer"}, "source_id": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["n", "source_id", "quote"]}},
            "image_ids": {"type": "array", "items": {"type": "string"}, "description": "До 3 картинок из найденных фрагментов"},
            "text": {"type": "string", "description": "Текст ответа с маркерами [1], [2]…; абзацы разделяй пустой строкой"},
        }, "required": ["kind", "coverage", "text"]}}},
    {"type": "function", "function": {
        "name": "ask_clarification",
        "description": "Задать один уточняющий вопрос, когда ответ зависит от условия, которого нет в вопросе.",
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}, "description": "2–4 варианта-кнопки"},
        }, "required": ["question"]}}},
    {"type": "function", "function": {
        "name": "offer_operator",
        "description": "Предложить перевод на оператора: по теме продукта ответа в документации нет, он неполный или источники противоречат.",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string", "enum": ["no_answer_in_docs", "conflicting_sources", "low_confidence", "partial_answer"]},
            "message": {"type": "string", "description": "Короткое пояснение пользователю, что именно не найдено"},
        }, "required": ["reason"]}}},
    {"type": "function", "function": {
        "name": "escalate_to_operator",
        "description": "Немедленно передать диалог дежурному оператору.",
        "parameters": {"type": "object", "properties": {
            "reason": {"type": "string", "enum": ["user_request", "needs_human_action", "no_answer_in_docs", "repeated_failure", "user_frustration", "conflicting_sources"]},
            "summary": {"type": "string", "description": "Суть проблемы, что выяснено, что искал и не нашёл, почему передаёшь"},
            "urgency": {"type": "string", "enum": ["low", "normal", "high"]},
        }, "required": ["reason", "summary"]}}},
]

STATUS_TEXT = {
    "search_docs": "Ищу в документации…",
    "list_documents": "Сверяю перечень документов…",
    "get_section": "Открываю раздел целиком…",
    "attach_image": "Подбираю скриншот…",
    "validate_filter": "Проверяю синтаксис фильтра…",
    "parse_bo_link": "Проверяю ссылку…",
}


def status_for(name: str, args: dict) -> str:
    if name == "search_docs" and ("image" in (args.get("chunk_types") or []) or re.search(r"схем|диаграм", args.get("query", ""), re.I)):
        return "Смотрю схему процесса и скриншоты…"
    return STATUS_TEXT.get(name, "Работаю…")


class Tools:
    """Executors bound to (project_id, session). Return (text_for_llm, compact_trace)."""

    def __init__(self, project_id: str, session: dict) -> None:
        self.project_id = project_id
        self.session = session
        self.retriever = HybridRetriever(project_id)
        self.attached_images: list[str] = []
        self.last_query = ""
        self.search_signals: list[dict] = []
        self.search_calls = 0

    # -- registry helpers
    def _register_chunk(self, c: dict, score: float | None) -> str:
        reg = self.session["registry"]
        for sid, v in reg.items():
            if v.get("chunk_id") == c["chunk_id"]:
                if score is not None and (v.get("score") or 0) < score:
                    v["score"] = score
                return sid
        sid = f"S{self.session['next_s']}"
        self.session["next_s"] += 1
        reg[sid] = {
            "kind": "chunk", "chunk_id": c["chunk_id"], "doc_id": c["doc_id"], "document_title": c["document_title"],
            "section_path": c["section_path"], "section_path_str": c["section_path_str"], "step_label": c.get("step_label"),
            "section_number": c.get("section_number"), "chunk_type": c["chunk_type"], "page": c.get("page"), "image_ids": c.get("image_ids") or [],
            "text": c["text"], "score": score, "source_url": c.get("source_url"),
        }
        return sid

    def _register_tool(self, name: str, text: str, section: str) -> str:
        sid = f"T{self.session['next_t']}"
        self.session["next_t"] += 1
        self.session["registry"][sid] = {"kind": "tool", "tool": name, "document_title": "Проверка инструментом " + name,
                                         "section_path_str": section, "text": text, "score": 1.0, "image_ids": [], "chunk_type": "tool"}
        return sid

    @staticmethod
    def _seen(sid: str, c: dict, score: float | None) -> dict:
        """A fragment exactly as the model saw it (tool log for the benchmark run format)."""
        return {"source_id": sid, "document": c["document_title"], "section_path": c["section_path_str"], "page": c.get("page"),
                "chunk_type": c["chunk_type"], "score": score, "text": c["text"], "image_ids": c.get("image_ids") or []}

    def _fmt_chunk(self, sid: str, c: dict, score: float | None) -> str:
        imgs = f" | image_ids: {', '.join(c.get('image_ids') or [])}" if c.get("image_ids") else ""
        sc = f" | score {score:.2f}" if score is not None else ""
        return f"[{sid}] ({c['chunk_type']}) {c['section_path_str']}{sc}{imgs}\n{c['text']}"

    # -- tools
    def search_docs(self, query: str, document: str | None = None, section: str | None = None,
                    chunk_types: list[str] | None = None, top_k: int | None = None) -> tuple[str, dict]:
        self.search_calls += 1
        self.last_query = query
        top_k = max(1, min(int(top_k or get_settings().context_top_k), 8))
        r = self.retriever.search(query, document=document, section=section, chunk_types=chunk_types or None, top_k=top_k)
        self.search_signals.append(r["signals"])
        parts = []
        sig = r["signals"]
        parts.append(f"signals: max_score={sig['max_score']} gap_top1_top2={sig['gap_top1_top2']} n_supporting={sig['n_supporting']} (score: 0..1, ≥0.6 — фрагмент содержит ответ, <{get_settings().min_evidence_score} — доказательств нет)")
        parts.extend(r["notes"])
        ids = []
        for c in r["results"]:
            score = c.get("rerank") if c.get("rerank") is not None else c.get("dense")
            sid = self._register_chunk(c, score)
            ids.append(sid)
            parts.append(self._fmt_chunk(sid, c, score))
        if not r["results"]:
            parts.append("Ничего не найдено.")
        chunks = [self._seen(i, c, c.get("rerank") if c.get("rerank") is not None else c.get("dense")) for i, c in zip(ids, r["results"])]
        for sid, n in self._neighbours(r["results"], ids):
            parts.append(self._fmt_chunk(n["sid"], n["chunk"], None).replace(f"[{n['sid']}]", f"[{n['sid']}] (соседний шаг к {sid})", 1))
            chunks.append(self._seen(n["sid"], n["chunk"], None))
        for sid, n in self._siblings(query, r["results"], ids):
            parts.append(self._fmt_chunk(n["sid"], n["chunk"], None).replace(f"[{n['sid']}]", f"[{n['sid']}] (соседний подраздел к {sid})", 1))
            chunks.append(self._seen(n["sid"], n["chunk"], None))
        return "\n\n".join(parts), {"query": query, "document": document, "results": [(i, c["section_path_str"], c.get("rerank")) for i, c in zip(ids, r["results"])],
                                    "signals": sig, "chunks": chunks}

    def _neighbours(self, results: list[dict], ids: list[str], max_total: int = 3) -> list[tuple[str, dict]]:
        """FR-RET-07: for a found instruction step N, steps N−1 and N+1 of the same section join the context."""
        if not get_settings().retrieval_neighbors or not results:
            return []
        try:
            kb = get_kb(self.project_id)
        except Exception:  # noqa: BLE001
            return []
        by_id = kb.get("by_id") or {}
        found = {c["chunk_id"] for c in results}
        out: list[tuple[str, dict]] = []
        for c, sid in list(zip(results, ids))[:3]:
            if not c.get("step_label") or c.get("chunk_type") not in ("text", "callout"):
                continue
            for d in (-1, 1):
                nid = f"{c['doc_id']}:{c['order'] + d:04d}"
                n = by_id.get(nid)
                if (not n or nid in found or n.get("section_path") != c.get("section_path")
                        or n.get("chunk_type") not in ("text", "callout") or not n.get("step_label")):
                    continue
                found.add(nid)
                out.append((sid, {"sid": self._register_chunk(n, None), "chunk": n}))
                if len(out) >= max_total:
                    return out
        return out

    _SIB_STOP = frozenset({"докум", "работ", "инстр", "функц", "возмо", "разде", "описа", "общие", "допол", "настр"})

    def _siblings(self, query: str, results: list[dict], ids: list[str], max_sections: int = 2) -> list[tuple[str, dict]]:
        """FR-RET-07: for a found subsection X.Y.Z, the first fragments (RETRIEVAL_SIBLING_CHUNKS) of a sibling X.Y.W
        (same parent) whose title shares a 5-letter word stem with the query join the context: a broad question sees every
        described way, not only the best-ranked one. Stems of the document title and of the parent sections are shared by
        every sibling and do not count. Generic: works from the section tree of the knowledge base."""
        s = get_settings()
        if not s.retrieval_siblings or not results:
            return []
        qst = {w[:5] for w in re.findall(r"[а-яёa-z]{5,}", query.lower().replace("ё", "е"))} - self._SIB_STOP
        if not qst:
            return []
        try:
            kb = get_kb(self.project_id)
        except Exception:  # noqa: BLE001
            return []
        per = max(1, s.retrieval_sibling_chunks)
        found = {c["chunk_id"] for c in results}
        have = {(c["doc_id"], tuple(c.get("section_path") or [])) for c in results}
        out: list[tuple[str, dict]] = []
        added = 0
        for c, sid in zip(results, ids):
            sp = tuple(c.get("section_path") or [])
            if len(sp) < 2:
                continue
            common = {w[:5] for w in re.findall(r"[а-яёa-z]{5,}", " ".join([c.get("document_title") or "", *sp[:-1]]).lower().replace("ё", "е"))}
            sibs: dict[tuple, list[dict]] = {}
            for n in kb.get("chunks") or []:
                nsp = tuple(n.get("section_path") or [])
                if (n["doc_id"] != c["doc_id"] or len(nsp) != len(sp) or nsp[:-1] != sp[:-1] or nsp == sp
                        or (n["doc_id"], nsp) in have or n.get("chunk_type") not in ("text", "callout", "table")):
                    continue
                sibs.setdefault(nsp, []).append(n)
            for nsp, ns in sibs.items():
                tst = {w[:5] for w in re.findall(r"[а-яёa-z]{5,}", nsp[-1].lower().replace("ё", "е"))}
                if not (tst & (qst - common)):
                    continue
                have.add((c["doc_id"], nsp))
                for n in sorted(ns, key=lambda x: x["order"])[:per]:
                    if n["chunk_id"] in found:
                        continue
                    found.add(n["chunk_id"])
                    out.append((sid, {"sid": self._register_chunk(n, None), "chunk": n}))
                added += 1
                if added >= max_sections:
                    return out
        return out

    def list_documents(self) -> tuple[str, dict]:
        kb = get_kb(self.project_id)
        lines = ["Документы в базе знаний (других документов нет):"]
        for d in kb["docs"].values():
            secs = [s for s in d["sections"] if s.count(" → ") <= 1][:30]
            lines.append(f"- «{d['title']}»: разделы: " + "; ".join(secs))
        return "\n".join(lines), {"documents": [d["title"] for d in kb["docs"].values()]}

    def get_section(self, document: str, section_path: str) -> tuple[str, dict]:
        self.search_calls += 1
        kb = get_kb(self.project_id)
        doc_id, _ = match_document(kb, document)
        if not doc_id:
            titles = "; ".join(f"«{d['title']}»" for d in kb["docs"].values())
            return f"Документ «{document}» в базе знаний не найден. Есть: {titles}.", {"found": False}
        chunks, target = section_chunks(kb, doc_id, section_path)
        if not chunks:
            secs = "; ".join(kb["docs"][doc_id]["sections"][:40])
            return f"Раздел «{section_path}» не найден в «{kb['docs'][doc_id]['title']}». Разделы: {secs}", {"found": False}
        budget = 3500
        parts, used = [f"Раздел целиком: {kb['docs'][doc_id]['title']} → {target}"], 0
        shown: list[dict] = []
        for c in chunks:
            if used > budget:
                parts.append("… (раздел длиннее лимита, остальное — через search_docs с section)")
                break
            sid = self._register_chunk(c, 0.7)  # explicitly requested section = solid evidence
            parts.append(self._fmt_chunk(sid, c, None))
            shown.append(self._seen(sid, c, None))
            used += len(c["text"]) // 3
        # an explicitly opened subsection also brings a matching sibling (same rule as search_docs, by the last query)
        if chunks and self.last_query:
            sid0 = self._register_chunk(chunks[0], 0.7)
            for _, n in self._siblings(self.last_query, chunks, [sid0] * len(chunks)):
                parts.append(self._fmt_chunk(n["sid"], n["chunk"], None).replace(f"[{n['sid']}]", f"[{n['sid']}] (соседний подраздел)", 1))
                shown.append(self._seen(n["sid"], n["chunk"], None))
        return "\n\n".join(parts), {"section": target, "n_chunks": len(chunks), "chunks": shown}

    def attach_image(self, image_id: str) -> tuple[str, dict]:
        known = {i for v in self.session["registry"].values() for i in v.get("image_ids", [])}
        if image_id not in known:
            return f"image_id {image_id!r} не встречался в найденных фрагментах — приложить нельзя.", {"ok": False}
        if image_id not in self.attached_images:
            self.attached_images.append(image_id)
        return f"Изображение {image_id} будет приложено к ответу.", {"ok": True}

    def validate_filter(self, expression: str) -> tuple[str, dict]:
        chk = validate_filter(expression)
        d = chk.to_dict()
        ref = filter_reference()
        lines = [f"Выражение: «{chk.expression}» → {'корректно' if chk.valid else 'ОШИБКА'}",
                 *(f"Проблема: {p}" for p in chk.problems),
                 *(f"Рабочая альтернатива: {s}" for s in chk.suggestions)]
        if ref:
            lines.append("Поддерживаемые операторы фильтра по столбцу: " + ", ".join(f"«{k}» ({v})" for k, v in (ref.get("column_operators") or {}).items()))
            lines.append(f"Формат даты: {ref.get('date_format')}. Ручной фильтр: {ref.get('manual_list')}. Пустые значения: {ref.get('empty_values')}.")
            if ref.get("editor_group_categories"):
                lines.append("Группы условий редактора фильтров: " + ", ".join(ref["editor_group_categories"]) + ".")
        if chk.search_hints:
            lines.append("Что искать в базе, чтобы подтвердить ответ документацией: " + "; ".join(chk.search_hints))
        text = "\n".join(lines)
        sid = self._register_tool("validate_filter", text, "проверка синтаксиса фильтра")
        return f"[{sid}] (tool) validate_filter\n{text}", d

    def parse_bo_link(self, url: str) -> tuple[str, dict]:
        kb = get_kb(self.project_id)
        a = parse_bo_link(url, known_names=known_names(kb))
        lines = [f"Ссылка: {a.original}", f"Внутренняя ссылка продукта: {'да' if a.is_bo_link else 'нет'}"]
        if a.is_bo_link:
            lines += [
                f"Система: {a.system}", f"Действие: {a.action}", f"Модуль: {a.module}",
                f"Документ (транслит): {a.document_slug} → вероятно «{a.document_guess}»" if a.document_guess else f"Документ (транслит): {a.document_slug} — не распознан",
                "Кандидаты: " + ", ".join(f"«{c['name']}» ({c['score']:.0f}%)" for c in a.document_candidates),
                f"ID записи (исправленный): {a.record_id}",
            ]
        lines += [f"Повреждение: {p}" for p in a.problems]
        if a.is_bo_link:
            lines.append(f"Исправленная ссылка: {a.normalized_url}")
            lines.append("Что искать в базе для ответа: " + "; ".join(a.search_hints))
        text = "\n".join(lines)
        sid = self._register_tool("parse_bo_link", text, "разбор ссылки")
        return f"[{sid}] (tool) parse_bo_link\n{text}", a.to_dict()

    def execute(self, name: str, args: dict[str, Any]) -> tuple[str, dict]:
        fn = getattr(self, name, None)
        if fn is None or name in FINAL_TOOLS:
            return f"Неизвестный инструмент {name}", {"error": "unknown"}
        try:
            return fn(**args)
        except TypeError as e:
            return f"Неверные аргументы для {name}: {e}", {"error": str(e)}


def parse_args(raw: str | None) -> dict:
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}
