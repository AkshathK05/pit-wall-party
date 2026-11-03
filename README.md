# Pit Wall Party

F1 races in the Americas air after midnight in India. Fans who stay up watch alone, group chats move too fast, and the quiet middle stretches are when people drift off and miss what matters. Pit Wall Party turns a Telegram group into an interactive watch party by fast-replaying a real past Grand Prix (~8 seconds per lap, ~10 minutes total), posting key track moments with context, and hosting live prediction rounds settled automatically from real race data.

## Try it

Bot link: https://t.me/pitwallparty_bot

1. Add the bot to your Telegram group.
2. Send `/race replay` to begin the race replay.
3. Tap prediction buttons when rounds open (voting stays open for 4 laps).
4. Send `/leaderboard` at any point to view group scores.
5. Send `/race stop` to halt the replay and clear active round buttons.

Note: on free cloud hosting (Render), the bot may take about a minute to respond to the first command if waking from an idle state.

## How it works

Code handles facts, AI handles language. All overtakes, lap positions, pit stops, penalties, and round results are computed deterministically from race data via Python code. Gemini only rewrites structured facts into casual group chat commentary without inventing numbers, drivers, or outcomes.

Flow:
OpenF1 API → `prepare_race.py` → `race_data.json` → replay engine (`replay.py`) → rounds and settling (`rounds.py`) → writer (`writer.py` with Gemini and template fallback) → Telegram (`bot.py`).

Safety net:
- Number verification: any generated text containing numbers or number words not present in the input facts is rejected and replaced by the template.
- Banned phrases: responses containing marketing filler, exaggerated claims, or contradictory statements fall back to templates.
- Timeouts and API errors: a 5-second timeout or API failure falls back immediately to code templates without interrupting the race replay.

AI commentary is used only for notable moments (lead changes, safety cars, red flags, penalties, laps with 3+ events) and round banter to stay focused and respect rate limits.

## Design decisions

- Replay over live: pre-processed replays can be demoed on demand at any time without waiting for a race weekend; live OpenF1 telemetry requires a paid subscription.
- Telegram over WhatsApp: Telegram provides free bot tokens, native inline keyboards, and zero approval delays; WhatsApp Business API requires Meta business verification.
- Deterministic round results: round winners and point awards always use deterministic code templates; AI only adds an optional friendly banter line after the result.
- Fair prediction windows: questions close voting before the evaluation window begins, ensuring no user can vote after an event has started.
- Red-flag pit exclusion: pit lane entries during red-flag stoppages are excluded during data preparation so universal pit stops do not skew prediction rounds.

## Swapping in another sport

- Sport-specific files: `prepare_race.py` (data fetching and event parsing) and question templates in `rounds.py`.
- Sport-agnostic files: `replay.py` (lap runner and scheduler), `rounds.py` (lifecycle engine), `writer.py` (safety net and commentary), `db.py` (SQLite persistence), and `bot.py` (Telegram bot interface).
To adapt to another sport (such as cricket or football), replace `prepare_race.py` with a sport-specific event ingest script and define questions in `rounds.py`.

## Run locally

Requirements: Python 3.11+.

```bash
git clone https://github.com/AkshathK05/pit-wall-party.git
cd pit-wall-party
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Environment variables in `.env`:
- `TELEGRAM_BOT_TOKEN`: bot token from @BotFather.
- `GEMINI_API_KEY`: API key from Google AI Studio.
- `GEMINI_MODEL`: Gemini model identifier (e.g. `gemini-3.5-flash-lite`).
- `AI_ENABLED`: `true` to enable Gemini commentary, `false` for templates only.
- `SECONDS_PER_LAP`: replay speed in seconds per lap (default `8`).
- `WEBHOOK_URL`: leave empty for local long-polling.
- `WEBHOOK_SECRET`: secret token for webhook header validation.
- `PORT`: HTTP port for webhook listener (default `8080`).

Run headless simulator (tests race engine, voting, and database without Telegram):
```bash
python simulate.py --fast --no-ai
```

Run Telegram bot locally (uses long polling when `WEBHOOK_URL` is empty):
```bash
python bot.py
```

## Deploy (Render)

1. Push this repository to GitHub.
2. In Render, create a new Web Service and connect the repository (or deploy using `render.yaml`).
3. Set the build command to `pip install -r requirements.txt` and the start command to `python bot.py`.
4. Configure environment variables in the Render dashboard: `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `WEBHOOK_URL` (your Render service URL, e.g. `https://your-service.onrender.com`), and `WEBHOOK_SECRET`.
5. Deploy the service. On startup, the bot registers its webhook endpoint with Telegram.

Note: Render free tier spins down after inactivity and uses an ephemeral filesystem, which resets SQLite scores on restart. This is acceptable for per-race group games.

## Project structure

```text
pit-wall-party/
├── prepare_race.py     # Offline fetch and event detection from OpenF1 API
├── race_data.json      # Precomputed race facts for the 2024 São Paulo GP
├── replay.py           # Lap timer and event scheduler per chat
├── rounds.py           # Prediction round lifecycle and settlement logic
├── writer.py           # Gemini commentary writer with template fallback
├── db.py               # SQLite storage for user predictions and scores
├── bot.py              # Telegram command and callback handlers (polling/webhook)
├── simulate.py         # Headless CLI test harness with virtual voters
├── config.py           # Environment variable loading and validation
├── render.yaml         # Render deployment blueprint
├── requirements.txt    # Pinned Python dependencies
├── context.md          # Project context and memory
└── rules.md            # Project rules and verification checklists
```

## Limitations

- Single pre-processed race: race data is offline-cached for the 2024 São Paulo GP (69 laps); adding new races requires running `prepare_race.py`.
- Ephemeral storage on free tier: SQLite database resets on free-tier server restarts.
- Cold start delay: free hosting on Render sleeps when idle, taking about a minute to respond to the initial command.
- Gemini quota fallback: if API rate limits or network timeouts occur, commentary automatically falls back to deterministic code templates.
