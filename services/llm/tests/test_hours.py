from datetime import datetime
from zoneinfo import ZoneInfo

from rag_service.agent.loop import SUPPORT_BUTTON, apply_hours_policy
from rag_service.core.hours import ShiftSchedule

MSK = ZoneInfo("Europe/Moscow")
S = ShiftSchedule("mon-fri 09:00-18:00", "Europe/Moscow")


def test_open_and_closed():
    assert S.is_open(datetime(2026, 11, 16, 11, 0, tzinfo=MSK))  # Monday
    assert not S.is_open(datetime(2026, 11, 16, 18, 0, tzinfo=MSK))
    assert not S.is_open(datetime(2026, 11, 14, 12, 0, tzinfo=MSK))  # Saturday


def test_next_open():
    fri_night = datetime(2026, 11, 13, 23, 0, tzinfo=MSK)
    assert S.next_open(fri_night) == datetime(2026, 11, 16, 9, 0, tzinfo=MSK)
    assert S.describe_next(fri_night) == "в понедельник в 09:00"
    assert S.describe_next(datetime(2026, 11, 17, 7, 0, tzinfo=MSK)) == "сегодня в 09:00"
    assert S.describe_next(datetime(2026, 11, 17, 20, 0, tzinfo=MSK)) == "завтра в 09:00"


def test_human_and_multi_windows():
    s = ShiftSchedule("mon-fri 09:00-18:00; sat 10:00-14:00", "Europe/Moscow")
    assert s.human() == "пн–пт 09:00–18:00; сб 10:00–14:00"
    assert s.is_open(datetime(2026, 11, 14, 11, 0, tzinfo=MSK))


def _answer(level):
    return {"action": "answer", "text": "Ответ [1]", "sources": [{"source_id": "S1"}], "confidence_level": level, "buttons": []}


def test_policy_in_hours_is_unchanged():
    st = S.status(datetime(2026, 11, 16, 11, 0, tzinfo=MSK))
    r = apply_hours_policy(_answer("medium"), st)
    assert r["text"] == "Ответ [1]" and r["buttons"] == []
    esc = apply_hours_policy({"action": "escalate", "text": "Передаю"}, st)
    assert esc["text"] == "Передаю"


def test_policy_out_of_hours():
    st = S.status(datetime(2026, 11, 14, 23, 0, tzinfo=MSK))
    esc = apply_hours_policy({"action": "escalate", "text": "Передаю"}, st)
    assert "нерабочее время" in esc["text"] and "в понедельник в 09:00" in esc["text"] and esc["queued_until_shift"]
    off = apply_hours_policy({"action": "offer_operator", "text": "Я пока не нашёл точного ответа. Переключить на оператора?", "buttons": [SUPPORT_BUTTON]}, st)
    assert off["text"].startswith("Я пока не нашёл точного ответа") and "нерабочее время" in off["text"]
    low = apply_hours_policy(_answer("low"), st)
    assert SUPPORT_BUTTON in low["buttons"] and "нерабочее время" in low["text"]
    high = apply_hours_policy(_answer("high"), st)
    assert high["text"] == "Ответ [1]" and high["buttons"] == []


def test_policy_is_idempotent_for_cached_answers():
    """A cached answer already carries the out-of-hours note: serving it again must not duplicate the note,
    and a note with a stale shift time («сегодня в 09:00» stored yesterday) is replaced by the current one."""
    fri = S.status(datetime(2026, 11, 13, 23, 0, tzinfo=MSK))
    first = apply_hours_policy(_answer("medium"), fri)
    cached = {**first, "buttons": list(first["buttons"])}
    again = apply_hours_policy(cached, S.status(datetime(2026, 11, 17, 7, 0, tzinfo=MSK)))
    assert again["text"].count("нерабочее время") == 1 and "сегодня в 09:00" in again["text"]
    assert again["buttons"].count(SUPPORT_BUTTON) == 1
    off = apply_hours_policy({"action": "offer_operator", "text": "Переключить на оператора?", "buttons": [SUPPORT_BUTTON]}, fri)
    assert apply_hours_policy(dict(off), fri)["text"].count("нерабочее время") == 1
    in_hours = apply_hours_policy(dict(first), S.status(datetime(2026, 11, 16, 11, 0, tzinfo=MSK)))
    assert "нерабочее время" not in in_hours["text"], "в рабочее время старая пометка из кэша убирается"
