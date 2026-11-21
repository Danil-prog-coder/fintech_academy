"""Support shift schedule (FR-ESC-05, «вопросы зависают до утра»).

The bot knows when the human duty shift works (config SUPPORT_HOURS / SUPPORT_TZ). Out of hours the
escalation is still accepted immediately, but the user is told when the shift starts; the confidence
level also changes how the final event is phrased (see agent.loop.apply_hours_policy).

SUPPORT_HOURS format: "mon-fri 09:00-18:00; sat 10:00-14:00" (days: mon tue wed thu fri sat sun).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAYS_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
DAYS_RU_FULL = ["в понедельник", "во вторник", "в среду", "в четверг", "в пятницу", "в субботу", "в воскресенье"]


@dataclass(frozen=True)
class Window:
    day: int  # 0 = Monday
    start: int  # minutes from midnight
    end: int


def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def parse_hours(spec: str) -> list[Window]:
    out: list[Window] = []
    for part in [p.strip().lower() for p in (spec or "").split(";") if p.strip()]:
        m = re.fullmatch(r"([a-z]{3})(?:\s*-\s*([a-z]{3}))?\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", part)
        if not m:
            raise ValueError(f"bad SUPPORT_HOURS part: {part!r}")
        d1 = DAYS.index(m.group(1))
        d2 = DAYS.index(m.group(2)) if m.group(2) else d1
        days = range(d1, d2 + 1) if d2 >= d1 else [*range(d1, 7), *range(0, d2 + 1)]
        for d in days:
            out.append(Window(d, _hm(m.group(3)), _hm(m.group(4))))
    return out


class ShiftSchedule:
    def __init__(self, spec: str, tz: str) -> None:
        self.spec = spec
        self.tz = ZoneInfo(tz)
        self.windows = parse_hours(spec)

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def _local(self, now: datetime | None) -> datetime:
        if now is None:
            return self.now()
        return now.astimezone(self.tz) if now.tzinfo else now.replace(tzinfo=self.tz)

    def is_open(self, now: datetime | None = None) -> bool:
        t = self._local(now)
        mins = t.hour * 60 + t.minute
        return any(w.day == t.weekday() and w.start <= mins < w.end for w in self.windows)

    def next_open(self, now: datetime | None = None) -> datetime | None:
        """Start of the next shift (now if a shift is running)."""
        t = self._local(now)
        if self.is_open(t):
            return t
        base = t.replace(second=0, microsecond=0)
        for add in range(0, 8):
            day = (base + timedelta(days=add))
            starts = sorted(w.start for w in self.windows if w.day == day.weekday())
            for st in starts:
                cand = day.replace(hour=st // 60, minute=st % 60)
                if cand > t:
                    return cand
        return None

    def human(self) -> str:
        """«пн–пт 09:00–18:00» style summary."""
        groups: dict[tuple[int, int], list[int]] = {}
        for w in self.windows:
            groups.setdefault((w.start, w.end), []).append(w.day)
        parts = []
        for (st, en), days in groups.items():
            days = sorted(set(days))
            if len(days) > 1 and days == list(range(days[0], days[-1] + 1)):
                d = f"{DAYS_RU[days[0]]}–{DAYS_RU[days[-1]]}"
            else:
                d = ", ".join(DAYS_RU[x] for x in days)
            parts.append(f"{d} {st // 60:02d}:{st % 60:02d}–{en // 60:02d}:{en % 60:02d}")
        return "; ".join(parts)

    def describe_next(self, now: datetime | None = None) -> str:
        t = self._local(now)
        n = self.next_open(t)
        if n is None:
            return "в ближайшую смену"
        when = n.strftime("%H:%M")
        if n.date() == t.date():
            return f"сегодня в {when}"
        if n.date() == (t + timedelta(days=1)).date():
            return f"завтра в {when}"
        return f"{DAYS_RU_FULL[n.weekday()]} в {when}"

    def status(self, now: datetime | None = None) -> dict:
        t = self._local(now)
        n = self.next_open(t)
        return {"support_open": self.is_open(t), "support_hours": self.human(), "support_tz": str(self.tz),
                "next_shift_at": n.isoformat() if n else None, "next_shift_human": self.describe_next(t)}


_sched: ShiftSchedule | None = None


def get_schedule() -> ShiftSchedule:
    global _sched
    from .config import get_settings

    s = get_settings()
    if _sched is None or _sched.spec != s.support_hours:
        _sched = ShiftSchedule(s.support_hours, s.support_tz)
    return _sched
