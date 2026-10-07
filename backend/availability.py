from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple


def build_availability_payload(resp: dict) -> dict:
    if not resp.get("success"):
        raise RuntimeError(f"Backend returned success=false: {resp}")

    rd = resp.get("resultData") or {}
    time_list = rd.get("timeList") or []
    node_list = rd.get("nodeList") or []
    conflict_list = rd.get("conflictList") or []
    price_list = rd.get("priceList") or []

    times = [str(t.get("time")) for t in time_list]
    time_statuses = [str(t.get("status")) for t in time_list]
    courts = [str(n.get("sitename", f"场地{idx + 1}")) for idx, n in enumerate(node_list)]

    conflict_coords, conflict_codes_map = _parse_conflicts(conflict_list)
    prices = _parse_prices(price_list)

    grid: List[dict] = []
    for court_idx in range(len(courts)):
        for time_idx in range(len(times)):
            t_status = time_statuses[time_idx] if time_idx < len(time_statuses) else ""
            has_conflict = (court_idx, time_idx) in conflict_coords
            conflict_codes = conflict_codes_map.get((court_idx, time_idx), ())
            conflict_code = conflict_codes[0] if conflict_codes else ""
            available = bool(not has_conflict and t_status != "1")
            price = prices.get((court_idx, time_idx), "")
            grid.append(
                {
                    "courtIndex": court_idx,
                    "timeIndex": time_idx,
                    "price": price,
                    "available": available,
                    "conflictCode": conflict_code,
                    "conflictCodes": list(conflict_codes),
                    "timeStatus": t_status,
                }
            )

    meta = _extract_meta(rd)
    return {
        "times": times,
        "courts": courts,
        "grid": grid,
        "meta": meta,
        "raw": {
            "timeList": time_list,
            "nodeList": node_list,
            "conflictList": conflict_list,
            "priceList": price_list,
        },
    }


def _parse_conflicts(
    conflict_list: List[str],
) -> Tuple[Set[Tuple[int, int]], Dict[Tuple[int, int], Tuple[str, ...]]]:
    coords: Set[Tuple[int, int]] = set()
    codes: Dict[Tuple[int, int], set[str]] = {}
    for entry in conflict_list:
        parts = str(entry).split("-")
        if len(parts) >= 2:
            try:
                y = int(parts[0])
                x = int(parts[1])
            except ValueError:
                continue
            coords.add((y, x))
            code = parts[2] if len(parts) >= 3 else ""
            if code:
                codes.setdefault((y, x), set()).add(code)
    return coords, {key: tuple(sorted(values)) for key, values in codes.items()}


def _parse_prices(price_list: List[dict]) -> Dict[Tuple[int, int], str]:
    out: Dict[Tuple[int, int], str] = {}
    for price in price_list:
        try:
            x = int(price.get("x"))
            y = int(price.get("y"))
        except Exception:
            continue
        value = price.get("price")
        out[(y, x)] = str(value) if value is not None else ""
    return out


def _extract_meta(result_data: dict) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    for key, value in result_data.items():
        if isinstance(value, (list, dict)):
            continue
        meta[key] = value
    return meta
