import os
import json
import math
import threading
from datetime import datetime, date

from flask import Flask
from pytz import timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Update
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    ConversationHandler,
)
from vocab_data import vocab_list  # your 3000‑word list

# ─── CONFIG ──────────────────────────────────────────────────────────────────────
BOT_TOKEN     = os.environ["BOT_TOKEN"]            # set this in Render/Env
SETTINGS_FILE = "user_settings.json"               # stores { chat_id: {...} }
TZ            = timezone("Asia/Tashkent")          # your target zone
# ────────────────────────────────────────────────────────────────────────────────

# Conversation states
ASK_COUNT, ASK_PERCENT, ASK_TIME = range(3)

# Load (or init) persistent settings
if os.path.exists(SETTINGS_FILE):
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        user_settings = json.load(f)
else:
    user_settings = {}

def save_settings():
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(user_settings, f)

# ─── SCHEDULER ──────────────────────────────────────────────────────────────────
scheduler = BackgroundScheduler(timezone=TZ)
scheduler.start()

def send_words(context: CallbackContext, chat_id: int):
    """Actually send the next batch of words, advance position, save."""
    cid = str(chat_id)
    info = user_settings.get(cid)
    if not info:
        return  # no settings

    count    = info["count"]
    pos      = info.get("position", 0)
    next_pos = min(pos + count, len(vocab_list))
    batch    = vocab_list[pos:next_pos]

    # update settings
    info["position"]  = next_pos
    info["last_sent"] = date.today().isoformat()
    save_settings()

    # send
    text = "\n".join(batch)
    context.bot.send_message(chat_id=chat_id, text=text)

# On startup, re‑schedule existing jobs & catch up if missed
for cid, info in list(user_settings.items()):
    if all(k in info for k in ("time", "count", "position")):
        hh, mm = map(int, info["time"].split(":"))
        trigger = CronTrigger(hour=hh, minute=mm, timezone=TZ)
        scheduler.add_job(send_words, trigger,
                          args=[None, int(cid)],
                          id=str(cid), replace_existing=True)

        # catch‑up: if now past today’s send time and we haven’t sent yet today
        now   = datetime.now(TZ)
        today = date.today().isoformat()
        if now.time() >= datetime.now(TZ).replace(hour=hh, minute=mm).time():
            if info.get("last_sent") != today:
                print(f"[catch‑up] sending for {cid}")
                send_words(None, int(cid))

# ─── FLASK KEEPALIVE ───────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive!"

@app.route("/ping")
def ping():
    return "pong", 200, {"Content-Type": "text/plain"}

def run_flask():
    app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run_flask, daemon=True).start()

# ─── BOT HANDLERS ──────────────────────────────────────────────────────────────
def start(update: Update, context: CallbackContext):
    update.message.reply_text("Nechta so‘z olishni xohlaysiz?")
    return ASK_COUNT

def ask_percent(update: Update, context: CallbackContext):
    cid = str(update.effective_chat.id)
    try:
        cnt = int(update.message.text.strip())
    except ValueError:
        update.message.reply_text("Iltimos, to‘g‘ri son kiriting.")
        return ASK_COUNT

    user_settings[cid] = {"count": cnt}
    update.message.reply_text("Taxminan necha foizini o‘rgandingiz? (Masalan: 30)")
    return ASK_PERCENT

def ask_time(update: Update, context: CallbackContext):
    cid = str(update.effective_chat.id)
    try:
        pct        = float(update.message.text.strip())
        total      = len(vocab_list)
        start_idx  = min(math.floor(total * pct / 100), total - 1)
    except ValueError:
        update.message.reply_text("Iltimos, faqat raqam kiriting.")
        return ASK_PERCENT

    user_settings[cid]["position"] = start_idx
    update.message.reply_text("Qaysi vaqtda yuboray? (Format: HH:MM, 24 soat)")
    return ASK_TIME

def confirm_settings(update: Update, context: CallbackContext):
    cid = str(update.effective_chat.id)
    txt = update.message.text.strip()
    try:
        hh, mm = map(int, txt.split(":"))
    except:
        update.message.reply_text("Vaqt formatini tekshirib qayta kiriting (Mas: 16:00).")
        return ASK_TIME

    # save time
    user_settings[cid]["time"] = f"{hh:02d}:{mm:02d}"
    save_settings()

    # schedule
    trigger = CronTrigger(hour=hh, minute=mm, timezone=TZ)
    scheduler.add_job(send_words, trigger,
                      args=[context, int(cid)],
                      id=cid, replace_existing=True)

    cnt = user_settings[cid]["count"]
    pos = user_settings[cid]["position"]
    update.message.reply_text(
        f"Har kuni {cnt} ta so‘z yuboraman, boshlanish: {pos+1}-chi so‘zdan, soat {hh:02d}:{mm:02d}."
    )
    return ConversationHandler.END

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Bekor qilindi.")
    return ConversationHandler.END

# ─── MAIN ENTRYPOINT ───────────────────────────────────────────────────────────
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_COUNT:   [MessageHandler(Filters.text & ~Filters.command, ask_percent)],
            ASK_PERCENT: [MessageHandler(Filters.text & ~Filters.command, ask_time)],
            ASK_TIME:    [MessageHandler(Filters.text & ~Filters.command, confirm_settings)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    dp.add_handler(conv)

    print("[Bot Started: using long‑polling]")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
