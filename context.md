# Context: Pit Wall Party

## Goal & Fan Problem
F1 races in the Americas air late at night in India. Friends watch alone and half-asleep in fragmented chats, missing drama and group excitement. Pit Wall Party is an F1 watch-party Telegram bot that fast-replays a real race (~8s/lap, ~10m total), posts key moments with context, and hosts free, live prediction rounds with instant settlement and leaderboard banter. Free-to-play engagement only; no wagering or betting language.

## Architecture
- Code handles facts, AI handles language.
- Offline data prep (`prepare_race.py`): queries OpenF1 API once to compile `race_data.json` (race info, drivers, lap positions, structured events). Bot never calls OpenF1 at runtime.
- Replay Engine (`replay.py`): sport-agnostic lap-by-lap async runner; batches max 1 message/lap; lead changes prioritized first; strict post-event round settlement.
- Prediction Rounds (`rounds.py`): triggers 5 rounds at preset laps, closes betting before outcome window, auto-settles against `race_data.json` with tie-scoring support.
- AI Writer (`writer.py`): rewrites code facts into casual fan chat using Gemini via `google-genai` SDK with strict JSON response and numerical hallucination validator. Banned phrases trigger fallback to template (no sentence mutation). Fully functional with `AI_ENABLED=false`.
- Database (`db.py`): SQLite for group/user predictions, points, and leaderboard (parameterised SQL).
- Telegram Bot (`bot.py`): `python-telegram-bot` supporting local polling and production webhook on Render with secret token validation.
- Simulator (`simulate.py`): terminal replay with simulated users to test engine, writer, rounds, and db without Telegram. Tracks and reports AI vs fallback statistics.

## File Map
- `context.md`, `rules.md`: project memory and operational guidelines
- `prepare_race.py`: fetch and parse OpenF1 race into structured `race_data.json`
- `race_data.json`: precomputed race facts, laps, drivers, and events (69 laps, 2024 São Paulo GP)
- `config.py`: typed configuration and strict env validation
- `replay.py`: lap timer and event scheduler per chat
- `rounds.py`: prediction rounds lifecycle (open, vote, close, settle)
- `writer.py`: Gemini client + template fallback + numerical verification + AI stats tracker
- `db.py`: SQLite storage for scores and predictions (parameterised SQL)
- `bot.py`: Telegram command and callback query handlers (webhook/polling)
- `simulate.py`: headless CLI test harness with virtual voters
- `requirements.txt`: pinned dependencies
- `render.yaml`, `.env.example`, `.gitignore`, `README.md`

## Decisions Made
- Selected Race: 2024 São Paulo Grand Prix (intermittent wet, 69 laps due to aborted start, red flag, P17 to P1 win).
- Code vs AI boundary: strict schema. Events detected deterministically offline; AI only rewrites facts into chat messages.
- Prediction fairness: voting closes before evaluation window begins. Green-flag window enforced for SC questions. Red-flag pit entries excluded. Questions renamed to explicit "Safety car or VSC".
- Fallback integrity: banned phrases trigger full template fallback to avoid fragmented text.
- Fallback telemetry: fallback reasons (timeout, bad JSON, number check, banned phrase, API error) logged and counted.

## Current Status
- All Phases complete and verified:
  - Code-enforced "why it matters" line for SC, VSC, red flag, penalty, lead change (never overtakes or pits).
  - VSC why-line: "Pitting under a VSC costs less time because everyone else is driving slower."
  - Grid position passed in facts ONLY for lead changes, nowhere else.
  - Pit durations >= 10s stripped from AI facts and allowed number list.
  - Race title year duplication fixed.
  - Round results use strict template for facts/winners, with AI providing one friendly banter line.
  - Full 69-lap simulation and partial slices verified end-to-end.
  - Telegram bot dual mode (polling/webhook) ready.
  - Render blueprint configuration ready.

## What's Next
- Live testing in Telegram group and Render deployment.

## Known Issues
- None.
