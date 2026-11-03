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
    "what a moment", "stay tuned", "everyone", "huge", "massive"
]

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

def get_ai_stats() -> Dict[str, Any]:
    return ai_stats

def reset_ai_stats() -> None:
    ai_stats["ai_count"] = 0
    ai_stats["fallback_count"] = 0
    ai_stats["reasons"].clear()

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

def prepare_event_facts(events: List[Dict]) -> List[Dict]:
    prepared = []
    for ev in events:
        c = dict(ev)
        if "driver" in c:
            c["driver"] = to_surname(c["driver"])
        if "passed" in c:
            c["passed"] = to_surname(c["passed"])
        if "time" in c and isinstance(c["time"], (int, float)):
            c["time"] = format_lap_time(float(c["time"]))
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

def validate_ai_text(text: str, allowed_numbers: Set[str]) -> Tuple[bool, str]:
    # 1. Banned words check: fall back to template rather than stripping words
    for b in BANNED_WORDS:
        if re.search(r"\b" + re.escape(b) + r"\b", text, re.I):
            return False, "banned phrase"

    # 2. Check for numerical hallucinations
    found_numbers = re.findall(r"\b\d+(?:\.\d+)?\b", text)
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
    if not config.AI_ENABLED or not config.GEMINI_API_KEY:
        return None

    client = get_gemini_client()
    if not client:
        return None

    prepared_events = prepare_event_facts(events)
    allowed_numbers = extract_allowed_numbers(events)

    prompt = (
        "You are a knowledgeable, casual friend watching F1 in a group chat with friends. "
        "Rewrite these exact race events into at most 2 short sentences.\n\n"
        "CRITICAL RULES:\n"
        "1. Lead with the single most important event.\n"
        "2. Add ONE plain-English 'why it matters' line for casual fans "
        "(general F1 knowledge allowed, e.g. 'a safety car closes up the field' or 'pitting under VSC saves about 10 seconds'). "
        "No race-specific claims beyond the facts provided.\n"
        "3. Use driver surnames, not acronym codes.\n"
        "4. Do NOT mention lap numbers.\n"
        "5. No exaggeration (banned words: 'everyone', 'huge', 'massive', 'thrilling', 'exciting', 'game-changer', 'buckle up', 'electrifying').\n"
        "6. Max 1 emoji across the message. Max 1 exclamation mark.\n"
        "7. Return ONLY strict JSON: {\"text\": \"your commentary here\"}\n\n"
        f"Events: {json.dumps(prepared_events)}"
    )

    try:
        from google.genai import types
        cfg = types.GenerateContentConfig(response_mime_type="application/json")
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

        valid, reason = validate_ai_text(text, allowed_numbers)
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

async def generate_ai_round_result(
    question: str,
    winner: str,
    explanation: str,
    scored_users: List[str],
    zero_users: List[str]
) -> Optional[str]:
    if not config.AI_ENABLED or not config.GEMINI_API_KEY:
        return None

    client = get_gemini_client()
    if not client:
        return None

    allowed_numbers = {"10", "0"}
    for match in re.findall(r"\d+(?:\.\d+)?", explanation):
        allowed_numbers.add(match)

    winner_name = to_surname(winner)

    prompt = (
        "You are a casual friend in an F1 group chat announcing the result of a live prediction round.\n"
        "Write a short result announcement plus ONE line of friendly banter about who got it right or wrong.\n\n"
        "CRITICAL RULES:\n"
        "1. State the winner and why in 1 short sentence.\n"
        "2. Add ONE line of friendly banter using ONLY the provided player names and points (10 pts for correct, 0 for wrong).\n"
        "3. Do not invent any names, numbers, or facts.\n"
        "4. Friendly group chat tone. Max 1 emoji. Max 1 exclamation mark.\n"
        "5. No exaggeration (banned words: 'everyone', 'huge', 'massive', 'thrilling', 'exciting', 'game-changer', 'buckle up').\n"
        "6. Return ONLY strict JSON: {\"text\": \"your text here\"}\n\n"
        f"Round Question: {question}\n"
        f"Winning Pick: {winner_name}\n"
        f"Fact: {explanation}\n"
        f"Players who scored 10 pts: {', '.join(scored_users) if scored_users else 'None'}\n"
        f"Players who scored 0 pts: {', '.join(zero_users) if zero_users else 'None'}"
    )

    try:
        from google.genai import types
        cfg = types.GenerateContentConfig(response_mime_type="application/json")
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

        valid, reason = validate_ai_text(text, allowed_numbers)
        if not valid:
            ai_stats["fallback_count"] += 1
            ai_stats["reasons"][reason] += 1
            return None

        ai_stats["ai_count"] += 1
        return _clean_text(text)

    except asyncio.TimeoutError:
        logger.info("AI fallback on round result: timeout (5s)")
        ai_stats["fallback_count"] += 1
        ai_stats["reasons"]["timeout"] += 1
        return None
    except Exception as e:
        err_msg = str(e)
        code_match = re.search(r"\b(4\d\d|5\d\d)\b", err_msg)
        code_str = f"HTTP {code_match.group(1)}" if code_match else type(e).__name__
        logger.info("AI fallback on round result: %s (%s)", code_str, err_msg[:80])
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
        overtakes_by_driver: Dict[str, Dict] = {}
        pit_events = []
        other_events = []

        for ev in events:
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

        for ev in other_events:
            txt = format_event_template(ev)
            if txt:
                lines.append(txt)

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
