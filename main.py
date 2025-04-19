import os
import json
import math
import threading
from datetime import datetime, date
from flask import Flask, request
from telegram import Update
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    ConversationHandler,
)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone
from vocab_data import vocab_list

# ────── Configuration ──────
# In Render set these two environment variables:
#   BOT_TOKEN   = "7575015472:AAE6RZZcJDeAMHaCMr62crpKULf5YJkq5Pw"
#   WEBHOOK_URL = "https://<YOUR_RENDER_SUBDOMAIN>.onrender.com/<BOT_TOKEN>"
BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]

# ────── Conversation States ──────
ASK_COUNT, ASK_PERCENT, ASK_TIME = range(3)

# ────── Scheduler Setup ──────
tz = timezone("Asia/Tashkent")
scheduler = BackgroundScheduler(timezone=tz)
scheduler.start()

# ────── Persistence ──────
SETTINGS_FILE = "user_settings.json"
if os.path.exists(SETTINGS_FILE):
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        user_settings = json.load(f)
else:
    user_settings = {}

def save_settings():
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(user_settings, f)

# ────── Vocabulary Delivery ──────
def send_words(context: CallbackContext, chat_id: int):
    cid = str(chat_id)
    try:
        count = user_settings[cid]["count"]
        pos   = user_settings[cid].get("position", 0)
        next_pos = min(pos + count, len(vocab_list))
        words = vocab_list[pos:next_pos]

        # update position & last_sent
        user_settings[cid]["position"] = next_pos
        user_settings[cid]["last_sent"] = date.today().isoformat()
        save_settings()

        # send the batch
        if context:
            context.bot.send_message(chat_id=int(cid), text="\n".join(words))

        print(f"[Sent] {cid} → words {pos}-{next_pos}")
    except Exception as e:
        print(f"[Error sending to {cid}] {e}")

# ────── Flask App for Webhook & Ping ──────
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running."

@app.route("/ping")
def ping():
    return "pong", 200, {"Content-Type": "text/plain"}

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook_handler():
    update = Update.de_json(request.get_json(force=True), updater.bot)
    updater.dispatcher.process_update(update)
    return "OK"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

threading.Thread(target=run_flask, daemon=True).start()

# ────── Reschedule & Catch‑Up on Startup ──────
for chat_id, info in user_settings.items():
    if {"time", "count", "position"}.issubset(info):
        # schedule daily job
        t_obj = datetime.strptime(info["time"], "%H:%M").time()
        trigger = CronTrigger(hour=t_obj.hour, minute=t_obj.minute, timezone=tz)
        scheduler.add_job(send_words, trigger, args=[None, int(chat_id)],
                          id=str(chat_id), replace_existing=True)

        # catch‑up if missed today
        now = datetime.now(tz)
        if (now.time() >= t_obj) and info.get("last_sent") != date.today().isoformat():
            print(f"[Catch‑Up] Missed {chat_id}, sending now...")
            send_words(None, int(chat_id))

# ────── Bot Handlers ──────
def start(update: Update, context: CallbackContext):
    update.message.reply_text("Nechta so‘z olishni xohlaysiz?")
    return ASK_COUNT

def ask_percent(update: Update, context: CallbackContext):
    chat_id = str(update.message.chat_id)
    try:
        count = int(update.message.text.strip())
        user_settings[chat_id] = {"count": count}
        save_settings()
        update.message.reply_text("Taxminan necha foizini o‘rgandingiz? (Masalan: 30)")
        return ASK_PERCENT
    except ValueError:
        update.message.reply_text("Iltimos, son kiriting.")
        return ASK_COUNT

def ask_time(update: Update, context: CallbackContext):
    chat_id = str(update.message.chat_id)
    try:
        percent = float(update.message.text.strip())
        total_words = len(vocab_list)
        start_index = min(math.floor(total_words * percent / 100), total_words - 1)
        user_settings[chat_id]["position"] = start_index
        save_settings()
        update.message.reply_text("Qaysi vaqtda yuboray? (Format: HH:MM, 24 soat)")
        return ASK_TIME
    except ValueError:
        update.message.reply_text("Iltimos, faqat raqamli foiz kiriting.")
        return ASK_PERCENT

def confirm_settings(update: Update, context: CallbackContext):
    chat_id = str(update.message.chat_id)
    try:
        send_time = datetime.strptime(update.message.text.strip(), "%H:%M").time()
        user_settings[chat_id]["time"] = send_time.strftime("%H:%M")
        save_settings()

        trigger = CronTrigger(hour=send_time.hour, minute=send_time.minute, timezone=tz)
        scheduler.add_job(send_words, trigger, args=[context, int(chat_id)],
                          id=chat_id, replace_existing=True)

        count = user_settings[chat_id]["count"]
        pos   = user_settings[chat_id]["position"]
        update.message.reply_text(
            f"Har kuni {count} ta so‘z yuboraman. Boshlanish: {pos+1}-chi so‘zdan, soat {send_time.strftime('%H:%M')} da."
        )
        print(f"[Scheduled] {chat_id} → from index {pos}, at {send_time}")
        return ConversationHandler.END
    except ValueError:
        update.message.reply_text("Vaqt formati noto‘g‘ri. Masalan: 16:00")
        return ASK_TIME

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Bekor qilindi.")
    return ConversationHandler.END

# ────── Main ──────
def main():
    global updater
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_COUNT:  [MessageHandler(Filters.text & ~Filters.command, ask_percent)],
            ASK_PERCENT:[MessageHandler(Filters.text & ~Filters.command, ask_time)],
            ASK_TIME:   [MessageHandler(Filters.text & ~Filters.command, confirm_settings)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    dp.add_handler(conv)

    # start webhook instead of polling
    updater.start_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        url_path=BOT_TOKEN,
    )
    updater.bot.set_webhook(WEBHOOK_URL)

    print("[Bot Started via Webhook]")
    updater.idle()

if __name__ == "__main__":
    main()
