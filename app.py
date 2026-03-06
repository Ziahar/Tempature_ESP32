from flask import Flask, request, jsonify, render_template
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import telebot
import threading
import time
import matplotlib.pyplot as plt
import io
from matplotlib.dates import DateFormatter
from zoneinfo import ZoneInfo
import os

app = Flask(__name__)

# === GOOGLE SHEETS ===
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS_FILE = "smart-house.json"  # завантаж цей файл у корінь проєкту на GitHub

creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
client = gspread.authorize(creds)
SHEET_ID = "1iTxnmPncCOAaZVBTBQL_fVj7ODgFVSZ8WzorefUui88"  # заміни
sheet = client.open_by_key(SHEET_ID).sheet1

# === TELEGRAM БОТ ===
TELEGRAM_TOKEN = '8561971309:AAG7dKvFlGYO5weT42p9OBdCD5ZkbyL2daQ'
CHAT_ID = 1481541168

bot = telebot.TeleBot(TELEGRAM_TOKEN)

def send_notification(message):
    try:
        bot.send_message(CHAT_ID, message)
        print(f"[Telegram] Надіслано: {message}")
    except Exception as e:
        print(f"[Telegram] Помилка: {e}")

# Фонова перевірка
def check_alerts():
    while True:
        # Отримуємо останній рядок з Google Sheets
        rows = sheet.get_all_values()
        if len(rows) > 1:
            last = rows[-1]
            temp = float(last[3]) if last[3] else 0
            hum = float(last[4]) if last[4] else 0
            light = int(last[5]) if last[5] else 0
            gas = last[7] == "Так"

            if temp > 28:
                send_notification(f"🌡️ У будинку жарко: {temp}°C!\nРекомендую увімкнути вентилятор.")
            if gas:
                send_notification("🚨 Виявлено газ/дим!\nВідчиніть вікно та викличіть 104!")
        time.sleep(60)

threading.Thread(target=check_alerts, daemon=True).start()

# Polling бота
def run_bot_polling():
    print("[Telegram] Бот запущено...")
    try:
        bot.polling(none_stop=True, interval=0, timeout=30)
    except Exception as e:
        print(f"[Telegram] Polling помилка: {e}")

threading.Thread(target=run_bot_polling, daemon=True).start()

send_notification("Розумний будинок онлайн 🏠\nНапиши /start")

# Команди бота (без змін, тільки /start, /status, /history)
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привіт! Це бот моніторингу розумного будинку 🏠\n"
                          "Команди:\n/start — привітання\n/status — останні дані\n/history HH:MM HH:MM — графік за період")

@bot.message_handler(commands=['status'])
def send_status(message):
    rows = sheet.get_all_values()
    if len(rows) > 1:
        last = rows[-1]
        reply = (
            f"Останні дані:\n\n"
            f"🌡️ Температура: {last[3]} °C\n"
            f"💧 Вологість: {last[4]} %\n"
            f"☀️ Освітленість: {last[5]}\n"
            f"🔥 Газ: {last[7]}\n"
            f"🕒 {last[1]} {last[2]}"
        )
        bot.reply_to(message, reply)
    else:
        bot.reply_to(message, "Даних ще немає 😔")

# /history — графік за період (тут тільки текстовий список, якщо хочеш графік — скажи, додамо)
@bot.message_handler(commands=['history'])
def send_history(message):
    bot.reply_to(message, "Функція /history тимчасово в текстовому режимі.\nСкоро додаю графіки!")

# ==================================================
@app.route('/data', methods=['POST'])
def receive_data():
    try:
        data = request.get_json(force=True)
        print(f"Отримано: {data}")

        timestamp = datetime.now().strftime('%Y-%m-%d')
        time_str = datetime.now().strftime('%H:%M:%S')

        row = [
            len(sheet.get_all_values()),  # ID
            timestamp,                    # Дата
            time_str,                     # Час
            data.get('temp', 0),
            data.get('hum', 0),
            data.get('light', 0),
            data.get('motion', False),
            "Так" if data.get('gas', False) else "Ні"
        ]

        sheet.append_row(row)

        # Сповіщення
        temp = float(data.get('temp', 0))
        gas = data.get('gas', False)

        if temp > 28:
            send_notification(f"🌡️ У будинку жарко: {temp}°C!\nРекомендую увімкнути вентилятор.")

        if gas:
            send_notification("🚨 Виявлено газ/дим!\nВідчиніть вікно та викличіть 104!")

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"Помилка: {e}")
        return jsonify({"error": str(e)}), 400

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data')
def api_data():
    rows = sheet.get_all_values()[1:]  # без заголовків
    data = []
    for row in rows:
        if len(row) >= 6:
            data.append({
                "timestamp": f"{row[1]} {row[2]}",
                "light": int(row[5]),
                "temp": float(row[3]),
                "hum": float(row[4])
            })
    return jsonify(data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
