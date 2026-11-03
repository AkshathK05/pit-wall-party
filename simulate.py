import sys
import json
import random
import asyncio
import argparse
from pathlib import Path

import db
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
    args = parser.parse_args()

    race_file = Path(__file__).resolve().parent / "race_data.json"
    if not race_file.exists():
        sys.exit("Error: race_data.json not found. Run prepare_race.py first.")

    with open(race_file, "r", encoding="utf-8") as f:
        race_data = json.load(f)

    chat_id = "simulator_group"
    db.init_db("pitwall.db")
    db.reset_chat(chat_id)

    # Fast mode: 0.05s per lap so 69 laps finish in ~3.5s
    seconds_per_lap = 0.05 if args.fast else 1.0

    print("=" * 60)
    print("PIT WALL PARTY LOCAL SIMULATOR")
    print(f"Speed: {seconds_per_lap}s/lap | AI: {'OFF' if args.no_ai else 'ON'}")
    print("=" * 60)

    async def handle_message(cid: str, text: str, buttons=None, round_id=None):
        print("\n" + "-" * 40)
        print(text)
        if buttons and round_id:
            print(f"[Buttons: {' | '.join(buttons)}]")
            # Simulate fake users voting
            for uid, name in FAKE_USERS:
                pick = random.choice(buttons)
                db.record_vote(cid, uid, name, round_id, pick)
                print(f"  -> {name} voted: {pick}")

    session = ReplaySession(
        chat_id=chat_id,
        race_data=race_data,
        seconds_per_lap=seconds_per_lap,
        send_message_cb=handle_message,
        use_ai=(not args.no_ai)
    )

    await session.start()
    if session.task:
        await session.task

    print("\n" + "=" * 60)
    print("SIMULATION COMPLETED SUCCESSFULLY")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
