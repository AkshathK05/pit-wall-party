# Context: Pit Wall Party

## Goal & Fan Problem
F1 races in the Americas air late at night in India. Friends watch alone and half-asleep in fragmented chats, missing drama and group excitement. Pit Wall Party is an F1 watch-party Telegram bot that fast-replays a real race (~8s/lap, ~10m total), posts key moments with context, and hosts free, live prediction rounds with instant settlement and leaderboard banter. Free-to-play engagement only; no wagering or betting language.

## Architecture
- Code handles facts, AI handles language.
- Offline data prep (`prepare_race.py`): queries OpenF1 API once to compile `race_data.json` (race info, drivers, lap positions, structured events). Bot never calls OpenF1 at runtime.
- Replay Engine (`replay.py`): sport-agnostic lap-by-lap async runner; batches max 1 message/lap; lead changes prioritized first; strict post-event round settlement.
- Prediction Rounds (`rounds.py`): triggers 5 rounds at preset laps, closes betting before outcome window, auto-settles against `race_data.json` with tie-scoring support.
- AI Writer (`writer.py`): rewrites code facts into casual fan chat using Gemini via `google-genai` SDK with strict JSON response and numerical hallucination validator. Deterministic template fallback on error, timeout (5s), or bad facts. Fully functional with `AI_ENABLED=false`.
- Database (`db.py`): SQLite for group/user predictions, points, and leaderboard (parameterised SQL).
- Telegram Bot (`bot.py`): `python-telegram-bot` supporting local polling and production webhook on Render with secret token validation.
- Simulator (`simulate.py`): terminal replay with simulated users to test engine, writer, rounds, and db without Telegram.

## File Map
- `context.md`, `rules.md`: project memory and operational guidelines
- `prepare_race.py`: fetch and parse OpenF1 race into structured `race_data.json`
- `race_data.json`: precomputed race facts, laps, drivers, and events (69 laps, 2024 São Paulo GP)
- `config.py`: typed configuration and strict env validation
- `replay.py`: lap timer and event scheduler per chat
- `rounds.py`: prediction rounds lifecycle (open, vote, close, settle)
- `writer.py`: Gemini client + template fallback + numerical verification
- `db.py`: SQLite storage for scores and predictions (parameterised SQL)
- `bot.py`: Telegram command and callback query handlers (webhook/polling)
- `simulate.py`: headless CLI test harness with virtual voters
- `requirements.txt`: pinned dependencies
- `render.yaml`, `.env.example`, `.gitignore`, `README.md`

## Decisions Made
- Selected Race: 2024 São Paulo Grand Prix (intermittent wet, 69 laps due to aborted start, red flag, P17 to P1 win).
- Code vs AI boundary: strict schema. Events detected deterministically offline; AI only rewrites facts into chat messages.
- Prediction fairness: voting closes before evaluation window begins. Green-flag window enforced for SC questions. Red-flag pit entries excluded.
- Event pacing: lead changes sent first; overtakes grouped per driver; heavy pit activity (>3 stops) summarized in one line.
- Fastest laps: filtered to final third only (laps >= 46) and capped at 4 key milestones. Formatted as m:ss.sss.
- Chequered flag parsing: strict match prevents substring collision with red flag.

## Current Status
- All Phases (1 through 6) complete:
  - `prepare_race.py` and `race_data.json` clean and verified.
  - Replay engine, rounds, and db fully functional without lookahead.
  - Gemini commentary integrated in `writer.py` with 5s timeout, JSON schema, and strict numerical anti-hallucination filter.
  - `bot.py` implements `/start`, `/help`, `/race replay`, `/race stop`, `/leaderboard`, server-validated callback buttons, and webhook/polling dual mode.
  - `render.yaml` and `README.md` configured for Render deployment.

## What's Next
- Live testing in Telegram group and Render deployment.

## Known Issues
- None.
