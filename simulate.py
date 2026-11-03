import sys
import os
import json
import random
import asyncio
import argparse
from pathlib import Path

# Ensure UTF-8 output on Windows terminal
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import db
import writer
from replay import ReplaySession

FAKE_USERS = [
    ("u1", "Arjun"),
    ("u2", "Rohan"),
    ("u3", "Priya")
]

async def main():
    parser = argparse.ArgumentParser(description="Pit Wall Party Simulator")
    parser.add_argument("--fast", action="store_true", help="Fast replay speed")
    parser.add_argument("--no-ai", action="store_true", help="Disable AI commentary")
    parser.add_argument("--from-lap", type=int, default=1, help="Start lap")
    parser.add_argument("--to-lap", type=int, default=None, help="End lap")
    parser.add_argument("--seconds-per-lap", type=float, default=None, help="Seconds per lap")
    args = parser.parse_args()

    race_file = Path(__file__).resolve().parent / "race_data.json"
    if not race_file.exists():
        sys.exit("Error: race_data.json not found. Run prepare_race.py first.")

    with open(race_file, "r", encoding="utf-8") as f:
        race_data = json.load(f)

    chat_id = "simulator_group"
    db.init_db("pitwall.db")
    db.reset_chat(chat_id)
    writer.reset_ai_stats()

    if args.seconds_per_lap is not None:
        seconds_per_lap = args.seconds_per_lap
    elif "SECONDS_PER_LAP" in os.environ:
        try:
            seconds_per_lap = float(os.environ["SECONDS_PER_LAP"])
        except ValueError:
            seconds_per_lap = 8.0
    else:
        seconds_per_lap = 0.05 if args.fast else 1.0

    to_lap = args.to_lap or race_data["race_info"]["total_laps"]

    print("=" * 60)
    print("PIT WALL PARTY LOCAL SIMULATOR")
    print(f"Laps: {args.from_lap} to {to_lap} | Speed: {seconds_per_lap}s/lap | AI: {'OFF' if args.no_ai else 'ON'}")
    print("=" * 60)

    async def handle_message(cid: str, text: str, buttons=None, round_id=None):
        print("\n" + "-" * 40)
        print(text)
        if buttons and round_id:
            print(f"[Buttons: {' | '.join(buttons)}]")
            for uid, name in FAKE_USERS:
                pick = random.choice(buttons)
                db.record_vote(cid, uid, name, round_id, pick)
                print(f"  -> {name} voted: {pick}")

    session = ReplaySession(
        chat_id=chat_id,
        race_data=race_data,
        seconds_per_lap=seconds_per_lap,
        send_message_cb=handle_message,
        use_ai=(not args.no_ai),
        from_lap=args.from_lap,
        to_lap=to_lap
    )

    await session.start()
    if session.task:
        await session.task

    stats = writer.get_ai_stats()
    print("\n" + "=" * 60)
    print(f"AI messages: {stats['ai_count']}, fallback: {stats['fallback_count']}")
    if stats["reasons"]:
        print("Fallback reasons:")
        for reason, count in stats["reasons"].items():
            print(f"  - {reason}: {count}")
    print("SIMULATION COMPLETED SUCCESSFULLY")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
