import json
import logging
from pathlib import Path
from typing import Dict, Tuple, List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

import config
import db
import writer
from replay import ReplaySession, active_replays

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pitwall.bot")

# Track round messages to remove buttons when voting closes: (chat_id, round_id) -> message_id
round_message_ids: Dict[Tuple[str, str], int] = {}
cached_race_data: Optional[Dict] = None

def get_race_data() -> Dict:
    global cached_race_data
    if cached_race_data is None:
        p = Path(__file__).resolve().parent / "race_data.json"
        if not p.exists():
            raise FileNotFoundError("race_data.json not found. Run prepare_race.py first.")
        with open(p, "r", encoding="utf-8") as f:
            cached_race_data = json.load(f)
    return cached_race_data

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Welcome to Pit Wall Party!\n\n"
        "Watch classic F1 races at high speed with friends and make live predictions.\n\n"
        "Commands:\n"
        "/race replay - Start race replay in this group\n"
        "/race stop - Stop current replay\n"
        "/leaderboard - View group scores\n"
        "/help - List commands"
    )
    await update.effective_message.reply_text(text)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Pit Wall Party commands:\n"
        "/race replay - Start the race replay\n"
        "/race stop - Stop running replay\n"
        "/leaderboard - Current group scores\n"
        "/help - Show this help"
    )
    await update.effective_message.reply_text(text)

async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    lb = db.get_leaderboard(chat_id)
    await update.effective_message.reply_text(writer.format_leaderboard(lb))

async def cmd_race(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    args = context.args or []
    if not args or args[0].lower() not in ("replay", "stop"):
        await update.effective_message.reply_text("Usage: /race replay or /race stop")
        return

    subcmd = args[0].lower()
    if subcmd == "stop":
        session = active_replays.get(chat_id)
        if session and session.running:
            session.stop()
            keys_to_clear = [k for k in list(round_message_ids.keys()) if k[0] == chat_id]
            for k in keys_to_clear:
                mid = round_message_ids.pop(k, None)
                if mid:
                    try:
                        await context.bot.edit_message_reply_markup(
                            chat_id=int(chat_id),
                            message_id=mid,
                            reply_markup=None
                        )
                    except Exception as e:
                        logger.debug("Could not clear buttons on stop for message %s: %s", mid, e)
            await update.effective_message.reply_text("Replay stopped.")
        else:
            await update.effective_message.reply_text("No replay currently running in this group.")
        return

    if subcmd == "replay":
        existing = active_replays.get(chat_id)
        if existing and existing.running:
            await update.effective_message.reply_text(
                "A replay is already running in this group. Use /race stop to end it."
            )
            return

        try:
            race_data = get_race_data()
        except Exception as e:
            logger.error("Failed to load race_data: %s", e)
            await update.effective_message.reply_text("Error: Race data not available.")
            return

        db.reset_chat(chat_id)

        async def send_msg(cid: str, text: str, buttons: Optional[List[str]] = None, round_id: Optional[str] = None):
            session = active_replays.get(cid)
            if not session or not session.running:
                return
            reply_markup = None
            if buttons and round_id:
                keyboard = [
                    [InlineKeyboardButton(opt, callback_data=f"{round_id}:{opt}") for opt in buttons]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

            sent = await context.bot.send_message(
                chat_id=int(cid),
                text=text,
                reply_markup=reply_markup
            )
            if round_id:
                round_message_ids[(cid, round_id)] = sent.message_id

        async def close_round(cid: str, round_id: str):
            mid = round_message_ids.pop((cid, round_id), None)
            if mid:
                try:
                    await context.bot.edit_message_reply_markup(
                        chat_id=int(cid),
                        message_id=mid,
                        reply_markup=None
                    )
                except Exception as e:
                    logger.debug("Could not clear buttons for message %s: %s", mid, e)

        session = ReplaySession(
            chat_id=chat_id,
            race_data=race_data,
            seconds_per_lap=config.SECONDS_PER_LAP,
            send_message_cb=send_msg,
            close_round_cb=close_round,
            use_ai=config.AI_ENABLED
        )
        await session.start()

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    chat_id = str(update.effective_chat.id)
    user = query.from_user
    user_id = str(user.id)
    user_name = user.first_name or user.username or f"User{user_id[:4]}"

    # Server-side validation
    if ":" not in data:
        await query.answer("Invalid vote.")
        return

    round_id, choice = data.split(":", 1)
    session = active_replays.get(chat_id)
    if not session or not session.running:
        await query.answer("This race replay is no longer active.")
        return

    matching_round = next((r for r in session.rounds if r.id == round_id), None)
    if not matching_round or matching_round.status != "open":
        await query.answer("Voting for this round is closed.")
        return

    if choice not in matching_round.options:
        await query.answer("Invalid selection.")
        return

    db.record_vote(chat_id, user_id, user_name, round_id, choice)
    await query.answer(f"Voted: {choice}!")

def main():
    use_webhook = bool(config.WEBHOOK_URL)
    config.validate_bot_config(webhook=use_webhook)
    db.init_db()

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("race", cmd_race))
    app.add_handler(CallbackQueryHandler(handle_callback))

    if use_webhook:
        logger.info("Starting Telegram bot in webhook mode on port %d...", config.PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=config.PORT,
            url_path="webhook",
            webhook_url=f"{config.WEBHOOK_URL}/webhook",
            secret_token=config.WEBHOOK_SECRET
        )
    else:
        logger.info("Starting Telegram bot in local polling mode...")
        app.run_polling()

if __name__ == "__main__":
    main()
