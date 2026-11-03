# rules.md: Pit Wall Party

## 1. Security (non-negotiable)
- NO secrets in code, ever: no tokens, API keys, webhook URLs, secrets, chat IDs, or user IDs in any .py, .json, .yaml, or .md file. Everything comes from environment variables via config.py.
- .env is in .gitignore. Only .env.example is committed, with placeholders like "your-token-here".
- config.py validates all required env vars at startup and exits with a clear message if one is missing. No silent defaults for secrets.
- Never log or print secrets, full API responses containing keys, or full user messages. Log event types and error messages only.
- Webhook uses a secret token; reject requests without it.
- Treat all Telegram input as untrusted: validate commands, args, and callback data before acting.
- Use parameterised SQL queries only. Never build SQL with string formatting.
- Pin dependency versions in requirements.txt.
- Before every phase report, run: grep -rniE "(token|key|secret|api_key|bot[0-9]+:)\s*=\s*['\"][^'\"]{8,}" --include=*.py --include=*.yaml --include=*.json . and confirm zero hits. Also confirm .env is not tracked by git.

## 2. Code size and style
- Write the shortest clear version. If it can be 50 lines, do not write 200.
- No speculative features, no abstractions "for later", no classes where a function works, no config systems beyond env vars.
- Comments only where the WHY isn't obvious. No comments restating what the code does. No docstrings on trivial functions.
- No ASCII-art banners, no decorative log lines, no emoji in code or logs.
- Prefer the standard library. Add a dependency only if it saves real work.

## 3. Facts vs AI
- Every number, name, lap, position and result shown to users comes from race_data.json via code.
- Gemini only rewrites given facts. Any AI text containing a number not in the input facts is discarded and replaced by the template.
- The bot must work fully with AI_ENABLED=false.

## 4. No "AI-made" look or voice
- Bot messages sound like a friend in a group chat, not a marketing bot. Banned words/phrases: "Exciting", "Buckle up", "Get ready", "Let's dive in", "Unleash", "Elevate", "Seamless", "Game-changer", "Thrilling", "Electrifying", "What a moment!", "Stay tuned".
- At most one emoji per message. No emoji chains. No rocket, fire, or sparkle spam.
- No exclamation mark on every line. Max one per message.
- README: plain and direct. No emoji headers, no badge walls, no "✨ Features ✨", no marketing intro. Sections: What it is, Run locally, Deploy, How it works (short).
- If any HTML is ever served (e.g. a health check), it is plain text "ok". No styling, no gradients, no purple, no glassmorphism, no generic landing-page look.
- No "Certainly!", "Great question", or apologetic filler in any output.

## 5. Reliability
- The replay must never crash mid-race. Wrap per-lap work and every handler in try/except, log the error, continue.
- Respect Telegram limits: max ~1 message per 3 s per group; batch per lap.
- Max one Gemini call per lap; 5 s timeout.

## 6. Generalisation
- Only prepare_race.py and the question templates know about F1. replay.py, rounds.py settling logic, writer.py, db.py and bot.py must not hardcode F1 concepts beyond reading event "type" fields.

## 7. Process
- Re-read this file and context.md at the start of every phase and after every 3 files created/edited.
- Update context.md at the end of every phase.
- Never fabricate API field names, library methods, or model names. If unsure, check docs or test the call, and say so.

## Self-check (run against every file you just wrote)
[ ] No hardcoded secrets/IDs/URLs (grep passes)
[ ] Could this be shorter without losing clarity? If yes, shorten it.
[ ] Every user-facing fact comes from data, not AI
[ ] No banned words, ≤1 emoji, ≤1 "!" per message
[ ] Errors are caught and logged without leaking secrets
[ ] No F1-specific logic outside prepare_race.py / question templates
