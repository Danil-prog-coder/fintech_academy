"""Ingestion pipeline: files -> parse -> clean -> VLM image descriptions -> chunks -> embeddings -> Qdrant.

Publishes a new generation atomically and writes the indexing report (FR-ING-08, FR-ADM-02/07).
`ingest()` builds a complete generation, reusing unchanged documents; `ingest_incremental()` re-parses only
the given files, drops removed documents and copies every other point (with its dense vector) from the active
generation — used by Git sync (FR-GIT-03). Git documents get folder-aware titles, front matter metadata and
links pinned to the commit (FR-GIT-01/02/04). Red-frame crops of screenshots are stored next to the originals (FR-ING-06).
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import re
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path, PurePosixPath

from qdrant_client import models as qm

from ..config import get_settings
from ..index import store
from ..index.embeddings import get_embedder
from ..index.sparse import doc_sparse, tokenize
from ..project_paths import upload_dir, write_atomic
from ..retrieval.access import DEFAULT_SECTION
from .blocks import ParsedDocument
from .chunker import Chunk, ImageInfo, _image_context, chunk_document, split_sections
from .confluence_parser import parse_confluence_html
from .crops import crop_red_frame
from .docx_parser import parse_docx
from .md_parser import parse_markdown, parse_markdown_text, parse_text
from .pdf_parser import parse_pdf
from .util import sha256_file, stable_uuid
from .vision import describe_image

log = logging.getLogger(__name__)
SUPPORTED = {".docx", ".pdf", ".md", ".markdown", ".txt"}
INGEST_SCHEMA_VERSION = 1  # Bump when parser/chunker semantics change and old chunks must be rebuilt.


def input_identity(path: Path, meta: dict | None, file_hash: str | None = None) -> tuple[str, str]:
    key = "source:" + meta["doc_id"] if meta else "file:" + str(path.resolve())
    context = {name: meta.get(name) for name in (
        "doc_id", "source_id", "source_type", "path", "url", "url_template", "commit", "provider",
        "confluence_fingerprint",
    )} if meta else {}
    digest = hashlib.sha256(json.dumps({"file_hash": file_hash or sha256_file(str(path)),
                                       "context": context}, sort_keys=True).encode()).hexdigest()
    return key, digest


def _ingest_signature(settings, describe: bool) -> str:
    fields = ("embedding_provider", "embedding_model", "embedding_dim", "embedding_base_url", "vision_model", "vision_mode",
              "vision_prompt", "vision_cache_legacy", "chunk_max_tokens", "chunk_target_tokens", "table_max_tokens")
    data = {field: getattr(settings, field, None) for field in fields}
    return hashlib.sha256(json.dumps({"schema": INGEST_SCHEMA_VERSION, "describe": describe, **data}, sort_keys=True).encode()).hexdigest()


def parse_file(path: Path, images_dir: Path) -> ParsedDocument:
    ext = path.suffix.lower()
    if ext == ".docx":
        return parse_docx(path, images_dir)
    if ext == ".pdf":
        return parse_pdf(path, images_dir / path.stem)
    if ext in (".md", ".markdown", ".txt"):
        return parse_markdown(path)
    raise ValueError(f"unsupported format: {ext}")


_REL_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\((?!https?://|mailto:|#)([^)\s]+)\)")


def rewrite_relative_links(text: str, path: str) -> str:
    """FR-GIT-04: `[текст](../other.md#x)` → `текст (см. файл other.md)` so the agent sees where the link leads."""
    def rep(m: re.Match) -> str:
        target = PurePosixPath(path).parent / m.group(2).split("#")[0]
        parts: list[str] = []
        for part in target.parts:
            if part == "..":
                if parts:
                    parts.pop()
            elif part != ".":
                parts.append(part)
        return f"{m.group(1)} (см. файл {'/'.join(parts)})"
    return _REL_LINK_RE.sub(rep, text)


def parse_with_meta(path: Path, images_dir: Path, meta: dict | None) -> ParsedDocument:
    """Parse a file; documents from Git / Confluence get a stable doc_id and a folder-aware title (FR-GIT-01/04)."""
    if not meta:
        return parse_file(path, images_dir)
    ext = path.suffix.lower()
    rel = meta["path"]
    if meta.get("source_type") == "confluence" and meta.get("confluence_storage"):
        doc = parse_confluence_html(
            Path(meta["confluence_storage"]).read_text(encoding="utf-8"),
            title=meta.get("confluence_title") or Path(rel).stem,
            document_id=meta["doc_id"], source_url=meta.get("url") or "",
            image_paths=meta.get("confluence_images") or {},
        )
    elif ext in (".md", ".markdown"):
        doc = parse_markdown_text(rewrite_relative_links(path.read_text(encoding="utf-8", errors="replace"), rel), path.parent, source_file=rel)
    elif ext == ".txt":
        doc = parse_text(path.read_text(encoding="utf-8", errors="replace"), source_file=rel)
    else:
        doc = parse_file(path, images_dir)
    title = doc.title
    # the H1 equal to the title is not a section (it would repeat in section_path after re-titling)
    for i, b in enumerate(doc.blocks):
        if b.kind == "heading" and b.level == 1 and b.text.strip() == title.strip():
            doc.blocks.pop(i)
            break
    folders = list(PurePosixPath(rel).parent.parts)
    if PurePosixPath(rel).stem.lower() in ("readme", "index", "_index"):
        title = f"{title} (описание раздела)"  # README / index files describe their folder
    doc.title = " → ".join([*folders, title]) if folders else title
    doc.doc_id = meta["doc_id"]
    doc.source_type = meta.get("source_type") or "git"
    doc.source_file = rel
    doc.meta.update({k: meta.get(k) for k in ("provider", "repo", "branch", "path", "commit", "source_id")})
    return doc


def pages_without_text_layer(doc: ParsedDocument, min_chars: int = 40) -> list[int]:
    """PDF pages that hold a picture but (almost) no extractable text — scanned pages."""
    pages: dict[int, list[int]] = {}
    for b in doc.blocks:
        if b.page is None:
            continue
        cnt = pages.setdefault(b.page, [0, 0])
        if b.kind == "image":
            cnt[1] += 1
        else:
            cnt[0] += len((b.text or "").strip()) + sum(len(c) for r in (b.rows or []) for c in r)
    return sorted(p for p, (chars, imgs) in pages.items() if imgs and chars < min_chars)


def image_id_for(doc_id: str):
    def f(path: str) -> str:
        return f"{doc_id}/{Path(path).stem}" if path else f"{doc_id}/unknown"
    return f


def collect_files(paths: list[str | Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            out.extend(sorted(x for x in p.rglob("*") if x.suffix.lower() in SUPPORTED and "images" not in x.parts))
        elif p.suffix.lower() in SUPPORTED:
            out.append(p)
    return out


def section_of(path: Path, root: Path) -> str | None:
    """Uploads live in `<project upload dir>/<section>/<file>`: the first folder is the section."""
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return rel.parts[0] if len(rel.parts) > 1 else DEFAULT_SECTION


def build_chunks(files: list[Path], *, describe: bool = True, workers: int | None = None,
                 file_meta: dict[str, dict] | None = None,
                 sections: dict[str, str] | None = None) -> tuple[list[Chunk], dict[str, ImageInfo], dict]:
    s = get_settings()
    images_dir = Path(s.state_dir) / "images"
    report: dict = {"documents": [], "warnings": [], "errors": []}
    all_chunks: list[Chunk] = []
    all_images: dict[str, ImageInfo] = {}
    for f in files:
        meta = (file_meta or {}).get(str(f))
        original_file = None
        try:
            file_hash = sha256_file(str(f))
            parse_path = f
            if not meta:
                content = f.read_bytes()
                file_hash = hashlib.sha256(content).hexdigest()
                parse_path = Path(s.state_dir) / "originals" / file_hash / f.name
                parse_path.parent.mkdir(parents=True, exist_ok=True)
                if not parse_path.exists() or sha256_file(str(parse_path)) != file_hash:
                    write_atomic(parse_path, content)
                original_file = str(parse_path.resolve())
            content_hash = (meta.get("confluence_fingerprint") if meta else None) or file_hash[:16]
            doc = parse_with_meta(parse_path, images_dir / content_hash, meta)
        except Exception as e:  # noqa: BLE001
            report["errors"].append(f"{f.name}: {e}")
            log.exception("parse failed: %s", f)
            continue
        # FR-GIT-01: for Git documents the commit SHA is the document version
        doc.meta["document_version"] = (meta["commit"][:12] if meta and meta.get("commit") else content_hash)
        idf = image_id_for(doc.doc_id)
        # image jobs with context
        jobs: dict[str, tuple[str, str, str]] = {}
        content_dups: Counter = Counter()
        img_blocks = [(sec, i, b) for sec in split_sections(doc) for i, b in enumerate(sec.blocks) if b.kind == "image"]
        hashes: dict[str, str] = {}
        for _, _, b in img_blocks:
            if b.image_path and Path(b.image_path).exists():
                h = sha256_file(b.image_path)
                hashes[b.image_path] = h
                content_dups[h] += 1
        for sec, i, b in img_blocks:
            iid = idf(b.image_path or "")
            if iid not in jobs:
                jobs[iid] = (b.image_path or "", _image_context(sec.blocks, i), " → ".join([doc.title, *sec.path]))
        infos: dict[str, ImageInfo] = {}

        def run(item):
            iid, (path, ctx, secname) = item
            dup = content_dups.get(hashes.get(path, ""), 1)
            if describe:
                return iid, describe_image(path, iid, context=ctx, section=secname, dup_count=dup)
            from .vision import looks_broken

            info = ImageInfo(image_id=iid, path=path)
            if not Path(path).exists() or looks_broken(path, dup):
                info.broken, info.kind = True, "broken"
            return iid, info

        with ThreadPoolExecutor(max_workers=workers or s.vision_workers) as ex:
            # each task carries a copy of the caller's context, so vision-model tokens land in its usage meter
            futures = [ex.submit(contextvars.copy_context().run, run, item) for item in jobs.items()]
            for fut in futures:
                iid, info = fut.result()
                infos[iid] = info
        # FR-ING-06: a cut-out of the element in a red frame, served by GET /images/{id}?crop=true
        for iid, info in infos.items():
            if not info.broken and info.path and Path(info.path).exists():
                try:
                    out = Path(s.state_dir) / "image_crops" / content_hash / f"{iid}.png"
                    if crop_red_frame(info.path, out):
                        info.crop_path = str(out)
                except Exception as e:  # noqa: BLE001
                    log.debug("crop failed for %s: %s", iid, e)
        warnings: list[str] = list(doc.warnings)
        for page in pages_without_text_layer(doc):
            # a scan: the page text exists only as a picture, so it reaches the index only through the vision model
            described = any(i.description or i.ocr_lines for b in doc.blocks if b.kind == "image" and b.page == page
                            for i in [infos.get(idf(b.image_path or ""))] if i)
            warnings.append(f"page_without_text_layer: p.{page}" + ("" if described else " (not described: the page text is lost)"))
        for iid, info in infos.items():
            if info.broken:
                warnings.append(f"broken_image: {iid}")
            elif describe and not info.description:
                warnings.append(f"image_not_described: {iid}")
        chunks = chunk_document(
            doc, infos, idf, max_tokens=s.chunk_max_tokens, target_tokens=s.chunk_target_tokens,
            table_max_tokens=s.table_max_tokens, warnings=warnings,
        )
        for c in chunks:
            c.meta["document_version"] = doc.meta["document_version"]
            c.meta["source_type"] = doc.source_type
            if meta:  # FR-GIT-02: link to the file pinned to the commit, anchored at the nearest heading
                c.meta.update({"repo": meta.get("repo"), "git_path": meta.get("path"), "commit": meta.get("commit")})
                if meta.get("url_template") and c.section_path and f.suffix.lower() in (".md", ".markdown"):
                    from ..git_source.providers import heading_anchor

                    c.meta["source_url"] = meta["url_template"].replace("{anchor}", heading_anchor(c.section_path[-1], meta.get("provider", "github")))
                else:
                    c.meta["source_url"] = meta.get("url")
        all_chunks.extend(chunks)
        all_images.update(infos)
        types = Counter(c.chunk_type for c in chunks)
        report["documents"].append({
            "doc_id": doc.doc_id, "title": doc.title, "file": meta["path"] if meta else f.name, "source_type": doc.source_type,
            "section": (meta or {}).get("section") or (sections or {}).get(str(f)) or DEFAULT_SECTION,
            "document_version": doc.meta["document_version"], "content_hash": content_hash,
            "input_key": input_identity(f, meta, file_hash)[0],
            "input_fingerprint": input_identity(f, meta, file_hash)[1],
            **({"original_file": original_file} if original_file else {}),
            **({"confluence_fingerprint": meta["confluence_fingerprint"]}
               if meta and meta.get("confluence_fingerprint") else {}),
            **({"git": {k: meta.get(k) for k in ("source_id", "provider", "repo", "branch", "path", "commit", "url")},
                "front_matter": {k: v for k, v in doc.meta.items() if k in ("title", "tags", "date", "updated", "description")}} if meta else {}),
            "sections": len(split_sections(doc)), "chunks": len(chunks), "chunk_types": dict(types),
            "tables": sum(1 for b in doc.blocks if b.kind == "table"),
            "images": len(infos), "images_described": sum(1 for i in infos.values() if i.description),
            "images_broken": sum(1 for i in infos.values() if i.broken),
            "outline": [" → ".join(sec.path) for sec in split_sections(doc) if sec.path],
        })
        report["warnings"].extend(f"{doc.doc_id}: {w}" for w in warnings)
        noise = [c.chunk_id for c in chunks if "Ошибка! Используйте вкладку" in c.text]
        if noise:
            report["errors"].append(f"noise left in chunks: {noise}")
    return all_chunks, all_images, report


def _new_generation() -> str:
    return time.strftime("g%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:16]


def _payload(project_id: str, generation: str, c: Chunk) -> dict:
    return {
        "project_id": project_id, "generation": generation, "chunk_id": c.chunk_id, "doc_id": c.doc_id,
        "document_title": c.document_title, "section_path": c.section_path, "section_number": c.section_number,
        "section_path_str": c.section_path_str, "section_key": f"{c.doc_id}|{' / '.join(c.section_path)}",
        "step_label": c.step_label, "chunk_type": c.chunk_type, "text": c.text, "order": c.order,
        "image_ids": c.image_ids, "page": c.page, "source_file": c.source_file,
        "source_type": c.meta.get("source_type", "upload"), "document_version": c.meta.get("document_version"),
        "image_kind": c.meta.get("image_kind"),
        # FR-GIT-01/02 (empty for uploads)
        "source_url": c.meta.get("source_url"), "repo": c.meta.get("repo"), "git_path": c.meta.get("git_path"),
        "commit": c.meta.get("commit"),
    }


def _publish(project_id: str, emb_model: str, new: list[tuple[dict, list[float]]], kept: list[tuple[dict, list[float]]],
             docs: list[dict], images: dict[str, dict], warnings: list[str], errors: list[str], extra: dict | None = None) -> tuple[str, dict]:
    """Write all points of a new generation (fresh BM25 weights for every chunk) and switch to it atomically."""
    generation = _new_generation()
    allp = new + kept
    texts = [f"{p['section_path_str']}\n{p['text']}" for p, _ in allp]
    if allp:
        store.ensure_collection(len(allp[0][1]))
    lens = [len(tokenize(t)) for t in texts]
    avgdl = sum(lens) / len(lens) if lens else 0
    points = []
    for (payload, vec), text in zip(allp, texts):
        payload = dict(payload, project_id=project_id, generation=generation)
        idx, val = doc_sparse(text, avgdl)
        points.append(qm.PointStruct(id=stable_uuid(project_id, generation, payload["chunk_id"]),
                                     vector={store.DENSE: vec, store.SPARSE: qm.SparseVector(indices=idx, values=val)}, payload=payload))
    if points:
        store.upsert(points)
    types = Counter(p["chunk_type"] for p, _ in allp)
    manifest = {
        "generation": generation, "created_at": time.time(), "embedding_model": emb_model,
        "embedding_dim": len(allp[0][1]) if allp else store.active_manifest(project_id).get("embedding_dim", 0), "avgdl": avgdl,
        "counts": {
            "documents": len(docs), "chunks": len(allp), "chunk_types": dict(types),
            "tables": sum(d.get("tables", 0) for d in docs),
            "images": len(images), "images_described": sum(1 for i in images.values() if i.get("description")),
            "images_broken": sum(1 for i in images.values() if i.get("broken")),
            "images_cropped": sum(1 for i in images.values() if i.get("crop_path")),
            # which model wrote the descriptions: more than one name means a mixed cache (fallback models or old files)
            "images_by_model": dict(Counter(i["model"] for i in images.values() if i.get("model"))),
            "git_documents": sum(1 for d in docs if d.get("source_type") == "git"),
            "warnings": len(warnings), "errors": len(errors),
        },
        "documents": docs, "images": images, "warnings": warnings, "errors": errors, **(extra or {}),
    }
    store.publish_generation(project_id, generation, manifest)
    from ..retrieval.kb import invalidate

    invalidate(project_id)
    return generation, manifest


def ingest(paths: list[str | Path], project_id: str | None = None, *, describe: bool = True,
           extra_files: list[tuple[Path, dict]] | None = None, include_git: bool = True,
           reuse_unchanged: bool = True) -> dict:
    """Publish all current inputs, reusing compatible unchanged chunks and dense vectors."""
    s = get_settings()
    project_id = project_id or s.default_project_id
    t0 = time.time()
    # Old queued jobs can still carry the shared folder: do not leak it into another project.
    paths = [upload_dir(s, project_id) if Path(p).resolve() == Path(s.kb_dir).resolve() else p for p in paths]
    files = collect_files(paths)
    extra = list(extra_files or [])
    if include_git:
        from ..git_source.sources import local_files

        extra += local_files(project_id)
    from ..confluence_source import local_files as confluence_files

    extra += confluence_files(project_id)  # pages and attachments received from the Confluence adapter
    meta = {str(p): m for p, m in extra}
    files += [p for p, _ in extra if str(p) not in {str(f) for f in files}]
    previous = store.active_manifest(project_id)
    signature = _ingest_signature(s, describe)
    previous_by_key = {d["input_key"]: d for d in previous.get("documents", []) if d.get("input_key")}
    reused = []
    changed = []
    reusable = reuse_unchanged and previous.get("ingest_signature") == signature and not previous.get("errors")
    for file in files:
        key, fingerprint = input_identity(file, meta.get(str(file)))
        old = previous_by_key.get(key)
        usable = bool(old and old.get("input_fingerprint") == fingerprint)
        if usable and old.get("original_file") and not Path(old["original_file"]).is_file():
            usable = False
        if usable:
            for info in previous.get("images", {}).values():
                if info.get("image_id", "").split("/", 1)[0] == old["doc_id"]:
                    if not info.get("broken") and not Path(info.get("path") or "").is_file():
                        usable = False
        if reusable and usable:
            reused.append(old)
        else:
            changed.append(file)
    root = upload_dir(s, project_id)
    sections = {str(f): sec for f in changed if (sec := section_of(f, root))}
    chunks, images, report = build_chunks(changed, describe=describe, file_meta=meta, sections=sections)
    if report["errors"]:
        report.update({"status": "failed", "reason": "parse errors; active generation unchanged"})
        return report
    reused_ids = {d["doc_id"] for d in reused}
    kept = [(p, v) for p, v in store.scroll_with_vectors(project_id, previous["generation"])
            if p["doc_id"] in reused_ids] if reused_ids else []
    if sum(d.get("chunks", 0) for d in reused) != len(kept):
        return {"status": "failed", "reason": "published vectors are incomplete; active generation unchanged"}
    confirmed_empty = (not files and previous.get("documents")
                       and all(d.get("source_type") == "confluence" for d in previous["documents"]))
    if not chunks and not kept and not confirmed_empty:
        report.update({"status": "failed", "reason": "no chunks"})
        return report
    docs = reused + report["documents"]
    ids = [d["doc_id"] for d in docs]
    if len(ids) != len(set(ids)):
        return {"status": "failed", "reason": "duplicate document IDs; rename conflicting files"}
    emb = get_embedder() if chunks else None
    if kept and emb and emb.model != previous.get("embedding_model"):
        return ingest(paths, project_id, describe=describe, extra_files=extra_files,
                      include_git=include_git, reuse_unchanged=False)
    vecs = emb.embed_documents([c.embedding_text() for c in chunks]) if emb else []
    if len(vecs) != len(chunks):
        return {"status": "failed", "reason": "incomplete embeddings; active generation unchanged"}
    new = [(_payload(project_id, "", c), v) for c, v in zip(chunks, vecs)]
    imgs = {key: value for key, value in previous.get("images", {}).items() if key.split("/", 1)[0] in reused_ids}
    imgs.update({key: asdict(value) for key, value in images.items()})
    warnings = [w for w in previous.get("warnings", []) if w.split(":", 1)[0] in reused_ids] + report["warnings"]
    removed = {d["doc_id"] for d in previous.get("documents", [])} - set(ids)
    incremental = {"reused_docs": sorted(reused_ids), "reindexed_docs": sorted(set(ids) - reused_ids),
                   "removed_docs": sorted(removed), "reused_chunks": len(kept), "embedded_chunks": len(new)}
    if not changed and not removed and kept:
        return {"status": "up_to_date", "project_id": project_id, "generation": previous["generation"],
                "counts": previous["counts"], "incremental": incremental,
                "elapsed_s": round(time.time() - t0, 1)}
    generation, manifest = _publish(project_id, emb.model if emb else previous.get("embedding_model", ""), new, kept, docs,
                                    imgs, warnings, report["errors"],
                                    {"ingest_signature": signature, "incremental": incremental})
    report["documents"] = docs
    report.update({"status": "ok", "project_id": project_id, "generation": generation, "counts": manifest["counts"],
                   "incremental": incremental, "elapsed_s": round(time.time() - t0, 1)})
    return report


def ingest_incremental(project_id: str, files: list[tuple[Path, dict | None]], removed_doc_ids: set[str] | None = None,
                       *, describe: bool = True) -> dict:
    """FR-GIT-03: re-index only `files`, drop `removed_doc_ids`, copy every other chunk (and its vector) unchanged."""
    s = get_settings()
    t0 = time.time()
    prev_gen = store.active_generation(project_id)
    if not prev_gen:
        return ingest([upload_dir(s, project_id)], project_id, describe=describe, extra_files=[(p, m) for p, m in files if m])
    prev = store.active_manifest(project_id)
    meta = {str(p): m for p, m in files if m}
    chunks, images, report = build_chunks([p for p, _ in files], describe=describe, file_meta=meta)
    if report["errors"]:
        report.update({"status": "failed", "reason": "parse errors; active generation unchanged"})
        return report
    replaced = {d["doc_id"] for d in report["documents"]} | set(removed_doc_ids or set())
    kept = [(p, v) for p, v in store.scroll_with_vectors(project_id, prev_gen) if p["doc_id"] not in replaced]
    emb = get_embedder() if chunks else None
    vecs = emb.embed_documents([c.embedding_text() for c in chunks]) if emb else []
    new = [(_payload(project_id, "", c), v) for c, v in zip(chunks, vecs)]
    if not new and not kept and not removed_doc_ids:
        report.update({"status": "failed", "reason": "no chunks"})
        return report
    docs = [d for d in prev.get("documents", []) if d["doc_id"] not in replaced] + report["documents"]
    imgs = {k: v for k, v in (prev.get("images") or {}).items() if k.split("/", 1)[0] not in replaced}
    imgs.update({k: asdict(v) for k, v in images.items()})
    warnings = [w for w in prev.get("warnings", []) if w.split(":", 1)[0] not in replaced] + report["warnings"]
    errors = [e for e in prev.get("errors", []) if e.split(":", 1)[0] not in replaced] + report["errors"]
    inc = {"reindexed_docs": sorted(d["doc_id"] for d in report["documents"]),
           "removed_docs": sorted(set(removed_doc_ids or set()) - {d["doc_id"] for d in report["documents"]}),
           "embedded_chunks": len(new), "reused_chunks": len(kept), "previous_generation": prev_gen}
    generation, manifest = _publish(project_id, emb.model if emb else prev.get("embedding_model", ""), new, kept, docs, imgs, warnings, errors, {"incremental": inc})
    report.update({"status": "ok", "project_id": project_id, "generation": generation, "counts": manifest["counts"],
                   "incremental": inc, "elapsed_s": round(time.time() - t0, 1)})
    return report
