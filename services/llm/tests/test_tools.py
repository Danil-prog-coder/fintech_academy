"""Deterministic tools (NFR-03: tools are tested without an LLM)."""

from rag_service.tools.bo_link import extract_links, parse_bo_link
from rag_service.tools.filter_syntax import extract_filter_expressions, validate_filter

LINK = "https://bo.bars.group//#mainmenuitemclick&bars_office&byudjeetsdelki&id&=&6DF3B1B8B2F249368E5F9749\u0421" "10CD2AC"


def test_not_greater_is_not_supported_and_alternative_is_documented():
    chk = validate_filter("!> 200")
    assert not chk.valid
    assert any("!>" in p for p in chk.problems)
    assert any("< 201" in s for s in chk.suggestions)
    # suggestions use only documented operators
    for s in chk.suggestions:
        assert ">=" not in s and "<=" not in s


def test_documented_syntax_is_valid():
    for e in ["> 200", "< 201", "= 5", "!= СВОДЫ", "in Москва|Казань", "> 01.02.2025"]:
        assert validate_filter(e).valid, e


def test_undocumented_operators_rejected_with_fix():
    assert not validate_filter(">= 5").valid
    chk = validate_filter("<> 3")
    assert not chk.valid and any("!= 3" in s for s in chk.suggestions)


def test_extract_filter_expressions():
    assert "!> 200" in " ".join(extract_filter_expressions("Почему не работает фильтр в БО “!> 200” ?"))


def test_bo_link_damage_and_document():
    a = parse_bo_link(LINK, known_names=["Бюджет сделки", "Реестр мебели"])
    assert a.is_bo_link and a.damaged
    assert a.document_guess == "Бюджет сделки"
    probs = " ".join(a.problems)
    assert "//" in probs and "id&=&" in probs and "U+0421" in probs
    assert a.record_id == "6DF3B1B8B2F249368E5F9749C10CD2AC" and a.record_id.isascii()
    assert a.normalized_url == "https://bo.bars.group/#mainmenuitemclick&bars_office&byudjeetsdelki&id=6DF3B1B8B2F249368E5F9749C10CD2AC"


def test_not_a_bo_link():
    assert not parse_bo_link("https://example.com/x").is_bo_link


def test_extract_links():
    assert extract_links(f"Мне прислали ссылку {LINK} что с ней делать ?")


def test_sibling_subsection_joins_broad_question(monkeypatch):
    from rag_service.tools import registry

    def ch(cid, order, path, text="t", title="Функции системы"):
        return {"chunk_id": cid, "doc_id": "d", "order": order, "section_path": path, "section_path_str": " → ".join(path),
                "document_title": title, "chunk_type": "text", "text": text}
    root, par = "2 Работа с записями", "2.1 Инструменты поиска данных"
    a1 = ch("d:0001", 1, [root, par, "2.1.1 Редактор фильтров"])
    b1 = ch("d:0002", 2, [root, par, "2.1.2 Фильтрация по столбцам"])
    b2 = ch("d:0003", 3, [root, par, "2.1.2 Фильтрация по столбцам"])
    b3 = ch("d:0004", 4, [root, par, "2.1.2 Фильтрация по столбцам"])
    c1 = ch("d:0005", 5, [root, par, "2.1.3 Поиск по записям"])
    kb = {"chunks": [a1, b1, b2, b3, c1], "by_id": {}, "docs": {}}
    monkeypatch.setattr(registry, "get_kb", lambda pid: kb)
    t = registry.Tools("p", {"registry": {}, "next_s": 1, "next_t": 1})
    got = t._siblings("Как работает фильтр документа?", [a1], ["S1"])
    assert [n["chunk"]["chunk_id"] for _, n in got] == ["d:0002", "d:0003"]  # first RETRIEVAL_SIBLING_CHUNKS of the matching sibling
    # a stem shared by the parent section («записи») does not pull every sibling in
    assert t._siblings("Как найти записи?", [a1], ["S1"]) == []
