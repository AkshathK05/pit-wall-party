# Pit Wall Party

An F1 watch-party Telegram bot that fast-replays a real race (~8s per lap, ~10m total), posts key race moments with context, and runs live prediction rounds with instant settlement and group leaderboards.

## What it is
Late-night F1 races often leave fans watching alone in silent or disconnected chats. Pit Wall Party turns any Telegram group into an interactive pit wall. It streams race drama lap-by-lap from precomputed official telemetry, runs fair tap-to-vote prediction rounds, and maintains a group score tally. It is completely free-to-play with no betting, wagering, or real-money concepts.

## Run locally

1. Clone repo and create a virtual environment:
```bash
git clone <repo-url>
cd pitwall-party
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

2. Generate or verify race data (offline data prep, run once):
```bash
python prepare_race.py
```

3. Run the headless simulator (no Telegram or API keys needed):
```bash
python simulate.py --fast --no-ai
```

4. Run the Telegram bot locally:
- Copy `.env.example` to `.env` and fill in `TELEGRAM_BOT_TOKEN`.
- Leave `WEBHOOK_URL` empty to run in local polling mode.
- If using Gemini commentary, set `GEMINI_API_KEY` and `GEMINI_MODEL=gemini-2.5-flash`.
```bash
python bot.py
```

Telegram group commands:
- `/start` - Introduction and command list
- `/race replay` - Start race replay in this group
- `/race stop` - Stop the active replay
- `/leaderboard` - View group scores
- `/help` - Command reference

## Deploy

Deployed as a free web service on Render:

1. Push this repository to GitHub.
2. In Render Dashboard, click **New +** -> **Blueprint** and connect your repository (Render reads `render.yaml`).
3. Set the environment variables in Render:
   - `TELEGRAM_BOT_TOKEN`: Token from @BotFather
   - `WEBHOOK_URL`: Your Render service URL (e.g. `https://pit-wall-party.onrender.com`)
   - `WEBHOOK_SECRET`: A secure random string for request validation
   - `GEMINI_API_KEY`: Google Gemini API key
   - `GEMINI_MODEL`: `gemini-2.5-flash`
   - `AI_ENABLED`: `true` (or `false` to run purely on deterministic templates)
   - `SECONDS_PER_LAP`: `8` (default for live demo)
4. Deploy the service. When deployed, the bot automatically registers its webhook with Telegram using your `WEBHOOK_SECRET`.

## How it works (short)

1. **Facts vs AI**: All race events, overtakes, lap positions, and prediction outcomes are deterministically computed offline by `prepare_race.py` from OpenF1 API data into `race_data.json`.
2. **Replay Engine**: `replay.py` iterates through laps asynchronously, batching events into at most one message per lap. Empty laps are skipped. Lead changes are prioritized and posted first.
3. **Prediction Rounds**: `rounds.py` triggers 5 prediction rounds at preset laps. Voting closes strictly before the deciding outcome window opens. Rounds settle only after the deciding lap event message has been delivered to the group.
4. **AI Commentary & Safety Net**: `writer.py` rewrites lap facts using Gemini (`google-genai`). If the API call times out (>5s), errors, returns invalid JSON, or introduces any number not present in the input facts, it immediately falls back to deterministic code templates.
5. **Scoreboard**: `db.py` uses SQLite with parameterised queries to track user picks and tally 10 points per correct answer.
