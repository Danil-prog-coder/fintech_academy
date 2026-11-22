"""Confluence storage HTML -> the existing ingest Block representation.

No network calls, macro execution or HTML rendering. Attachment paths must come
from the validated source batch, never from a page's arbitrary URL.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .blocks import Block, ParsedDocument


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list = field(default_factory=list)


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in {"br", "hr", "img", "ri:attachment", "ri:url", "ri:page"}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(_Node(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)

    def unknown_decl(self, data):
        if data.startswith("CDATA["):
            self.handle_data(data[6:])


def parse_confluence_html(
    html: str, *, title: str, document_id: str, source_url: str,
    metadata: dict | None = None, image_paths: dict[str, str] | None = None,
) -> ParsedDocument:
    """Preserve headings, table cells, literal code, links and local image refs."""
    tree = _Tree()
    tree.feed(html)
    doc = ParsedDocument(title, document_id, source_url, source_type="confluence")
    doc.meta.update(metadata or {})
    doc.meta["source_url"] = source_url
    images = image_paths or {}

    def text(node, *, skip_lists=False):
        if isinstance(node, str):
            return node
        if node.tag in {"script", "style"} or (skip_lists and node.tag in {"ul", "ol"}):
            return ""
        if node.tag == "br":
            return "\n"
        value = "".join(text(c, skip_lists=skip_lists) for c in node.children)
        if node.tag == "a" and node.attrs.get("href"):
            target = urljoin(source_url, node.attrs["href"])
            if urlsplit(target).scheme in {"http", "https"}:
                return f"{value} ({target})"
        if node.tag in {"p", "div"}:
            return value + "\n"
        return value

    def descendants(node, tag):
        for child in node.children:
            if isinstance(child, _Node):
                if child.tag == tag:
                    yield child
                yield from descendants(child, tag)

    def visit(node, depth=0):
        if isinstance(node, str):
            if node.strip():
                doc.blocks.append(Block("paragraph", node.strip()))
            return
        tag = node.tag
        if tag in {"script", "style"}:
            return
        if tag == "table":
            rows = []
            spans = []
            for row in descendants(node, "tr"):
                cells = [c for c in row.children if isinstance(c, _Node) and c.tag in {"th", "td"}]
                rows.append([text(c).strip() for c in cells])
                spans.append([
                    {k: c.attrs[k] for k in ("rowspan", "colspan") if k in c.attrs}
                    for c in cells
                ])
                if any(c.attrs.get("rowspan", "1") != "1" or c.attrs.get("colspan", "1") != "1" for c in cells):
                    doc.warnings.append("Confluence table contains merged cells; spans retained in metadata")
            doc.blocks.append(Block("table", rows=rows, meta={"cell_spans": spans}))
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            doc.blocks.append(Block("heading", text(node).strip(), level=int(tag[1])))
            return
        if tag in {"pre", "ac:plain-text-body"}:
            doc.blocks.append(Block("paragraph", text(node), meta={"code": True}))
            return
        if tag == "ac:structured-macro":
            name = node.attrs.get("ac:name", "unknown")
            if name in {"code", "noformat"}:
                for body in descendants(node, "ac:plain-text-body"):
                    visit(body, depth)
                return
            if name not in {"info", "note", "warning", "tip", "panel", "expand"}:
                doc.warnings.append(f"Confluence macro not executed: {name}")
                return
            for body in descendants(node, "ac:rich-text-body"):
                visit(body, depth)
            return
        if tag in {"ac:image", "img"}:
            refs = list(descendants(node, "ri:attachment"))
            filename = refs[0].attrs.get("ri:filename", "") if refs else node.attrs.get("src", "")
            path = images.get(filename)
            if path:
                doc.blocks.append(Block("image", image_path=path, alt=node.attrs.get("alt", "")))
            else:
                doc.warnings.append(f"Confluence image unavailable: {filename or 'unnamed'}")
            return
        if tag == "li":
            doc.blocks.append(Block("list_item", text(node, skip_lists=True).strip(), indent=depth, marker="-"))
            for child in node.children:
                if isinstance(child, _Node) and child.tag in {"ul", "ol"}:
                    visit(child, depth + 1)
            return
        if tag == "p":
            value = text(node).strip()
            if value:
                doc.blocks.append(Block("paragraph", value))
            for image in descendants(node, "ac:image"):
                visit(image, depth)
            for image in descendants(node, "img"):
                visit(image, depth)
            return
        for child in node.children:
            visit(child, depth)

    visit(tree.root)
    return doc
