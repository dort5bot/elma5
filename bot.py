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
KEEP_ALIVE_URL = os.getenv("KEEP_ALIVE_URL")

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

# =============== ALARM TEMİZLİK ===============
def cleanup_old_alarms():
    """Geçmiş tarihli tek seferlik alarmları CSV’den siler"""
    if not os.path.exists(alarms_csv):
        return
    now = datetime.now()
    with open(alarms_csv, "r", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if len(rows) <= 1:
        return
    new_rows = [rows[0]]
    removed_count = 0
    for r in rows[1:]:
        if r[1].startswith("ONCE"):
            try:
                alarm_time = datetime.strptime(r[1].replace("ONCE ", ""), "%Y-%m-%d %H:%M:%S")
            except:
                try:
                    alarm_time = datetime.strptime(r[1].replace("ONCE ", ""), "%Y-%m-%d %H:%M")
                except:
                    new_rows.append(r)
                    continue
            if alarm_time < now:
                removed_count += 1
                continue
        new_rows.append(r)
    with open(alarms_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(new_rows)
    if removed_count > 0:
        print(f"[TEMİZLİK] {removed_count} eski ONCE alarmı silindi.")

# =============== KOMUTLAR ===============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Bot çalışıyor.\n"
        "Alarm Kur: /alarm 21:00 ap f1 f2 (her gün)\n"
        "/alarm 2025-07-20 23:00 ap f1 f2 (tek sefer)\n"
        "/alarmlist : kurulu alarmları göster\n"
        "/delalarm ID : alarmı sil",
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
    if text.startswith("/"):
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

# =============== ALARM İŞLEMLERİ ===============
async def alarm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = update.message.text.split()
        if len(args) < 2:
            await update.message.reply_text("❌ Kullanım: /alarm 21:00 ap f1 veya /alarm 2025-07-20 21:00 ap f1")
            return

        if len(args[1]) == 5 and ":" in args[1]:  # sadece saat girilmiş (her gün)
            alarm_time = datetime.strptime(args[1], "%H:%M").time()
            commands = args[2:]
            context.job_queue.run_daily(trigger_alarm, time=alarm_time,
                                        data={"commands": commands, "type": "DAILY", "time": args[1]})
            save_csv(alarms_csv, [datetime.now().strftime("%Y-%m-%d %H:%M"),
                                  f"DAILY {args[1]}", " ".join(commands)])
            await update.message.reply_text(f"✅ Günlük alarm kuruldu: {args[1]} → {' '.join(commands)}")
        else:  # tam tarih girilmiş (tek sefer)
            dt_str = f"{args[1]} {args[2]}"
            commands = args[3:]
            alarm_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            if alarm_dt < datetime.now():
                await update.message.reply_text("❌ Geçmiş bir tarih/saat olamaz.")
                return
            context.job_queue.run_once(trigger_alarm, alarm_dt,
                                       data={"commands": commands, "type": "ONCE", "time": alarm_dt})
            save_csv(alarms_csv, [datetime.now().strftime("%Y-%m-%d %H:%M"),
                                  f"ONCE {alarm_dt}", " ".join(commands)])
            await update.message.reply_text(f"✅ Tek seferlik alarm kuruldu: {alarm_dt} → {' '.join(commands)}")
    except Exception as e:
        await update.message.reply_text(f"❌ Alarm kurulamadı: {e}")

async def trigger_alarm(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    commands = job_data["commands"]
    alarm_type = job_data["type"]
    alarm_time = job_data["time"]

    buttons = [
        [
            InlineKeyboardButton("⏹ Durdur", callback_data=f"stop_{alarm_time}"),
            InlineKeyboardButton("🔁 Tekrar Kur", callback_data=f"repeat_{alarm_time}")
        ]
    ]
    msg = f"⏰ *Alarm ({alarm_type})*: {alarm_time}\nKomutlar: {' '.join(commands)}"
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
        context.job_queue.run_once(trigger_alarm, alarm_time,
                                   data={"commands": ["ap"], "type": "ONCE", "time": alarm_time})

async def alarmlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_old_alarms()
    if not os.path.exists(alarms_csv):
        await update.message.reply_text("⏹ Hiç alarm yok.")
        return
    with open(alarms_csv, "r", encoding="utf-8") as f:
        rows = list(csv.reader(f))[1:]
    if not rows:
        await update.message.reply_text("⏹ Hiç alarm yok.")
        return
    text = "📋 *Kurulu Alarmlar:*\n"
    for i, r in enumerate(rows, 1):
        text += f"{i}) {r[1]} → {r[2]}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def delalarm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = update.message.text.split()
        if len(args) < 2:
            await update.message.reply_text("❌ Kullanım: /delalarm ID")
            return
        alarm_id = int(args[1])
        if not os.path.exists(alarms_csv):
            await update.message.reply_text("⏹ Alarm yok.")
            return
        with open(alarms_csv, "r", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        if alarm_id <= 0 or alarm_id >= len(rows):
            await update.message.reply_text("❌ Geçersiz ID.")
            return
        removed = rows.pop(alarm_id)
        with open(alarms_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        await update.message.reply_text(f"✅ Alarm silindi: {removed[1]} → {removed[2]}")
    except Exception as e:
        await update.message.reply_text(f"❌ Alarm silinemedi: {e}")

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

    cleanup_old_alarms()
    await context.bot.send_message(chat_id=CHAT_ID, text="✅ Günlük temizlik tamamlandı.")

# =============== KEEP-ALIVE ===============
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
        time_module.sleep(60 * 5)

# =============== ANA FONKSİYON ===============
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ap", ap_command))
    app.add_handler(CommandHandler("p", price_command))
    app.add_handler(CommandHandler("alarm", alarm_command))
    app.add_handler(CommandHandler("alarmlist", alarmlist_command))
    app.add_handler(CommandHandler("delalarm", delalarm_command))
    app.add_handler(CallbackQueryHandler(alarm_buttons))
    app.add_handler(MessageHandler(filters.Regex("^(AP|ap)$"), lambda u, c: ap_command(u, c)))
    app.add_handler(MessageHandler(filters.Regex("^P "), price_command))
    app.add_handler(MessageHandler(filters.Regex("^F[0-9]+$"), f_list))

    app.job_queue.run_daily(daily_cleanup, time=time(hour=21, minute=0))

    threading.Thread(target=keep_alive, daemon=True).start()
    print("Bot Webhook ile çalışıyor...")
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="",
        webhook_url=KEEP_ALIVE_URL
    )

if __name__ == "__main__":
    main()
