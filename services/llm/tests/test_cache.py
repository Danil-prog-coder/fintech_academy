from rag_service.cache import ExactCache, is_cacheable_question, normalize_question


def test_cacheable_rules():
    assert is_cacheable_question("Кто согласовывает БП Командировки?", False, True)
    assert not is_cacheable_question("Кто согласовывает БП Командировки?", False, False)  # follow-up
    assert not is_cacheable_question("Что на скриншоте?", True, True)
    assert not is_cacheable_question("Почему не работает фильтр «!> 200»?", False, True)
    assert not is_cacheable_question("ссылка https://bo.bars.group//#x что делать", False, True)
    assert not is_cacheable_question("Сделка 2334-26 не выбирается", False, True)
    assert not is_cacheable_question("Позовите оператора", False, True)


def test_normalize():
    assert normalize_question("  Кто согласовывает БП «Командировки»?! ") == normalize_question("кто согласовывает бп командировки")


def test_exact_cache_roundtrip_and_generation_isolation():
    c = ExactCache()
    c._redis = None
    good = {"action": "answer", "text": "t [1]", "sources": [{"source_id": "S1"}], "confidence_level": "high"}
    c.store("default", "g1", "Кто согласовывает?", good)
    assert c.lookup("default", "g1", "кто согласовывает") ["text"] == "t [1]"
    assert c.lookup("default", "g2", "кто согласовывает") is None  # new KB generation → miss
    assert c.lookup("other", "g1", "кто согласовывает") is None  # project isolation
    c.store("default", "g1", "Вопрос низкой уверенности", dict(good, confidence_level="medium"))
    assert c.lookup("default", "g1", "Вопрос низкой уверенности") is None
    c.store("default", "g1", "оффер", {"action": "offer_operator", "text": "x", "confidence_level": "high", "sources": [1]})
    assert c.lookup("default", "g1", "оффер") is None


def test_self_contained_mid_session():
    from rag_service.cache import is_self_contained

    assert is_self_contained("Мне необходимо узнать, кто согласовывает БП Командировки? (TC-05)")
    assert not is_self_contained("а в выходные?")  # follow-up
    assert not is_self_contained("А если сотрудник уже уехал в командировку?")  # follow-up opener
    assert not is_self_contained("Как оформить её заранее в системе?")  # anaphoric pronoun
    assert not is_self_contained("Кто согласовывает этот документ потом?")
    assert not is_self_contained("Сколько дней?")  # too short to stand alone


def _fake_agent(calls):
    from rag_service.agent.memory import get_memory

    def run(session_id, project_id, message, images=None, now=None, debug=False):
        calls.append(message)
        mem = get_memory()
        sess = mem.load(session_id, project_id)
        sess["messages"] += [{"role": "user", "content": message}, {"role": "assistant", "content": "Руководитель [1]"}]
        sess["turns"] += 1
        mem.save(sess)
        yield {"type": "status", "text": "Ищу в документации…"}
        yield {"type": "final", "action": "answer", "text": f"Ответ на «{message}» [1]", "confidence": 0.9,
               "confidence_level": "high", "image_ids": [], "buttons": [],
               "sources": [{"citation_label": "[1]", "source_id": "S1", "document_title": "БП Командировка",
                            "section_path": "БП → 4", "excerpt": "руководитель", "chunk_type": "text", "image_ids": []}]}

    return run


def test_repeat_in_same_session_hits_cache(monkeypatch):
    import rag_service.cache as cache_mod
    import rag_service.service as service
    from rag_service.agent.memory import get_memory

    calls = []
    c = ExactCache()
    c._redis = None
    monkeypatch.setattr(service, "get_cache", lambda: c)
    monkeypatch.setattr(cache_mod, "_cache", c)
    monkeypatch.setattr(service.store, "active_generation", lambda pid: "g-repeat")
    monkeypatch.setattr(service, "run_turn_stream", _fake_agent(calls))
    monkeypatch.setattr(service.get_settings(), "faq_enabled", False)
    sid, q = "repeat-u", "Мне необходимо узнать, кто согласовывает БП Командировки? (TC-05)"
    get_memory().reset(sid, "default")

    first = service.ask_sync(sid, "default", q)  # first turn: agent, answer stored (behaviour unchanged)
    assert not first["cache_hit"] and calls == [q]
    second = service.ask_sync(sid, "default", q)  # exact repeat in the same session → cache-1
    assert second["cache_hit"] and second["cache_level"] == "exact" and calls == [q]
    assert get_memory().load(sid, "default")["turns"] == 2

    follow = "а в выходные?"
    service.ask_sync(sid, "default", follow)  # follow-up → agent with context, not cached
    service.ask_sync(sid, "default", follow)
    assert calls == [q, follow, follow]
    pron = "Как оформить её заранее в системе?"
    service.ask_sync(sid, "default", pron)  # anaphoric pronoun → agent, never stored
    assert c.lookup("default", "g-repeat", pron) is None
    assert not service.ask_sync(sid, "default", pron)["cache_hit"]
    assert calls == [q, follow, follow, pron, pron]


def test_first_turn_short_question_still_cacheable(monkeypatch):
    import rag_service.service as service
    from rag_service.agent.memory import get_memory

    calls = []
    c = ExactCache()
    c._redis = None
    monkeypatch.setattr(service, "get_cache", lambda: c)
    monkeypatch.setattr(service.store, "active_generation", lambda pid: "g-first")
    monkeypatch.setattr(service, "run_turn_stream", _fake_agent(calls))
    monkeypatch.setattr(service.get_settings(), "faq_enabled", False)
    for sid in ("first-a", "first-b"):  # a new session each time: first-turn rule as before, even under 4 words
        get_memory().reset(sid, "default")
    assert not service.ask_sync("first-a", "default", "Кто согласует командировку?")["cache_hit"]
    assert service.ask_sync("first-b", "default", "Кто согласует командировку?")["cache_hit"]
    assert calls == ["Кто согласует командировку?"]
