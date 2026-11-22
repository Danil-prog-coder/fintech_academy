from rag_service.agent import guardrails as gr

REG = {
    "S1": {"text": "Дежурство ОМ: Пн–Пт 17:30–21:00, Сб–Вс 10:30–21:00. Телефон дежурного +7 999 100-20-30", "score": 0.9},
    "S2": {"text": "Статус – текущий статус мебели (занят, свободен, списан)", "score": 0.8},
    "T1": {"text": "validate_filter: «!>» не поддерживается", "score": 1.0, "chunk_type": "tool"},
}


def test_operator_request_detector():
    for t in ["оператор", "Позовите живого человека", "соедините с оператором пожалуйста", "хочу поговорить с человеком",
              "связаться с поддержкой"]:
        assert gr.is_operator_request(t), t
    for t in ["Какие операторы фильтра поддерживаются?", "Почему не работает фильтр «!> 200»?",
              "Кто согласовывает БП Командировки?", "Мне не отвечает офис-менеджер"]:
        assert not gr.is_operator_request(t), t


def test_valid_answer_passes():
    chk = gr.check_answer("Дежурство: Пн–Пт 17:30–21:00 [1].", [{"n": 1, "source_id": "S1", "quote": "Пн–Пт 17:30–21:00"}], REG)
    assert chk.ok, chk.problems
    assert chk.valid_citations[0]["quote"]


def test_fake_quote_is_removed_but_answer_kept():
    chk = gr.check_answer("Статусы: занят, свободен, списан [1].", [{"n": 1, "source_id": "S2", "quote": "статусы: в ремонте"}], REG)
    assert chk.ok and chk.removed_quotes == ["статусы: в ремонте"]


def test_unknown_source_rejected():
    chk = gr.check_answer("Ответ [1].", [{"n": 1, "source_id": "S99", "quote": "x"}], REG)
    assert not chk.ok


def test_ungrounded_numbers_rejected():
    chk = gr.check_answer("Дежурство до 23:00 [1].", [{"n": 1, "source_id": "S1", "quote": ""}], REG)
    assert not chk.ok and "23:00" in " ".join(chk.problems)


def test_no_markers_rejected():
    assert not gr.check_answer("Просто текст без ссылок.", [], REG).ok


def test_source_id_markers_are_normalised():
    text, cits = gr.normalize_markers("Статусы [S2], фильтр [T1], оба [S2, T1].", [], REG)
    assert "[S" not in text and "[T" not in text
    assert {c["source_id"] for c in cits} == {"S2", "T1"}
    assert gr.check_answer(text, cits, REG).ok


def test_unknown_source_id_marker_rejected():
    text, cits = gr.normalize_markers("Ответ [S42].", [], REG)
    assert not gr.check_answer(text, cits, REG).ok


def test_confidence_levels():
    hi = gr.confidence(evidence=1.0, gap=0.3, n_supporting=3, coverage="full", first_pass=True, high=0.7, medium=0.45)
    lo = gr.confidence(evidence=0.3, gap=0.0, n_supporting=0, coverage="partial", first_pass=False, high=0.7, medium=0.45)
    mid = gr.confidence(evidence=0.7, gap=0.0, n_supporting=1, coverage="partial", first_pass=True, high=0.7, medium=0.45)
    assert hi[1] == "high" and lo[1] == "low" and mid[1] == "medium"
    assert 0 <= lo[0] < mid[0] < hi[0] <= 1


def test_image_id_as_source_is_mapped():
    reg = dict(REG, S3={"text": "Схема: Заказ билетов нужен?", "image_ids": ["bp/p04"], "chunk_id": "c3", "score": 0.7})
    text, cits = gr.normalize_markers("Развилка «Заказ билетов нужен?» [1].", [{"n": 1, "source_id": "bp/p04", "quote": "Заказ билетов нужен?"}], reg)
    assert cits[0]["source_id"] == "S3" and gr.check_answer(text, cits, reg).ok
_V1 = """Изображение (bpmn): Схема бизнес-процесса Командировка
Правила переходов:
- если Заказ билетов нужен? — Да, то следующий шаг — Проверка авансовых платежей бухгалтерией
- если Заказ билетов нужен? — Нет, то проверяется условие Офис Казанский?
- если Офис Казанский? — Да, то через Ожидание принятия в работу переход к Офис менеджер
- если Кол-во дней командировки больше 1? — Да, то возврат на проверку в Бухгалтерию
- если Требуется билет обратно? — Да, то переход к Покупка обратного билета
- если на любом этапе согласования выбрано Отклонить, процесс переходит в терминальный узел Отклонен"""
_V2 = """Изображение (bpmn): Схема бизнес-процесса Командировка
Правила переходов:
- «Старт» → «Инициация БП»
- «Инициация БП» — Отклонить → «Отклонен»
- «Заказ билетов нужен?» — Да → «Проверка авансовых платежей бухгалтерией (Бухгалтерия)»
- «Заказ билетов нужен?» — Нет → «Офис Казанский?»
- «Офис Казанский?» — Да → «Ожидание принятия в работу»
- «Кол-во дней командировки больше 1 ?» — Да → «Проверка авансовых платежей бухгалтерией (Бухгалтерия)»
- «Требуется билет обратно?» — Нет → «Согласование командировочных»"""
Q = "Какие могут быть условия в выборе следующего согласующего лица БП Командировка?"


def test_branch_gap_reads_both_vision_prompt_versions():
    for scheme in (_V1, _V2):
        cited = [{"chunk_type": "image", "text": scheme}]
        gap = gr.branch_gap(Q, "Согласует руководитель отдела (Группа МЕД) и Директор БЦ.", cited)
        assert "Заказ билетов нужен?" in gap and "Офис Казанский?" in gap and len(gap) == 4, gap
        full = "Развилки: нужен ли заказ билетов; Казанский ли офис; больше ли 1 дня командировка; требуется ли билет обратно."
        assert gr.branch_gap(Q, full, cited) == []


def test_branch_gap_only_for_condition_questions_with_a_cited_diagram():
    cited = [{"chunk_type": "image", "text": _V2}]
    assert gr.branch_gap("Кто согласовывает БП Командировки?", "Директор БЦ", cited) == []
    assert gr.branch_gap(Q, "Директор БЦ", [{"chunk_type": "text", "text": _V2}]) == []


def test_branch_gap_needs_branch_words_in_one_sentence():
    cited = [{"chunk_type": "image", "text": _V1}]
    # common words scattered over the answer («нужен», «обратитесь», «билетам») must not count as covered decisions
    loose = ("Согласует руководитель подразделения. Если остаток по билетам меньше 1000 руб., процесс возвращается автору. "
             "Если нужен полный алгоритм, обратитесь к оператору.")
    assert len(gr.branch_gap(Q, loose, cited)) >= 3
