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

# =============== GENEL FONKSİYONLAR ===============
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
                writer.writerow(["Timestamp", "Datetime", "Commands", "Repeat"])
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
        "✅ Bot çalışıyor.\n"
        "Alarm Kur: /alarm 21:00 ap f1 f2 (her gün)\n"
        "/alarm 2025-07-20 23:00 ap f1 (tek seferlik)\n"
        "/alarmlist - kurulu alarmları listele\n"
        "/delalarm <id> - alarm sil\n"
        "/cleancsv all - CSV temizle",
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
    coins = [c.upper() for c in text.split()[1:]]
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
        save_csv(p_csv, [timestamp, text, coin, f"{price if price else 0:.6f}"])
    await update.message.reply_text("\n".join(results), parse_mode="Markdown")

# =============== ALARM İŞLEMLERİ ===============
async def alarm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = update.message.text.split()
        if len(args) < 2:
            await update.message.reply_text("❌ Kullanım: /alarm [YYYY-MM-DD] HH:MM komutlar")
            return

        repeat = False
        if len(args[1]) == 5 and ":" in args[1]:
            # Her gün tekrarlayan
            alarm_time = datetime.strptime(args[1], "%H:%M").time()
            repeat = True
            context.job_queue.run_daily(trigger_alarm, time=alarm_time, data={"commands": args[2:], "repeat": True})
            save_csv(alarms_csv, [datetime.now().strftime("%Y-%m-%d %H:%M"), f"Her Gün {args[1]}", " ".join(args[2:]), "YES"])
            await update.message.reply_text(f"✅ Her gün {args[1]} → {' '.join(args[2:])}")
        else:
            # Tek seferlik
            dt = f"{args[1]} {args[2]}"
            alarm_time = datetime.strptime(dt, "%Y-%m-%d %H:%M")
            context.job_queue.run_once(trigger_alarm, alarm_time, data={"commands": args[3:], "repeat": False})
            save_csv(alarms_csv, [datetime.now().strftime("%Y-%m-%d %H:%M"), alarm_time, " ".join(args[3:]), "NO"])
            await update.message.reply_text(f"✅ Alarm kuruldu: {alarm_time} → {' '.join(args[3:])}")
    except Exception as e:
        await update.message.reply_text(f"❌ Alarm kurulamadı: {e}")

async def trigger_alarm(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    commands = job_data["commands"]
    msg = f"⏰ *Alarm*: {' '.join(commands)}"
    await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
    for cmd in commands:
        fake_update = Update(update_id=0, message=None)
        if cmd.lower() == "ap":
            await ap_command(fake_update, context, auto=True)
        elif cmd.upper() in f_lists:
            await f_list(fake_update, context)
        elif cmd.upper().startswith("P"):
            await price_command(fake_update, context)

async def alarmlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(alarms_csv):
        await update.message.reply_text("❌ Kayıtlı alarm yok.")
        return
    with open(alarms_csv, "r", encoding="utf-8") as f:
        rows = list(csv.reader(f))[1:]
    if not rows:
        await update.message.reply_text("❌ Kayıtlı alarm yok.")
        return
    text = "⏰ *Kurulu Alarmlar:*\n"
    for i, r in enumerate(rows, start=1):
        text += f"{i}. {r[1]} → {r[2]} ({'Tek Sefer' if r[3]=='NO' else 'Her Gün'})\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def delalarm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = update.message.text.split()
    if len(args) < 2:
        await update.message.reply_text("❌ Kullanım: /delalarm <id>")
        return
    alarm_id = int(args[1])
    if not os.path.exists(alarms_csv):
        await update.message.reply_text("❌ Alarm bulunamadı.")
        return
    with open(alarms_csv, "r", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if alarm_id < 1 or alarm_id >= len(rows):
        await update.message.reply_text("❌ Geçersiz ID.")
        return
    del rows[alarm_id]
    with open(alarms_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    await update.message.reply_text("✅ Alarm silindi.")

# =============== TEMİZLİK İŞLEMLERİ ===============
def cleanup_csv_file(filename, days=30, max_lines=10000):
    if not os.path.exists(filename):
        return
    with open(filename, "r", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if len(rows) <= 1:
        return
    header, data = rows[0], rows[1:]
    filtered = []
    now = datetime.now()
    for row in data:
        try:
            row_time = datetime.strptime(row[0], "%Y-%m-%d %H:%M")
            if now - row_time <= timedelta(days=days):
                filtered.append(row)
        except:
            filtered.append(row)
    if len(filtered) > max_lines:
        filtered = filtered[-max_lines:]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(filtered)

async def auto_cleanup(context: ContextTypes.DEFAULT_TYPE):
    for file in [ap_csv, p_csv, alarms_csv]:
        cleanup_csv_file(file)
    await context.bot.send_message(chat_id=CHAT_ID, text="✅ Otomatik temizlik tamamlandı.")

async def cleancsv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = update.message.text.split()
    target = args[1].lower() if len(args) > 1 else "all"
    files = {
        "ap": ap_csv,
        "p": p_csv,
        "alarms": alarms_csv
    }
    if target == "all":
        for f in files.values():
            cleanup_csv_file(f, days=0)
        await update.message.reply_text("✅ Tüm CSV'ler temizlendi.")
    elif target in files:
        cleanup_csv_file(files[target], days=0)
        await update.message.reply_text(f"✅ {target} temizlendi.")
    else:
        await update.message.reply_text("❌ Geçersiz parametre. /cleancsv all|ap|p|alarms")

# =============== KEEP-ALIVE ===============
def keep_alive():
    if not KEEP_ALIVE_URL:
        print("KEEP_ALIVE_URL ayarlanmamış.")
        return
    while True:
        try:
            requests.get(KEEP_ALIVE_URL, timeout=5)
            print(f"[KEEP-ALIVE] Ping gönderildi → {KEEP_ALIVE_URL}")
        except:
            pass
        time_module.sleep(60 * 5)

# =============== ANA FONKSİYON ===============
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ap", ap_command))
    app.add_handler(CommandHandler("p", price_command))
    app.add_handler(CommandHandler("list", lambda u, c: u.message.reply_text(str(f_lists))))
    app.add_handler(CommandHandler("alarm", alarm_command))
    app.add_handler(CommandHandler("alarmlist", alarmlist))
    app.add_handler(CommandHandler("delalarm", delalarm))
    app.add_handler(CommandHandler("cleancsv", cleancsv))
    app.add_handler(MessageHandler(filters.Regex("^(AP|ap)$"), lambda u, c: ap_command(u, c)))
    app.add_handler(MessageHandler(filters.Regex("^P "), price_command))
    app.add_handler(MessageHandler(filters.Regex("^F[0-9]+$"), f_list))

    app.job_queue.run_daily(auto_cleanup, time=time(hour=3, minute=0))

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
