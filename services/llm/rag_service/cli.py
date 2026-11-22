"""CLI: python -m rag_service.cli ingest [paths...] | search "query" | ask "question" """

from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import get_settings


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="rag_service")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("ingest")
    pi.add_argument("paths", nargs="*")
    pi.add_argument("--no-vision", action="store_true")
    pi.add_argument("--project", default=None)
    ps = sub.add_parser("search")
    ps.add_argument("query")
    ps.add_argument("--document")
    ps.add_argument("--no-rerank", action="store_true")
    pa = sub.add_parser("ask")
    pa.add_argument("message")
    pa.add_argument("--session", default="cli")
    args = ap.parse_args(argv)
    s = get_settings()
    if args.cmd == "ingest":
        from .ingest.pipeline import ingest

        rep = ingest(args.paths or [s.kb_dir], args.project, describe=not args.no_vision)
        rep.pop("documents", None)
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    elif args.cmd == "search":
        from .retrieval.search import search

        r = search(s.default_project_id, args.query, document=args.document, rerank=not args.no_rerank)
        print(json.dumps(r["signals"], ensure_ascii=False), r["notes"])
        for x in r["results"]:
            print(f"{x.get('rerank')}\t{x['rrf']:.4f}\t{x['dense']}\t{x['sparse']}\t{x['chunk_type']}\t{x['section_path_str'][:120]}")
    elif args.cmd == "ask":
        from .agent.loop import run_turn_sync

        res = run_turn_sync(args.session, s.default_project_id, args.message)
        print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
