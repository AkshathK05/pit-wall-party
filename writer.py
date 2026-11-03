import re
import json
import logging
import asyncio
from collections import Counter
from typing import List, Dict, Optional, Set, Any, Tuple

import config

logger = logging.getLogger("pitwall.writer")

BANNED_WORDS = [
    "exciting", "buckle up", "get ready", "let's dive in", "unleash",
    "elevate", "seamless", "game-changer", "thrilling", "electrifying",
    "what a moment", "stay tuned", "everyone", "huge", "massive",
    "crucial", "valuable", "championship points", "completely",
    "half the grid", "whole grid", "actually nailed"
]

WORD_TO_DIGIT = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "hundred": "100",
    "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5",
    "sixth": "6", "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10"
}

DRIVER_SURNAMES = {
    "VER": "Verstappen", "NOR": "Norris", "LEC": "Leclerc", "RUS": "Russell",
    "HAM": "Hamilton", "GAS": "Gasly", "OCO": "Ocon", "PIA": "Piastri",
    "TSU": "Tsunoda", "LAW": "Lawson", "ALO": "Alonso", "SAI": "Sainz",
    "PER": "Perez", "HUL": "Hulkenberg", "BOT": "Bottas", "ZHO": "Zhou",
    "COL": "Colapinto", "BEA": "Bearman"
}

ai_stats = {
    "ai_count": 0,
    "fallback_count": 0,
    "reasons": Counter()
}

_recent_banter: List[str] = []

def get_ai_stats() -> Dict[str, Any]:
    return ai_stats

def reset_ai_stats() -> None:
    ai_stats["ai_count"] = 0
    ai_stats["fallback_count"] = 0
    ai_stats["reasons"].clear()
    _recent_banter.clear()

_gemini_client = None

def get_gemini_client():
    global _gemini_client
    if _gemini_client is None and config.GEMINI_API_KEY:
        from google import genai
        _gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _gemini_client

def _clean_text(text: str) -> str:
    cleaned = text
    if cleaned.count("!") > 1:
        parts = cleaned.split("!")
        cleaned = parts[0] + "!" + "".join(parts[1:]).replace("!", ".")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in cleaned.splitlines()]
    return "\n".join(l for l in lines if l)

def format_lap_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m}:{s:06.3f}"

def to_surname(code: str) -> str:
    return DRIVER_SURNAMES.get(code, code)

def event_priority(e: Dict) -> int:
    t = e.get("type", "")
    if t == "red_flag":
        return 1
    if t in ("safety_car_deployed", "safety_car_ending", "vsc_deployed", "vsc_ending"):
        return 2
    if t == "overtake" and e.get("new_position") == 1:
        return 3
    if t == "penalty":
        return 4
    if t == "overtake":
        return 5
    if t == "pit":
        return 6
    return 7

def get_why_it_matters_line(events: List[Dict]) -> Optional[str]:
    # Only add for: SC, VSC, red flag, penalty, lead change. Overtakes and pits never get one.
    for ev in events:
        t = ev.get("type", "")
        if t == "red_flag":
            return "Red flag rules allow teams a free tire change in the pit lane."
        if t == "safety_car_deployed":
            return "The safety car bunches up the pack and wipes out all time gaps."
        if t == "vsc_deployed":
            return "Pitting under a VSC costs less time because everyone else is driving slower."
        if t == "penalty":
            return "Time penalties are served at the next pit stop or added at the finish."
        if t == "overtake" and ev.get("new_position") == 1:
            return "Leading the race gives clean air and lets the driver control the pace."
    return None

def prepare_event_facts(events: List[Dict]) -> List[Dict]:
    sorted_events = sorted(events, key=event_priority)
    prepared = []
    for ev in sorted_events:
        c = dict(ev)
        if "driver" in c:
            c["driver"] = to_surname(c["driver"])
        if "passed" in c:
            c["passed"] = to_surname(c["passed"])
        if "time" in c and isinstance(c["time"], (int, float)):
            c["time"] = format_lap_time(float(c["time"]))

        # Grid position in facts ONLY for lead changes, nowhere else
        is_lead_change = (c.get("type") == "overtake" and c.get("new_position") == 1)
        if not is_lead_change:
            c.pop("starting_grid", None)
            c.pop("grid_position", None)
            c.pop("grid", None)

        # Never pass pit durations >= 10s to the AI
        if c.get("type") == "pit":
            dur = c.get("duration")
            if dur is not None:
                try:
                    if float(dur) >= 10.0:
                        c.pop("duration", None)
                except (ValueError, TypeError):
                    c.pop("duration", None)

        prepared.append(c)
    return prepared

def extract_allowed_numbers(events: List[Dict], extra_numbers: Optional[Set[str]] = None) -> Set[str]:
    numbers = set(extra_numbers or [])
    for ev in events:
        for k, v in ev.items():
            if isinstance(v, (int, float)):
                numbers.add(str(v))
                if isinstance(v, float):
                    numbers.add(str(int(v)))
                    numbers.add(format_lap_time(v))
                    m = int(v // 60)
                    s = v % 60
                    numbers.add(str(m))
                    numbers.add(f"{s:.3f}")
                    numbers.add(f"{s:.1f}")
            elif isinstance(v, str):
                for match in re.findall(r"\d+(?:\.\d+)?", v):
                    numbers.add(match)
    return numbers

def validate_ai_text(text: str, allowed_numbers: Set[str], is_lead_change: bool = False) -> Tuple[bool, str]:
    for b in BANNED_WORDS:
        if re.search(r"\b" + re.escape(b) + r"\b", text, re.I):
            return False, "banned phrase"

    # If AI text mentions "grid" or "started" and the event is not a lead change, fall back to template
    if not is_lead_change:
        if re.search(r"\b(grid|started)\b", text, re.I):
            return False, "grid/started without lead change"

    normalized = text.lower()
    for word, digit in WORD_TO_DIGIT.items():
        normalized = re.sub(r"\b" + re.escape(word) + r"\b", digit, normalized)

    found_numbers = re.findall(r"\b\d+(?:\.\d+)?\b", normalized)
    for num in found_numbers:
        if num not in allowed_numbers:
            matching = False
            for allowed in allowed_numbers:
                if num in allowed:
                    matching = True
                    break
            if not matching:
                return False, "number check"

    return True, ""

async def generate_ai_commentary(events: List[Dict]) -> Optional[str]:
    if not config.AI_ENABLED or not config.GEMINI_API_KEY or not config.GEMINI_MODEL:
        return None

    client = get_gemini_client()
    if not client:
        return None

    prepared_events = prepare_event_facts(events)
    allowed_numbers = extract_allowed_numbers(prepared_events)

    prompt = (
        "You are a knowledgeable, casual friend watching F1 in a group chat with friends. "
        "Rewrite these exact race events into 1-2 lively, casual chat sentences.\n\n"
        "CRITICAL RULES:\n"
        "1. Lead with the single most important event.\n"
        "2. For lead changes, mention that the driver started from their starting grid position.\n"
        "3. Use driver surnames, not acronym codes.\n"
        "4. Do NOT mention lap numbers.\n"
        "5. No exaggeration (banned words: 'everyone', 'huge', 'massive', 'crucial', 'valuable', 'championship points', 'completely', 'thrilling', 'exciting', 'game-changer', 'buckle up', 'electrifying', 'half the grid', 'whole grid', 'actually nailed').\n"
        "6. Max 1 emoji across the message. Max 1 exclamation mark.\n"
        "7. Return ONLY strict JSON: {\"text\": \"your commentary here\"}\n\n"
        f"Events: {json.dumps(prepared_events)}"
    )

    try:
        from google.genai import types
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
        )
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt,
                config=cfg
            ),
            timeout=5.0
        )
        if not response or not response.text:
            ai_stats["fallback_count"] += 1
            ai_stats["reasons"]["bad JSON"] += 1
            return None

        try:
            data = json.loads(response.text)
        except Exception:
            ai_stats["fallback_count"] += 1
            ai_stats["reasons"]["bad JSON"] += 1
            return None

        text = data.get("text", "").strip()
        if not text:
            ai_stats["fallback_count"] += 1
            ai_stats["reasons"]["bad JSON"] += 1
            return None

        is_lead_change = any(e.get("type") == "overtake" and e.get("new_position") == 1 for e in events)
        valid, reason = validate_ai_text(text, allowed_numbers, is_lead_change=is_lead_change)
        if not valid:
            ai_stats["fallback_count"] += 1
            ai_stats["reasons"][reason] += 1
            return None

        ai_stats["ai_count"] += 1
        return _clean_text(text)

    except asyncio.TimeoutError:
        logger.info("AI fallback on lap commentary: timeout (5s)")
        ai_stats["fallback_count"] += 1
        ai_stats["reasons"]["timeout"] += 1
        return None
    except Exception as e:
        err_msg = str(e)
        code_match = re.search(r"\b(4\d\d|5\d\d)\b", err_msg)
        code_str = f"HTTP {code_match.group(1)}" if code_match else type(e).__name__
        logger.info("AI fallback on lap commentary: %s (%s)", code_str, err_msg[:80])
        ai_stats["fallback_count"] += 1
        ai_stats["reasons"][f"API error ({code_str})"] += 1
        return None

async def generate_ai_round_banter(
    question: str,
    correct_answer: str,
    winner_names: List[str],
    loser_names: List[str],
    current_leader: str,
    recent_banter: Optional[List[str]] = None
) -> Optional[str]:
    if not config.AI_ENABLED or not config.GEMINI_API_KEY or not config.GEMINI_MODEL:
        return None

    client = get_gemini_client()
    if not client:
        return None

    past_banters = recent_banter if recent_banter is not None else _recent_banter[-2:]
    history_note = ""
    if past_banters:
        history_items = "\n".join(f"- \"{b}\"" for b in past_banters[-2:])
        history_note = (
            f"\nPrevious round banter lines (DO NOT reuse their phrasing, wording, or structure):\n{history_items}\n"
        )

    prompt = (
        "You are a casual friend in an F1 group chat. "
        "Write ONLY ONE short line of friendly banter about who got the prediction right or wrong.\n\n"
        "CRITICAL RULES:\n"
        "1. Write ONLY ONE line of friendly banter. Do NOT repeat or restate the question or winner.\n"
        "2. Use ONLY the provided player names. Do NOT invent any numbers or points.\n"
        "3. Max 1 emoji. Max 1 exclamation mark.\n"
        "4. No mean banter, no buzzwords (banned words: 'actually nailed', 'half the grid', 'whole grid', 'everyone').\n"
        "5. Do NOT reuse wording, phrasing, or sentence patterns from the previous banter lines.\n"
        "6. Return ONLY strict JSON: {\"banter\": \"your banter line here\"}\n\n"
        f"Question: {question}\n"
        f"Correct Answer: {correct_answer}\n"
        f"Players who got it right: {', '.join(winner_names) if winner_names else 'None'}\n"
        f"Players who missed: {', '.join(loser_names) if loser_names else 'None'}\n"
        f"Group Leader: {current_leader}"
        f"{history_note}"
    )

    try:
        from google.genai import types
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
        )
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt,
                config=cfg
            ),
            timeout=5.0
        )
        if not response or not response.text:
            ai_stats["fallback_count"] += 1
            ai_stats["reasons"]["bad JSON"] += 1
            return None

        try:
            data = json.loads(response.text)
        except Exception:
            ai_stats["fallback_count"] += 1
            ai_stats["reasons"]["bad JSON"] += 1
            return None

        banter = data.get("banter", "").strip()
        if not banter:
            ai_stats["fallback_count"] += 1
            ai_stats["reasons"]["bad JSON"] += 1
            return None

        valid, reason = validate_ai_text(banter, set(), is_lead_change=False)
        if not valid:
            ai_stats["fallback_count"] += 1
            ai_stats["reasons"][reason] += 1
            return None

        ai_stats["ai_count"] += 1
        cleaned_banter = _clean_text(banter)
        _recent_banter.append(cleaned_banter)
        return cleaned_banter

    except asyncio.TimeoutError:
        logger.info("AI fallback on round banter: timeout (5s)")
        ai_stats["fallback_count"] += 1
        ai_stats["reasons"]["timeout"] += 1
        return None
    except Exception as e:
        err_msg = str(e)
        code_match = re.search(r"\b(4\d\d|5\d\d)\b", err_msg)
        code_str = f"HTTP {code_match.group(1)}" if code_match else type(e).__name__
        logger.info("AI fallback on round banter: %s (%s)", code_str, err_msg[:80])
        ai_stats["fallback_count"] += 1
        ai_stats["reasons"][f"API error ({code_str})"] += 1
        return None

def format_event_template(event: Dict) -> str:
    etype = event.get("type", "")
    if etype == "start":
        leader = to_surname(event.get("leader", "Leader"))
        gainer = to_surname(event.get("biggest_gainer", "Driver"))
        gained = event.get("places_gained", 0)
        return f"{leader} holds the lead into turn 1. {gainer} gained {gained} places off the start."
    if etype == "pit":
        d = to_surname(event.get("driver", "Driver"))
        dur = event.get("duration")
        if dur and float(dur) < 10.0:
            return f"{d} heads into the pits ({dur}s stop)."
        return f"{d} heads into the pits."
    if etype == "vsc_deployed":
        return "Virtual Safety Car deployed."
    if etype == "vsc_ending":
        return "VSC ending, back to green."
    if etype == "safety_car_deployed":
        return "Safety Car deployed. Pack bunches up."
    if etype == "safety_car_ending":
        return "Safety Car coming in this lap."
    if etype == "red_flag":
        return "Red flag. Race halted, all cars into pit lane."
    if etype == "penalty":
        d = to_surname(event.get("driver", "Driver"))
        desc = event.get("description", "time penalty")
        if not desc.startswith(d):
            return f"{d} gets a {desc}."
        return f"{desc}."
    if etype == "fastest_lap":
        d = to_surname(event.get("driver", "Driver"))
        t = event.get("time", 0.0)
        formatted_t = format_lap_time(float(t)) if isinstance(t, (int, float)) else str(t)
        return f"New fastest lap by {d}: {formatted_t}."
    return ""

def format_lap_message(
    lap: int,
    total_laps: int,
    events: List[Dict],
    show_header: bool = False,
    ai_text: Optional[str] = None
) -> Optional[str]:
    lines = []
    if show_header:
        lines.append(f"Lap {lap}/{total_laps}")

    if ai_text:
        lines.append(ai_text)
    else:
        sorted_events = sorted(events, key=event_priority)
        overtakes_by_driver: Dict[str, Dict] = {}
        pit_events = []
        other_events = []

        for ev in sorted_events:
            etype = ev.get("type")
            if etype == "overtake":
                d = to_surname(ev.get("driver", "Driver"))
                if d not in overtakes_by_driver:
                    overtakes_by_driver[d] = {
                        "driver": d,
                        "passed": [],
                        "new_position": ev.get("new_position")
                    }
                overtakes_by_driver[d]["passed"].append(to_surname(ev.get("passed", "car")))
                overtakes_by_driver[d]["new_position"] = min(
                    overtakes_by_driver[d]["new_position"],
                    ev.get("new_position", 99)
                )
            elif etype == "pit":
                pit_events.append(ev)
            else:
                other_events.append(ev)

        for ev in other_events:
            txt = format_event_template(ev)
            if txt:
                lines.append(txt)

        for d, oinfo in overtakes_by_driver.items():
            passed = oinfo["passed"]
            pos = oinfo["new_position"]
            if len(passed) == 1:
                lines.append(f"{d} gets past {passed[0]}, up to P{pos}.")
            elif len(passed) == 2:
                lines.append(f"{d} gets past {passed[0]} and {passed[1]}, up to P{pos}.")
            else:
                passed_str = ", ".join(passed[:-1]) + f" and {passed[-1]}"
                lines.append(f"{d} gets past {passed_str}, up to P{pos}.")

        if len(pit_events) > 3:
            drivers = [to_surname(p["driver"]) for p in pit_events]
            sample = ", ".join(drivers[:3])
            lines.append(f"Heavy pit activity: {len(drivers)} cars pit, including {sample}.")
        else:
            for p in pit_events:
                txt = format_event_template(p)
                if txt:
                    lines.append(txt)

    # In code enforcement: only add why-it-matters line for SC, VSC, red flag, penalty, lead change
    why_line = get_why_it_matters_line(events)
    if why_line:
        lines.append(why_line)

    if not lines:
        return None

    msg = "\n".join(lines)
    return _clean_text(msg)

def format_leaderboard(scores: List[Dict]) -> str:
    if not scores:
        return "Leaderboard:\nNo points scored yet."
    lines = ["Leaderboard:"]
    for idx, s in enumerate(scores, 1):
        lines.append(f"{idx}. {s['name']} - {s['score']} pts")
    return "\n".join(lines)

def format_final_results(top3: List[str], leaderboard: List[Dict]) -> str:
    podium = " | ".join(f"P{i+1}: {to_surname(code)}" for i, code in enumerate(top3))
    lb = format_leaderboard(leaderboard)
    return _clean_text(f"Race complete!\nPodium: {podium}\n\n{lb}")
