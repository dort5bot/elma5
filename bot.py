import os
import csv
import threading
import requests
import time as time_module
from datetime import datetime, timedelta, time
from dotenv import load_dotenv
from telegram import (
    Update, ReplyKeyboardMarkup, InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, CallbackQueryHandler, filters
)

# =============== ORTAM YÜKLEME ===============
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.getenv("PORT", 10000))
KEEP_ALIVE_URL = os.getenv("KEEP_ALIVE_URL")  # UptimeRobot’un ping atacağı Render URL (https://seninapp.onrender.com)

# =============== CSV DOSYALARI ===============
ap_csv = "ap_history.csv"
p_csv = "p_history.csv"
alarms_csv = "alarms.csv"

f_lists = {
    "F1": ["BTC", "ETH", "BNB", "SOL"],
    "F2": ["PEPE", "BOME", "DOGE"],
    "F3": ["S", "CAKE", "ZRO"]
}

# =============== FONKSİYONLAR ===============
def get_price(symbol: str):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}USDT"
    try:
        data = requests.get(url, timeout=5).json()
        return float(data["price"])
    except:
        return None

def format_price(price: float):
    if price is None:
        return "❌"
    return f"{price:.8f}$" if price < 1 else f"{price:.2f}$"

def get_ap_scores():
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        data = requests.get(url, timeout=5).json()
        alt_btc_strength, alt_usdt_strength, long_term_strength = [], [], []
        for c in data:
            symbol = c["symbol"]
            price_change = float(c["priceChangePercent"])
            volume = float(c["quoteVolume"])
            if symbol.endswith("BTC") and volume > 10:
                alt_btc_strength.append(price_change)
            if symbol.endswith("USDT") and volume > 1_000_000:
                alt_usdt_strength.append(price_change)
            if volume > 5_000_000:
                long_term_strength.append(price_change)

        def normalize(values):
            if not values:
                return 0
            avg = sum(values) / len(values)
            return max(0, min(100, (avg + 10) * 5))

        return normalize(alt_btc_strength), normalize(alt_usdt_strength), normalize(long_term_strength)
    except:
        return 0, 0, 0

def save_csv(filename, row):
    file_exists = os.path.exists(filename)
    with open(filename, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            if "ap" in filename:
                writer.writerow(["Timestamp", "BTC", "USDT", "LONG"])
            elif "alarm" in filename:
                writer.writerow(["Timestamp", "Datetime", "Commands"])
            else:
                writer.writerow(["Timestamp", "List", "Coin", "Price"])
        writer.writerow(row)

def get_previous_ap():
    if not os.path.exists(ap_csv):
        return None, None, None
    with open(ap_csv, "r", encoding="utf-8") as f:
        rows = list(csv.reader(f))
        if len(rows) < 2:
            return None, None, None
        last = rows[-1]
        return float(last[1]), float(last[2]), float(last[3])

def get_keyboard():
    keys = [["AP", "H"], ["P BTC BNB"], ["F1", "F2", "F3"]]
    return ReplyKeyboardMarkup(keys, resize_keyboard=True)

# =============== KOMUTLAR ===============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Bot çalışıyor.\nKomutlardan birini seç veya yaz.\n"
        "Alarm Kur: alarm 2025-07-20 08:00 ap f1\n"
        "/list: mevcut listeleri gör\n"
        "/addlist F4 BTC XRP ... yeni liste ekle\n"
        "/dellist F4 listeyi sil",
        reply_markup=get_keyboard()
    )

async def ap_command(update: Update, context: ContextTypes.DEFAULT_TYPE, auto=False):
    prev_btc, prev_usdt, prev_long = get_previous_ap()
    btc, usdt, long = get_ap_scores()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    save_csv(ap_csv, [timestamp, f"{btc:.2f}", f"{usdt:.2f}", f"{long:.2f}"])

    def change_text(current, previous):
        if previous is None:
            return ""
        diff = current - previous
        arrow = "🟢" if diff > 0 else "🔴"
        return f" {arrow} {diff:+.2f}"

    text = f"""
📊 *AP Raporu*
- Altların BTC'ye karşı: {btc:.1f}/100{change_text(btc, prev_btc)}
- Alt Kısa Vade: {usdt:.1f}/100{change_text(usdt, prev_usdt)}
- Coinlerin Uzun Vade: {long:.1f}/100{change_text(long, prev_long)}
"""
    if auto:
        await context.bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper()
    coins = []
    if text.startswith("/"):  # /p btc bnb
        coins = [c.upper() for c in context.args]
    else:
        parts = text.split()
        coins = parts[1:] if len(parts) > 1 else []

    if not coins:
        await update.message.reply_text("❌ Kullanım: P BTC BNB ETH ...")
        return

    results = []
    for coin in coins:
        price = get_price(coin)
        results.append(f"{coin}: {format_price(price)}")
    await update.message.reply_text("\n".join(results))

async def f_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper()
    if text not in f_lists:
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    results = [f"💹 *{text} Fiyatları:*"]
    for coin in f_lists[text]:
        price = get_price(coin)
        results.append(f"- {coin}: {format_price(price)}")
        save_csv(p_csv, [timestamp, text, coin, f"{price:.6f}"])
    await update.message.reply_text("\n".join(results), parse_mode="Markdown")

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📋 *Mevcut F Listeleri:*\n"
    for k, v in f_lists.items():
        text += f"{k}: {', '.join(v)}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# =============== ALARM İŞLEMLERİ ===============
async def alarm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = update.message.text.split()
        if len(args) < 3:
            await update.message.reply_text("❌ Kullanım: alarm YYYY-MM-DD HH:MM komut1 komut2 ...")
            return
        dt_str = args[1]
        if len(args[2]) == 5 and ":" in args[2]:  # alarm 08:00 ap f1
            dt_str = f"{datetime.now().strftime('%Y-%m-%d')} {args[1]}"
            commands = args[2:]
        else:  # alarm 2025-07-20 08:00 ap f1
            dt_str = f"{args[1]} {args[2]}"
            commands = args[3:]
        alarm_time = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")

        if alarm_time < datetime.now():
            await update.message.reply_text("❌ Geçmiş bir tarih/saat olamaz.")
            return

        save_csv(alarms_csv, [datetime.now().strftime("%Y-%m-%d %H:%M"), alarm_time, " ".join(commands)])
        context.job_queue.run_once(trigger_alarm, alarm_time, data={"commands": commands, "time": alarm_time})
        await update.message.reply_text(f"✅ Alarm kuruldu: {alarm_time} → {' '.join(commands)}")
    except Exception as e:
        await update.message.reply_text(f"❌ Alarm kurulamadı: {e}")

async def trigger_alarm(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    commands = job_data["commands"]
    alarm_time = job_data["time"]

    buttons = [
        [
            InlineKeyboardButton("⏹ Durdur", callback_data=f"stop_{alarm_time}"),
            InlineKeyboardButton("🔁 Tekrar Kur", callback_data=f"repeat_{alarm_time}")
        ]
    ]
    msg = f"⏰ *Alarm*: {alarm_time}\nKomutlar: {' '.join(commands)}"
    await context.bot.send_message(
        chat_id=CHAT_ID,
        text=msg,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

    for cmd in commands:
        fake_update = Update(update_id=0, message=None)
        if cmd.lower() == "ap":
            await ap_command(fake_update, context, auto=True)
        elif cmd.upper() in f_lists:
            await context.bot.send_message(chat_id=CHAT_ID, text=f"⏳ {cmd} çalışıyor...")
            await f_list(fake_update, context)
        elif cmd.upper().startswith("P"):
            await price_command(fake_update, context)

async def alarm_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("stop_"):
        await query.edit_message_text("⏹ Alarm durduruldu.")
    elif query.data.startswith("repeat_"):
        alarm_time = datetime.now() + timedelta(days=1)
        await query.edit_message_text(f"🔁 Alarm tekrarlandı: {alarm_time}")
        context.job_queue.run_once(trigger_alarm, alarm_time, data={"commands": ["ap"], "time": alarm_time})

# =============== GÜNLÜK TEMİZLİK ===============
async def daily_cleanup(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if os.path.exists(ap_csv):
        with open(ap_csv, "r", encoding="utf-8") as f:
            rows = list(csv.reader(f))[1:]
        if rows:
            btc_avg = sum(float(r[1]) for r in rows) / len(rows)
            usdt_avg = sum(float(r[2]) for r in rows) / len(rows)
            long_avg = sum(float(r[3]) for r in rows) / len(rows)
            with open(ap_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Timestamp", "BTC", "USDT", "LONG"])
                writer.writerow([now, f"{btc_avg:.2f}", f"{usdt_avg:.2f}", f"{long_avg:.2f}"])
    await context.bot.send_message(chat_id=CHAT_ID, text="✅ Günlük temizlik tamamlandı.")

# =============== KEEP-ALIVE (UptimeRobot uyumlu) ===============
def keep_alive():
    if not KEEP_ALIVE_URL:
        print("KEEP_ALIVE_URL ayarlanmamış, ping yapılmayacak.")
        return
    while True:
        try:
            requests.get(KEEP_ALIVE_URL, timeout=5)
            print(f"[KEEP-ALIVE] Ping gönderildi → {KEEP_ALIVE_URL}")
        except Exception as e:
            print(f"[KEEP-ALIVE] Hata: {e}")
        time_module.sleep(60 * 5)  # Her 5 dakikada bir ping at

# =============== ANA FONKSİYON ===============
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ap", ap_command))
    app.add_handler(CommandHandler("p", price_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("alarm", alarm_command))
    app.add_handler(CallbackQueryHandler(alarm_buttons))
    app.add_handler(MessageHandler(filters.Regex("^(AP|ap)$"), lambda u, c: ap_command(u, c)))
    app.add_handler(MessageHandler(filters.Regex("^P "), price_command))
    app.add_handler(MessageHandler(filters.Regex("^F[0-9]+$"), f_list))

    app.job_queue.run_daily(daily_cleanup, time=time(hour=21, minute=0))

    # Keep-alive başlat
    threading.Thread(target=keep_alive, daemon=True).start()

    print("Bot Webhook ile çalışıyor...")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="",  # boş bırakılırsa token otomatik kullanılır
        webhook_url=KEEP_ALIVE_URL
    )

if __name__ == "__main__":
    main()
