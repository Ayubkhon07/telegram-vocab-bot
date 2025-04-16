from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, ConversationHandler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask
from datetime import datetime
from pytz import timezone
from vocab_data import vocab_list
import math
import json
import threading

# Bot token (replace with your own)
BOT_TOKEN = "7575015472:AAE6RZZcJDeAMHaCMr62crpKULf5YJkq5Pw"

# States
ASK_COUNT, ASK_PERCENT, ASK_TIME = range(3)

# Timezone setup
tz = timezone("Asia/Tashkent")

# Scheduler
scheduler = BackgroundScheduler(timezone=tz)
scheduler.start()

# Flask server to keep bot alive
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running."

@app.route('/ping')
def ping():
    return "pong", 200, {"Content-Type": "text/plain"}

def start_flask():
    app.run(host='0.0.0.0', port=8080)

threading.Thread(target=start_flask).start()

# In-memory storage
user_settings = {}

# Handlers
def start(update: Update, context: CallbackContext):
    update.message.reply_text("Nechta so‘z olishni xohlaysiz?")
    return ASK_COUNT

def ask_percent(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    try:
        count = int(update.message.text.strip())
        user_settings[chat_id] = {'count': count}
        update.message.reply_text("Taxminan necha foizini o‘rgandingiz? (Masalan: 30)")
        return ASK_PERCENT
    except ValueError:
        update.message.reply_text("Iltimos, son kiriting.")
        return ASK_COUNT

def ask_time(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    try:
        percent = float(update.message.text.strip())
        total_words = len(vocab_list)
        start_index = min(math.floor(total_words * percent / 100), total_words - 1)
        user_settings[chat_id]['position'] = start_index
        update.message.reply_text("Qaysi vaqtda yuboray? (Format: HH:MM, 24 soat)")
        return ASK_TIME
    except ValueError:
        update.message.reply_text("Iltimos, faqat raqamli foiz kiriting.")
        return ASK_PERCENT

def confirm_settings(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    try:
        send_time = datetime.strptime(update.message.text.strip(), "%H:%M").time()
        user_settings[chat_id]['time'] = send_time

        # Schedule daily job
        trigger = CronTrigger(hour=send_time.hour, minute=send_time.minute, timezone=tz)
        scheduler.add_job(send_words, trigger, args=[context, chat_id], id=str(chat_id), replace_existing=True)

        count = user_settings[chat_id]['count']
        pos = user_settings[chat_id]['position']
        update.message.reply_text(f"Har kuni {count} ta so‘z yuboraman. Boshlanish: {pos + 1}-chi so‘zdan, soat {send_time.strftime('%H:%M')} da.")
        print(f"[Scheduled] Chat {chat_id} from index {pos} at {send_time.strftime('%H:%M')}")
        return ConversationHandler.END
    except ValueError:
        update.message.reply_text("Vaqt formati noto‘g‘ri. Masalan: 16:00")
        return ASK_TIME

def send_words(context: CallbackContext, chat_id: int):
    try:
        count = user_settings[chat_id]['count']
        pos = user_settings[chat_id]['position']
        next_pos = min(pos + count, len(vocab_list))
        words = vocab_list[pos:next_pos]
        user_settings[chat_id]['position'] = next_pos

        context.bot.send_message(chat_id=chat_id, text="\n".join(words))
        print(f"[Sent] Chat {chat_id}: words {pos}-{next_pos}")
    except Exception as e:
        print(f"[Error] {e}")

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("Bekor qilindi.")
    return ConversationHandler.END

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            ASK_COUNT: [MessageHandler(Filters.text & ~Filters.command, ask_percent)],
            ASK_PERCENT: [MessageHandler(Filters.text & ~Filters.command, ask_time)],
            ASK_TIME: [MessageHandler(Filters.text & ~Filters.command, confirm_settings)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    dp.add_handler(conv_handler)
    print("[Bot Started]")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
