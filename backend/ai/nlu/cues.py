"""Execution-request cues: what this assistant must refuse, and what it only records."""
from __future__ import annotations

import re

from backend.ai.nlu.text import norm

_CLAUSE = re.compile(r"[，。；;,.!?！？\n]+")
_NEGATION = re.compile(r"不要|不用|不必|别|无需|不需要|不想|不允许|禁止|不能|不可")
_ACTION = r"(?:预约|预订|订场|订|下单|付款|支付|扣款|购买|抢)"
# Wording that asks this assistant to act right now.
_COMMAND = (
    re.compile(r"(?:帮我|替我|给我|请你|你来|你去)[^，。；,.]{0,6}?(?:付款|支付|扣款|下单)"),
    re.compile(r"(?:直接|立即|立刻|马上|现在就|当场)[^，。；,.]{0,8}?" + _ACTION),
)
# Wording that describes what the later executor should do; recorded, never run.
_AUTOMATIC = re.compile(r"自动[^，。；,.]{0,8}?" + _ACTION)
_SCHEDULED = re.compile(r"到点|到时|届时|定时|准点|开放时|开抢|放号|每天|每周|开始时")
SCHEDULE_NOTE = "我只记录你想在开放时自动预约的意向；预约和付款由独立的执行器处理，这里不会代为执行。"
def classify_execution(turns: list[str]) -> tuple[bool, list[str]]:
    """Return (has_command, notes). Negations and scheduled wishes are not commands."""
    notes: list[str] = []
    for turn in turns:
        for clause in _CLAUSE.split(norm(turn)):
            for pattern in (*_COMMAND, _AUTOMATIC):
                match = pattern.search(clause)
                if match is None or _NEGATION.search(clause[max(0, match.start() - 3):match.end()]):  # negation must sit right at the action
                    continue
                if pattern is _AUTOMATIC or _SCHEDULED.search(clause):
                    if SCHEDULE_NOTE not in notes:
                        notes.append(SCHEDULE_NOTE)
                    break
                return True, notes
    return False, notes
