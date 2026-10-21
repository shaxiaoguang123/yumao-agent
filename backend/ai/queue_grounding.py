"""Check semantic agreement between typed deltas and their quoted user evidence."""
from __future__ import annotations

import re
from copy import deepcopy

from backend.ai import queue_cues as cues
from backend.ai.nlu import courts, dates
from backend.ai.nlu.text import prep, norm, to_int
from backend.ai.nlu.times import scan_duration_mentions
from backend.ai.nlu.windows import scan_windows, resolve_start
from backend.ai.queue_draft import deserialize_draft

_REFERENCE = re.compile(r"前者|后者|第[一二三四五六七八九十0-9]+|前[一二三四五六七八九十0-9]+个|后[一二三四五六七八九十0-9]+个|刚才|之前|原来|上[一个次]|那个|这些|这几个|都|照你|按你|你说的")


def _values(field, draft):
    if field == "target_date":
        return [day.isoformat() for day in draft.dates]
    group = draft.g1 if field.endswith("_1h") else draft.g2
    return list(group.windows) if field.startswith("windows_") else list(group.courts)


def _references(field, evidence, draft, dialogue, history, today):
    if not _REFERENCE.search(evidence):
        return None
    values = _values(field, draft)
    question = next(("\n".join(item.get("questions", [])) for item in reversed(history)
                     if item.get("questions")), "")
    if re.search(r"之前|原来|上[一个次]|刚才.*(?:取消|删|去掉)", evidence):
        for record in reversed(dialogue["undo"]):
            if field in record["fields"]:
                values = _values(field, deserialize_draft(record["before"]))
                break
    elif question:
        if field == "target_date":
            options = [day.isoformat() for item in dates.scan_dates(courts.mask_courts(question), today) for day in item.dates]
        elif field.startswith("windows_"):
            options = [(item.start, item.end) for item in scan_windows(question).mentions
                       if item.kind == "range" and item.start is not None and item.end is not None and item.issue != "ambiguous"]
        else:
            options = [number for item in courts.scan_courts(question) for number in item.numbers]
        if options and (re.search(r"前者|后者|第|照你|按你|你说的", evidence)):
            values = list(dict.fromkeys(options))
    if not values:
        return None
    if "前者" in evidence:
        return values[:1]
    if "后者" in evidence:
        return values[-1:]
    match = re.search(r"第([一二三四五六七八九十0-9]+)", evidence)
    if match:
        index = to_int(match[1])
        return values[index - 1:index] if index and index <= len(values) else None
    match = re.search(r"(前|后)([一二三四五六七八九十0-9]+)个", evidence)
    if match:
        count = to_int(match[2])
        return (values[:count] if match[1] == "前" else values[-count:]) if count and count <= len(values) else None
    return values if len(values) == 1 or re.search(r"都|这些|这几个|照你|按你|你说的|刚才|之前|原来", evidence) else None


def _operation(text, pos, stop):
    mode = cues.mode_before(text, pos, cues.sentence_start(text, pos)) or cues.mode_after(text, stop)
    return {"append": "add", "only": "replace"}.get(mode, mode)


def _member_swaps(raw, positions, stops, source):
    for index in range(1, len(raw)):
        gap = source[stops[index - 1]:positions[index]]
        if raw[index][1] == "replace" and raw[index - 1][1] in {None, "remove"} and re.fullmatch(r"(?:时段|时间段)?(?:再)?(?:换成|换为|改成|改为)", gap):
            raw[index - 1] = (raw[index - 1][0], "remove")
            raw[index] = (raw[index][0], "add")
    return raw


def _operation_agrees(operation, modes, values, proposed, current):
    explicit = {mode for mode in modes if mode}
    if not explicit:
        return operation != "remove"
    if operation != "replace":
        return explicit <= {operation}
    # A whole-sentence replacement must agree with the final result of all quoted operations.
    final = list(current)
    for index, (numbers, mode) in enumerate(values):
        if mode == "remove":
            final = [value for value in final if value not in numbers]
        elif mode == "replace" or (mode is None and index == 0):
            final = list(numbers)
        else:
            final.extend(value for value in numbers if value not in final)
    return final == proposed


_NEGATED = re.compile(r"(?:不是|并非|而非|不要|不用|别选|不选|不订|不抢|去掉|取消|排除|不考虑)(?:再|选|订|抢|用|到|日期|日子|是|的|把|将)*$")
_CORRECTION = re.compile(r"(?:改(?:成|为|到|回)?|换(?:成|为|到)|调整(?:到|为)|更正为|而是|还是|就选|只选)$")
_NEGATED_CHANGE = re.compile(r"(?:不要|不用|别|不必|不想)(?:再)?(?:改(?:成|为|到|回)?|换(?:成|为|到)?|调整(?:到|为)?)$")


def _date_agrees(mentions, full, value):
    choices, cursor, negated_series = [], 0, False
    for mention in mentions:
        position = full.find(mention.text, cursor)
        if position < 0:
            return False
        prefix = full[max(cursor, cues.sentence_start(full, position)):position].rstrip(",，:：")
        cursor = position + len(mention.text)
        if _CORRECTION.search(prefix):
            choices, negated_series = [], False
        if _NEGATED.search(prefix) or _NEGATED_CHANGE.search(prefix):
            negated_series = True
            continue
        if negated_series and re.fullmatch(r"(?:或(?:者)?|和|及|以及|、)", prefix):
            continue
        negated_series = False
        if re.match(r"(?:先)?(?:不要|不选|不订|取消|排除|不考虑)(?:了|吧)?(?:$|[,，。；;!?！？])", full[cursor:]):
            continue
        if mention.ambiguous:
            choices.append(None)
        choices.extend(day.isoformat() for day in mention.dates)
    return list(dict.fromkeys(choices)) == [value]


def _context_hours(full, position):
    prefix = full[cues.sentence_start(full, position):position]
    matches = [(match.end(), minutes) for pattern, minutes in ((cues.ONE_HOUR, 60), (cues.TWO_HOUR, 120))
               for match in pattern.finditer(prefix)]
    if not matches:
        return None
    end, minutes = max(matches)
    # Choosing both queue types does not scope every following fact to the last type named.
    if re.search(r"(?:都|同时|一起).{0,3}(?:抢|订|排|选|要)", prefix[end:]):
        return None
    return minutes


def _scope_agrees(item, full, position):
    minutes = _context_hours(full, position)
    expected = 60 if item["field"].endswith("_1h") else 120
    if minutes is None or minutes == expected:
        return True
    if item["field"].startswith(("windows_", "courts_")):
        item["_clarification_field"] = item["field"][:-2] + ("1h" if minutes == 60 else "2h")
    return False


def _ground_update(item, latest, draft, dialogue, asking, history, today, peers, read):
    field, operation, value, evidence = (item[key] for key in ("field", "operation", "value", "evidence"))
    source, full = prep(evidence), prep(latest)
    item["_order"] = max(0, full.find(source))
    if full.count(source) != 1:
        return False
    offset = full.find(source)
    if operation == "clear":
        if not re.search(r"清空|全部.*(?:删|取消|去掉)|(?:删|取消|去掉).*(?:全部|所有)|重新填", source):
            return False
        scope = source if re.search(r"日期|日子|场地|号场|时段|时间|类型", source) else full
        named = [name for pattern, name in ((r"日期|日子", "target_date"), (r"类型", "booking_mode"),
                 (r"场地|号场", "courts_"), (r"时段|时间", "windows_")) if re.search(pattern, scope)]
        if named and not any(field == name or field.startswith(name) for name in named):
            return False
        if not named and asking != field and not re.search(r"全部|所有", scope):
            return False
        groups = ({"1h"} if cues.ONE_HOUR.search(scope) else set()) | ({"2h"} if cues.TWO_HOUR.search(scope) else set())
        if groups and field.endswith(("_1h", "_2h")) and field[-2:] not in groups:
            if len(groups) == 1 and field.startswith(("windows_", "courts_")):
                item["_clarification_field"] = field[:-2] + next(iter(groups))
            return False
        return True
    if field == "booking_mode":
        return True  # Explicit numbered/mode choice is checked by the coordinator.
    if field.startswith("overlap_"):
        for word in cues.KEEP_STRONG:
            for match in re.finditer(re.escape(word), source):
                position = offset + match.start()
                if (not _NEGATED.search(full[cues.sentence_start(full, position):position])
                        and _scope_agrees(item, full, position)):
                    return True
        return (asking == field and source.strip("。！.! ") in cues.KEEP_WEAK
                and _scope_agrees(item, full, offset + len(source)))
    if field == "target_date":
        mentions = read("dates", full)
        if mentions:
            return _date_agrees(mentions, full, value)
        referenced = _references(field, source, draft, dialogue, history, today)
        return referenced == [value]
    minutes = 60 if field.endswith("_1h") else 120
    group = draft.groups[minutes]
    if field.startswith("windows_"):
        scan = read("windows", source)
        durations = read("durations", source)
        raw, positions, stops, other_groups = [], [], [], set()
        for mention in scan.mentions:
            hint = _context_hours(full, offset + mention.pos)
            inferred = hint or (mention.end - mention.start if mention.end is not None and mention.start is not None else minutes)
            if inferred in (60, 120) and inferred != minutes:
                other_groups.add(inferred)
                continue
            if mention.kind == "range":
                if mention.issue == "ambiguous":
                    return False
                if mention.start is None or mention.end is None:
                    literal = re.fullmatch(r"([0-9]{1,2})(?::([0-9]{2}))?[到至~\-—–]([0-9]{1,2})(?::([0-9]{2}))?", mention.text)
                    if literal is None:
                        return False
                    pair = int(literal[1]) * 60 + int(literal[2] or 0), int(literal[3]) * 60 + int(literal[4] or 0)
                else:
                    pair = (mention.start, mention.end)
            else:
                start, end, issue = resolve_start(mention, minutes)
                if issue == "ambiguous" or start is None or end is None:
                    return False
                pair = start, end
            raw.append(([pair], _operation(scan.text, mention.pos, mention.stop)))
            positions.append(mention.pos)
            stops.append(mention.stop)
        raw = _member_swaps(raw, positions, stops, scan.text)
        proposed = [(int(window["start"][:2]) * 60 + int(window["start"][3:]),
                     int(window["end"][:2]) * 60 + int(window["end"][3:])) for window in value]
        if not raw:
            if len(other_groups) == 1:
                item["_clarification_field"] = field[:-2] + ("1h" if other_groups.pop() == 60 else "2h")
                return False
            if not _scope_agrees(item, full, offset + len(source)):
                return False
            if durations and durations[-1][1] == minutes and group.windows:
                item["resolves_duration"] = True
                return proposed == group.windows
            referenced = _references(field, source, draft, dialogue, history, today)
            return referenced == proposed and (operation != "remove" or bool(re.search(r"去|删|不要|取消|后者|前者|第", source)))
        selected = [(entry, position) for entry, position in zip(raw, positions) if entry[1] == operation]
        if operation != "replace" and selected:
            raw, positions = map(list, zip(*selected))
        item["_order"] += min(positions)
        expected = list(dict.fromkeys(pair for pairs, _mode in raw for pair in pairs))
        modes = [mode for _pairs, mode in raw]
        aggregate = _operation_agrees(operation, modes, raw, proposed, group.windows)
        if proposed != expected and not (operation == "replace" and aggregate and any(modes)):
            return False
        if durations and durations[-1][1] == minutes:
            item["resolves_duration"] = True
        return aggregate
    # Expand a quoted fragment to its enclosing court range/list, preventing 1-11 -> [1, 11] or [1].
    position = full.find(source)
    for mention in read("courts", full):
        if position >= mention.pos and position + len(source) <= mention.pos + len(mention.text):
            source = full[max(cues.sentence_start(full, mention.pos), mention.pos - 10):mention.pos + len(mention.text)]
            break
    mentions = list(read("courts", source)) or list(read("bare_courts", source))
    mentions += [courts.CourtMention(match[0], tuple(range(1, 11)), False, match.start())
                 for match in courts.ALL_COURTS.finditer(source)]
    mentions.sort(key=lambda mention: mention.pos)
    offset = full.find(source)
    if not mentions:
        if not _scope_agrees(item, full, offset + len(source)):
            return False
        referenced = _references(field, source, draft, dialogue, history, today)
        return referenced == value and (operation != "remove" or bool(re.search(r"去|删|不要|取消|后者|前者|第", source)))
    windows = read("windows", source).mentions
    raw, positions, stops, other_groups = [], [], [], set()
    for mention in mentions:
        preceding = next((window for window in reversed(windows) if window.stop <= mention.pos), None)
        inferred = _context_hours(full, offset + mention.pos)
        if inferred is None and preceding and preceding.start is not None and preceding.end is not None:
            inferred = preceding.end - preceding.start
        if inferred in (60, 120) and inferred != minutes:
            other_groups.add(inferred)
            continue
        raw.append((list(mention.numbers), "remove" if mention.negated else _operation(source, mention.pos, mention.pos + len(mention.text))))
        positions.append(mention.pos)
        stops.append(mention.pos + len(mention.text))
    raw = _member_swaps(raw, positions, stops, source)
    if not raw:
        if len(other_groups) == 1:
            item["_clarification_field"] = field[:-2] + ("1h" if other_groups.pop() == 60 else "2h")
        return False
    selected = [(entry, position) for entry, position in zip(raw, positions) if entry[1] == operation]
    if operation != "replace" and selected:
        raw, positions = map(list, zip(*selected))
    item["_order"] = max(0, full.find(source)) + min(positions)
    expected = list(dict.fromkeys(number for numbers, _mode in raw for number in numbers))
    modes = [mode for _numbers, mode in raw]
    aggregate = _operation_agrees(operation, modes, raw, value, group.courts)
    peer_values = list(dict.fromkeys(number for peer in peers
                                    if peer["field"] == field and peer["operation"] == operation
                                    and prep(peer["evidence"]) == prep(evidence) for number in peer["value"]))
    return aggregate and (value == expected or peer_values == expected or operation == "replace" and any(modes))


def ground_decision(decision, latest, draft, dialogue, asking, history, today):
    result = deepcopy(decision)
    errors, accepted, cache = [], [], {}
    parsers = {"dates": lambda source: dates.scan_dates(courts.mask_courts(source), today),
               "windows": scan_windows, "durations": scan_duration_mentions,
               "courts": courts.scan_courts, "bare_courts": courts.scan_bare_courts}
    def read(kind, source):
        key = kind, prep(source)
        if key not in cache:
            cache[key] = parsers[kind](key[1])
        return cache[key]
    action = result.get("dialogue_action", {"type": "continue", "fields": [], "evidence": ""})
    expressions = {"begin_edit": r"改|调整|换|重新|日期|时间|时段|场地|类型", "cancel_edit": r"取消.*(?:编辑|修改)|不改|算了|保持原样", "undo": r"撤销|回退|还原|改回|恢复"}
    if action["type"] != "continue" and not re.search(expressions[action["type"]], action["evidence"]):
        errors.append({"field": None, "reason": "ungrounded_dialogue_action", "evidence": action["evidence"]})
        result["dialogue_action"] = {"type": "continue", "fields": [], "evidence": ""}
    if action["type"] in {"begin_edit", "undo"} and result.get("dialogue_action", action)["type"] == action["type"]:
        scope = action["evidence"]
        if not re.search(r"日期|日子|哪天|场地|号场|时段|时间|类型|队列种类", scope):
            scope = latest
        categories = set()
        for pattern, category in ((r"日期|日子|哪天", "target_date"), (r"场地|号场", "courts_"),
                                  (r"时段|时间", "windows_"), (r"类型|队列种类", "booking_mode")):
            if re.search(pattern, scope):
                categories.add(category)
        durations = ({"1h"} if cues.ONE_HOUR.search(scope) else set()) | ({"2h"} if cues.TWO_HOUR.search(scope) else set())
        wrong_category = categories and any(not any(field == category or field.startswith(category)
                                                     or category == "windows_" and field.startswith("overlap_")
                                                     for category in categories) for field in action["fields"])
        wrong_duration = durations and any(field.endswith(("_1h", "_2h")) and field[-2:] not in durations for field in action["fields"])
        if wrong_category or wrong_duration:
            errors.append({"field": None, "reason": "dialogue_scope_mismatch", "evidence": action["evidence"]})
            result["dialogue_action"] = {"type": "begin_edit", "fields": [], "evidence": action["evidence"]}
            result["next_field"], result["dialogue_focus"] = None, None
            result["next_action"] = "clarify_edit"
            result["next_question"] = "请确认要修改或撤销哪一项，例如2小时场地。"
        elif action["type"] == "undo" and not categories and not durations:
            result["dialogue_action"]["fields"] = []  # A bare undo rolls back the whole last fact transaction.
    for item in result["updates"]:
        if _ground_update(item, latest, draft, dialogue, asking, history, today, result["updates"], read):
            accepted.append(item)
        else:
            errors.append({"field": item["field"], "reason": "evidence_value_or_operation_mismatch",
                           "evidence": item["evidence"], "proposed_value": deepcopy(item["value"]),
                           **({"clarification_field": item["_clarification_field"]} if "_clarification_field" in item else {})})
    for field in dict.fromkeys(item["field"] for item in accepted):
        sequence = [item["_order"] for item in accepted if item["field"] == field and "_order" in item]
        if sequence != sorted(sequence):
            errors.append({"field": field, "reason": "operation_order_mismatch", "evidence": latest[:240]})
            accepted = [item for item in accepted if item["field"] != field]
    for item in result["updates"]:
        item.pop("_order", None)
        item.pop("_clarification_field", None)
    rejected_fields = {error["field"] for error in errors if error["field"]}
    accepted = [item for item in accepted if item["field"] not in rejected_fields]
    result["updates"] = accepted
    if result["kind"] != "question" and result.get("intent", "queue") == "queue":
        scan = read("windows", latest)
        def block(field, evidence, issue, **details):
            if not any(item["field"] == field and item.get("issue") == issue for item in result["unresolved"]):
                result["unresolved"] = [item for item in result["unresolved"] if item["field"] != field]
                result["unresolved"].append({"field": field, "evidence": evidence, "issue": issue, **details})
        for mention in scan.mentions:
            if (not mention.issue or _operation(scan.text, mention.pos, mention.stop) == "remove"
                    or re.match(r"(?:号|场|限制|编号|范围|项|元)", scan.text[mention.stop:])):
                continue
            covered = any(prep(mention.text) in prep(item["evidence"]) for item in accepted + result["unresolved"])
            superseded = any(item["operation"] == "replace" and item["field"].startswith("windows_")
                             and prep(latest).find(prep(item["evidence"])) >= mention.stop
                             and re.search(r"改|换|只留", prep(latest)[mention.stop:prep(latest).find(prep(item["evidence"])) + len(prep(item["evidence"]))])
                             for item in accepted)
            if not covered and not superseded:
                minutes = cues.governing_hours(scan.text[:mention.pos]) or (60 if (asking or "").endswith("_1h") else 120)
                block("windows_1h" if minutes == 60 else "windows_2h", mention.text, mention.issue)
        durations = read("durations", latest)
        if durations and durations[-1][1] not in (60, 120):
            evidence, unsupported, position = durations[-1]
            minutes = (cues.governing_hours(norm(latest)[:position]) or
                       (60 if (asking or "").endswith("_1h") or draft.booking_mode == "one_hour_only" else 120))
            block("windows_1h" if minutes == 60 else "windows_2h", evidence,
                  "unsupported_duration", duration_minutes=unsupported)
    for error in errors:
        field = error.get("clarification_field", error["field"])
        if field and not any(item["field"] == field for item in result["unresolved"]):
            result["unresolved"].append({"field": field, "issue": "ambiguous", "evidence": error["evidence"]})
    result["semantic_errors"] = errors
    if errors:
        result["reply"] = ""
    return result
