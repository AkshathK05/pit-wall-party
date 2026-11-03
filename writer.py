import re
import json
import logging
import asyncio
from typing import List, Dict, Optional, Set, Any

import config

logger = logging.getLogger("pitwall.writer")

BANNED_WORDS = [
    "exciting", "buckle up", "get ready", "let's dive in", "unleash",
    "elevate", "seamless", "game-changer", "thrilling", "electrifying",
    "what a moment", "stay tuned"
]

_gemini_client = None

def get_gemini_client():
    global _gemini_client
    if _gemini_client is None and config.GEMINI_API_KEY:
        from google import genai
        _gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _gemini_client

def _clean_text(text: str) -> str:
    cleaned = text
    for b in BANNED_WORDS:
        pattern = re.compile(re.escape(b), re.IGNORECASE)
        cleaned = pattern.sub("", cleaned)
    if cleaned.count("!") > 1:
        parts = cleaned.split("!")
        cleaned = parts[0] + "!" + "".join(parts[1:]).replace("!", ".")
    # Clean multiple spaces on each line while preserving line breaks
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in cleaned.splitlines()]
    return "\n".join(l for l in lines if l)

def format_lap_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m}:{s:06.3f}"

def extract_allowed_numbers(lap: int, total_laps: int, events: List[Dict]) -> Set[str]:
    # Collect all numbers appearing in the input facts
    numbers = {str(lap), str(total_laps)}
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

def validate_ai_text(text: str, allowed_numbers: Set[str]) -> bool:
    # 1. Check for numerical hallucinations
    found_numbers = re.findall(r"\b\d+(?:\.\d+)?\b", text)
    for num in found_numbers:
        # Check if the number is in allowed_numbers or a substring of an allowed formatted lap time
        if num not in allowed_numbers:
            matching = False
            for allowed in allowed_numbers:
                if num in allowed:
                    matching = True
                    break
            if not matching:
                logger.warning("AI hallucinated number '%s' not in facts: %s", num, allowed_numbers)
                return False

    # 2. Check for banned words
    for b in BANNED_WORDS:
        if re.search(r"\b" + re.escape(b) + r"\b", text, re.I):
            logger.warning("AI output contained banned phrase: %s", b)
            return False

    return True

async def generate_ai_commentary(lap: int, total_laps: int, events: List[Dict]) -> Optional[str]:
    if not config.AI_ENABLED or not config.GEMINI_API_KEY:
        return None

    client = get_gemini_client()
    if not client:
        return None

    allowed_numbers = extract_allowed_numbers(lap, total_laps, events)

    prompt = (
        f"You are a knowledgeable, casual friend watching an F1 race in a group chat with friends. "
        f"Rewrite these exact lap {lap}/{total_laps} race events into 1-2 lively, casual chat lines. "
        f"CRITICAL RULES:\n"
        f"1. Only state the facts provided. Never invent numbers, results, or driver names.\n"
        f"2. Any numbers you use must come directly from the provided events.\n"
        f"3. Friendly group chat tone. Max 1 emoji. Max 1 exclamation mark.\n"
        f"4. Do NOT use buzzwords like thrilling, exciting, game-changer, buckle up, electrifying.\n"
        f"5. Return ONLY a strict JSON object: {{\"text\": \"your commentary here\"}}\n\n"
        f"Lap: {lap}/{total_laps}\n"
        f"Events: {json.dumps(events)}"
    )

    try:
        from google.genai import types
        cfg = types.GenerateContentConfig(response_mime_type="application/json")
        # 5 second strict timeout
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=prompt,
                config=cfg
            ),
            timeout=5.0
        )
        if not response or not response.text:
            return None

        data = json.loads(response.text)
        text = data.get("text", "").strip()
        if not text:
            return None

        # Safety net validation
        if not validate_ai_text(text, allowed_numbers):
            return None

        return _clean_text(text)

    except asyncio.TimeoutError:
        logger.warning("Gemini commentary timed out (5s) on lap %d. Falling back to template.", lap)
        return None
    except Exception as e:
        logger.warning("Gemini error on lap %d: %s. Falling back to template.", lap, e)
        return None

def format_event_template(event: Dict) -> str:
    etype = event.get("type", "")
    if etype == "start":
        leader = event.get("leader", "Leader")
        gainer = event.get("biggest_gainer", "Driver")
        gained = event.get("places_gained", 0)
        return f"{leader} holds the lead into turn 1. {gainer} gained {gained} places off the start."
    if etype == "pit":
        d = event.get("driver", "Driver")
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
        d = event.get("driver", "Driver")
        desc = event.get("description", "time penalty")
        if not desc.startswith(d):
            return f"{d} gets a {desc}."
        return f"{desc}."
    if etype == "fastest_lap":
        d = event.get("driver", "Driver")
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
        # Group overtakes per driver
        overtakes_by_driver: Dict[str, Dict] = {}
        pit_events = []
        other_events = []

        for ev in events:
            etype = ev.get("type")
            if etype == "overtake":
                d = ev.get("driver")
                if d not in overtakes_by_driver:
                    overtakes_by_driver[d] = {
                        "driver": d,
                        "passed": [],
                        "new_position": ev.get("new_position")
                    }
                overtakes_by_driver[d]["passed"].append(ev.get("passed", "car"))
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
            drivers = [p["driver"] for p in pit_events]
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
    podium = " | ".join(f"P{i+1}: {code}" for i, code in enumerate(top3))
    lb = format_leaderboard(leaderboard)
    return _clean_text(f"Race complete!\nPodium: {podium}\n\n{lb}")
