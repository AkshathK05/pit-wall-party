import json
import time
import datetime
from collections import Counter
import requests

BASE_URL = "https://api.openf1.org/v1"

def fetch_openf1(endpoint: str, params: dict) -> list:
    url = f"{BASE_URL}/{endpoint}"
    for attempt in range(5):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                time.sleep(0.5)
                return resp.json()
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 2 * (attempt + 1)))
                print(f"Rate limited (429) on {endpoint}. Waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
        except requests.RequestException as e:
            if attempt == 4:
                raise
            time.sleep(1 + attempt)
    return []

def main():
    print("Fetching 2024 Sao Paulo GP data from OpenF1...")
    # Session 9636 is 2024 Sao Paulo GP Race
    session_key = 9636

    # 1. Fetch drivers
    raw_drivers = fetch_openf1("drivers", {"session_key": session_key})
    drivers = {}
    driver_num_to_code = {}
    for d in raw_drivers:
        num = d["driver_number"]
        code = d.get("name_acronym") or str(num)
        driver_num_to_code[num] = code
        drivers[code] = {
            "number": num,
            "code": code,
            "name": d.get("full_name") or code,
            "team": d.get("team_name") or "Unknown"
        }

    # 2. Fetch laps
    raw_laps = fetch_openf1("laps", {"session_key": session_key})
    driver_laps = {}
    for l in raw_laps:
        num = l["driver_number"]
        if l.get("date_start") and l.get("lap_duration"):
            t_start = datetime.datetime.fromisoformat(l["date_start"])
            t_end = t_start + datetime.timedelta(seconds=l["lap_duration"])
            driver_laps.setdefault(num, {})[l["lap_number"]] = (t_end, l["lap_duration"], l.get("is_pit_out_lap", False))

    total_laps = max((l["lap_number"] for l in raw_laps if l.get("lap_number")), default=69)

    # 3. Fetch positions
    raw_pos = fetch_openf1("position", {"session_key": session_key})
    driver_pos_history = {}
    for p in raw_pos:
        num = p["driver_number"]
        t = datetime.datetime.fromisoformat(p["date"])
        driver_pos_history.setdefault(num, []).append((t, p["position"]))
    for num in driver_pos_history:
        driver_pos_history[num].sort(key=lambda x: x[0])

    # 4. Fetch race control first to find red flags
    raw_rc = fetch_openf1("race_control", {"session_key": session_key})
    red_flag_laps = {
        r.get("lap_number") for r in raw_rc
        if r.get("flag") == "RED" or ("RED FLAG" in (r.get("message") or "") and "CHEQUERED" not in (r.get("message") or ""))
    }

    # 5. Fetch pit stops (exclude any during red-flag periods)
    raw_pits = fetch_openf1("pit", {"session_key": session_key})
    pits_by_driver_lap = {}
    pits_by_lap = {}
    for p in raw_pits:
        num = p["driver_number"]
        lap = p["lap_number"]
        if lap in red_flag_laps:
            continue
        code = driver_num_to_code.get(num, str(num))
        dur = p.get("stop_duration") or p.get("pit_duration")
        if dur:
            dur = round(float(dur), 1)
            # Drop extended pit / garage stays over 60s
            if dur > 60:
                continue
        pits_by_driver_lap[(code, lap)] = dur
        pits_by_lap.setdefault(lap, []).append({
            "type": "pit",
            "lap": lap,
            "driver": code,
            "duration": dur
        })

    # Process race control events
    rc_by_lap = {}
    seen_rc = set()
    for r in raw_rc:
        lap = r.get("lap_number") or 1
        msg = (r.get("message") or "").strip()
        cat = r.get("category") or ""
        flag = r.get("flag") or ""

        event = None
        key = (lap, msg)
        if key in seen_rc:
            continue

        if cat == "SafetyCar" or "SAFETY CAR" in msg:
            if "VIRTUAL SAFETY CAR DEPLOYED" in msg or "VSC DEPLOYED" in msg:
                event = {"type": "vsc_deployed", "lap": lap}
            elif "VIRTUAL SAFETY CAR ENDING" in msg or "VSC ENDING" in msg:
                event = {"type": "vsc_ending", "lap": lap}
            elif "SAFETY CAR DEPLOYED" in msg:
                event = {"type": "safety_car_deployed", "lap": lap}
            elif "SAFETY CAR IN THIS LAP" in msg or "SAFETY CAR ENDING" in msg:
                event = {"type": "safety_car_ending", "lap": lap}
        elif flag == "RED" or ("RED FLAG" in msg and "CHEQUERED" not in msg):
            event = {"type": "red_flag", "lap": lap}
        elif "PENALTY" in msg:
            d_code = None
            if r.get("driver_number"):
                d_code = driver_num_to_code.get(r["driver_number"])
            import re
            if not d_code:
                m = re.search(r"CAR\s+(\d+)", msg)
                if m:
                    d_code = driver_num_to_code.get(int(m.group(1)))
            clean_desc = msg
            m_pen = re.search(r"(\d+)\s*SECOND\s*(?:TIME\s*)?PENALTY.*?-\s*(.*)", msg, re.I)
            if m_pen:
                secs, reason = m_pen.group(1), m_pen.group(2).strip().lower()
                clean_desc = f"{secs}s penalty for {reason}"
            event = {"type": "penalty", "lap": lap, "driver": d_code or "CAR", "description": clean_desc}

        if event:
            seen_rc.add(key)
            rc_by_lap.setdefault(lap, []).append(event)

    # 6. Fastest lap progression (final third of race only, capped at ~4 messages)
    valid_laps = [
        l for l in raw_laps
        if l.get("lap_duration") and not l.get("is_pit_out_lap") and l.get("date_start")
    ]
    valid_laps.sort(key=lambda x: (x["lap_number"], x["date_start"]))
    fastest_time = float("inf")
    fastest_laps_by_lap = {}
    last_fl_lap = 0
    final_third_threshold = (total_laps * 2) // 3

    for l in valid_laps:
        dur = l["lap_duration"]
        if dur < fastest_time:
            fastest_time = dur
            code = driver_num_to_code.get(l["driver_number"], str(l["driver_number"]))
            lap = l["lap_number"]
            if lap >= final_third_threshold:
                if last_fl_lap == 0 or (lap - last_fl_lap >= 5) or (lap >= total_laps - 2):
                    fastest_laps_by_lap[lap] = {
                        "type": "fastest_lap",
                        "lap": lap,
                        "driver": code,
                        "time": round(dur, 3)
                    }
                    last_fl_lap = lap

    # 7. Positions and Overtakes per lap
    laps_data = {}
    event_counts = Counter()

    prev_positions = {} # code: pos

    for lap in range(1, total_laps + 1):
        lap_positions = {}
        for num, code in driver_num_to_code.items():
            lap_info = driver_laps.get(num, {}).get(lap)
            if lap_info:
                t_end = lap_info[0]
                records = [
                    p[1] for p in driver_pos_history.get(num, [])
                    if p[0] <= t_end + datetime.timedelta(seconds=2)
                ]
                if records:
                    lap_positions[code] = records[-1]

        # If a driver was running and didn't complete lap, carry last known position or leave out
        # Normalize positions so there are no duplicate positions
        sorted_pos = sorted(lap_positions.items(), key=lambda x: x[1])
        normalized_positions = {code: rank for rank, (code, _) in enumerate(sorted_pos, start=1)}

        lap_events = []

        # Lap 1 start summary
        if lap == 1:
            top3 = [code for code, p in sorted_pos[:3]]
            leader = top3[0] if top3 else "RUS"
            # find biggest gainer compared to starting grid (position records before race start)
            start_pos = {}
            for num, code in driver_num_to_code.items():
                if driver_pos_history.get(num):
                    start_pos[code] = driver_pos_history[num][0][1]
            gainers = []
            for code, p1 in normalized_positions.items():
                p0 = start_pos.get(code, p1)
                if p0 > p1:
                    gainers.append((p0 - p1, code))
            gainers.sort(reverse=True)
            biggest = gainers[0] if gainers else (0, leader)
            lap_events.append({
                "type": "start",
                "lap": 1,
                "leader": leader,
                "top3": top3,
                "biggest_gainer": biggest[1],
                "places_gained": biggest[0]
            })
            event_counts["start"] += 1
        else:
            # Detect overtakes
            for code, curr_pos in normalized_positions.items():
                prev_pos = prev_positions.get(code)
                if prev_pos is None or curr_pos >= prev_pos:
                    continue
                # Driver gained position(s)
                # Find whom they passed
                places_gained = prev_pos - curr_pos
                if not (curr_pos <= 10 or places_gained >= 2):
                    continue

                for passed_code, p_prev in prev_positions.items():
                    if passed_code == code:
                        continue
                    p_curr = normalized_positions.get(passed_code)
                    if p_curr is None:
                        continue
                    # Check if passed_code was ahead on lap-1 and is behind now
                    if prev_pos > p_prev and curr_pos < p_curr:
                        # Ignore if passed driver pitted on this lap or previous lap
                        if (passed_code, lap) in pits_by_driver_lap or (passed_code, lap - 1) in pits_by_driver_lap:
                            continue
                        lap_events.append({
                            "type": "overtake",
                            "lap": lap,
                            "driver": code,
                            "passed": passed_code,
                            "new_position": curr_pos
                        })
                        event_counts["overtake"] += 1

        # Add pit events
        if lap in pits_by_lap:
            for p in pits_by_lap[lap]:
                lap_events.append(p)
                event_counts["pit"] += 1

        # Add race control events
        if lap in rc_by_lap:
            for r in rc_by_lap[lap]:
                lap_events.append(r)
                event_counts[r["type"]] += 1

        # Add fastest lap event
        if lap in fastest_laps_by_lap:
            lap_events.append(fastest_laps_by_lap[lap])
            event_counts["fastest_lap"] += 1

        laps_data[str(lap)] = {
            "positions": normalized_positions,
            "events": lap_events
        }

        prev_positions = normalized_positions

    race_data = {
        "race_info": {
            "name": "2024 São Paulo Grand Prix",
            "year": 2024,
            "total_laps": total_laps,
            "session": "Race"
        },
        "drivers": drivers,
        "laps": laps_data
    }

    with open("race_data.json", "w", encoding="utf-8") as f:
        json.dump(race_data, f, indent=2)

    print("\nrace_data.json successfully generated!")
    print(f"Total laps: {total_laps}")
    print("\nEvent counts per type:")
    for etype, count in sorted(event_counts.items()):
        print(f"  {etype}: {count}")

    # Print final top 3
    final_positions = sorted(laps_data[str(total_laps)]["positions"].items(), key=lambda x: x[1])
    print("\nFinal Top 3:")
    for code, pos in final_positions[:3]:
        d = drivers.get(code, {})
        print(f"  P{pos}: {code} ({d.get('name', 'Unknown')}) - {d.get('team', 'Unknown')}")

if __name__ == "__main__":
    main()
