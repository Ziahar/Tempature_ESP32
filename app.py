from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import telebot
import threading
import time
import requests
import matplotlib.pyplot as plt
import io
from matplotlib.dates import DateFormatter

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class Measurement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    light = db.Column(db.Integer, nullable=False)
    temp = db.Column(db.Float, nullable=False)
    hum = db.Column(db.Float, nullable=False)
    motion = db.Column(db.Boolean, default=False)
    gas = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return {
            "timestamp": self.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            "light": self.light,
            "temp": round(self.temp, 1),
            "hum": round(self.hum, 1),
            "motion": self.motion,
            "gas": self.gas
        }

with app.app_context():
    db.create_all()

# === НАЛАШТУВАННЯ TELEGRAM БОТА ===
TELEGRAM_TOKEN = '8561971309:AAG7dKvFlGYO5weT42p9OBdCD5ZkbyL2daQ'
CHAT_ID = 1481541168
SECRET_CODE = '1234'
ESP_IP = "192.168.1.107"  # Заміни на актуальну

bot = telebot.TeleBot(TELEGRAM_TOKEN)
user_state = {}

def send_notification(message):
    try:
        bot.send_message(CHAT_ID, message)
        print(f"[Telegram] Надіслано: {message}")
    except Exception as e:
        print(f"[Telegram] Помилка: {e}")

# Фонова перевірка 
def check_alerts():
    while True:
        with app.app_context():
            last = Measurement.query.order_by(Measurement.timestamp.desc()).first()
            if last:
                alert = ""
                if last.temp > 30: alert += f"Висока температура: {last.temp}°C! "
                if last.hum > 70: alert += f"Висока вологість: {last.hum}%! "
                if last.light < 200: alert += f"Низька освітленість: {last.light}! "

                if alert:
                    send_notification(f"⚠️ Сповіщення!\n{alert}\nЧас: {last.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        time.sleep(60)

threading.Thread(target=check_alerts, daemon=True).start()

def run_bot_polling():
    print("[Telegram] Бот запущено...")
    try:
        bot.polling(none_stop=True, interval=0, timeout=30)
    except Exception as e:
        print(f"[Telegram] Polling помилка: {e}")

threading.Thread(target=run_bot_polling, daemon=True).start()

send_notification("Розумний будинок онлайн 🏠\nНапиши /start")

# ==================== КОМАНДИ БОТА ====================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привіт! Це бот моніторингу та керування розумним будинком 🏠\n"
                          "Команди:\n"
                          "/start — привітання\n"
                          "/status — останні дані\n"
                          "/history [дата] HH:MM HH:MM — графік за період\n"
                          "Приклад: /history 15:00 16:00\n"
                          "Або: /history 2025-03-01 10:00 12:00\n"
                          "/led_on — увімкнути LED\n/led_off — вимкнути LED")

@bot.message_handler(commands=['status'])
def send_status(message):
    with app.app_context():
        last = Measurement.query.order_by(Measurement.timestamp.desc()).first()
        if last:
            reply = (
                f"Останні дані:\n\n"
                f"🌡️ Температура: {last.temp} °C\n"
                f"💧 Вологість: {last.hum} %\n"
                f"☀️ Освітленість: {last.light}\n"
                f"🔥 Газ: {'Так' if last.gas else 'Ні'}\n"
                f"🚶 Рух: {'Так' if last.motion else 'Ні'}\n"
                f"🕒 {last.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            bot.reply_to(message, reply)
        else:
            bot.reply_to(message, "Даних ще немає 😔")

@bot.message_handler(commands=['history'])
def send_history(message):
    args = message.text.split()[1:]
    if len(args) not in (2, 3):
        bot.reply_to(message, "Формат:\n/history HH:MM HH:MM\nабо\n/history YYYY-MM-DD HH:MM HH:MM\nПриклад:\n/history 15:00 16:00\n/history 2025-03-01 10:00 12:00")
        return

    try:
        if len(args) == 2:
            date_str = datetime.now().strftime("%Y-%m-%d")
            start_str, end_str = args
        else:
            date_str, start_str, end_str = args

        start_dt = datetime.strptime(f"{date_str} {start_str}", "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(f"{date_str} {end_str}", "%Y-%m-%d %H:%M")

        with app.app_context():
            records = Measurement.query.filter(
                Measurement.timestamp >= start_dt,
                Measurement.timestamp <= end_dt
            ).order_by(Measurement.timestamp.asc()).all()

            if not records:
                bot.reply_to(message, f"За період {start_str}–{end_str} ({date_str}) даних немає")
                return

            # Малюємо графік
            times = [r.timestamp for r in records]
            temps = [r.temp for r in records]
            hums = [r.hum for r in records]
            lights = [r.light for r in records]

            fig, ax1 = plt.subplots(figsize=(10, 6))

            ax1.set_xlabel('Час')
            ax1.set_ylabel('Температура (°C) / Вологість (%)', color='tab:blue')
            ax1.plot(times, temps, color='tab:red', label='Температура', linewidth=2)
            ax1.plot(times, hums, color='tab:blue', label='Вологість', linewidth=2)
            ax1.tick_params(axis='y', labelcolor='tab:blue')
            ax1.legend(loc='upper left')

            ax2 = ax1.twinx()
            ax2.set_ylabel('Освітленість (raw)', color='tab:orange')
            ax2.plot(times, lights, color='tab:orange', label='Освітленість', linewidth=2)
            ax2.tick_params(axis='y', labelcolor='tab:orange')
            ax2.legend(loc='upper right')

            fig.suptitle(f'Дані за період {date_str} {start_str}–{end_str}', fontsize=16)
            fig.autofmt_xdate()
            ax1.xaxis.set_major_formatter(DateFormatter('%H:%M'))

            buf = io.BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
            plt.close()

            bot.send_photo(message.chat.id, buf, caption=f"Графік за {start_str}–{end_str} ({date_str})")

    except ValueError:
        bot.reply_to(message, "Неправильний формат! Приклад:\n/history 15:00 16:00\nабо /history 2025-03-01 10:00 12:00")

@bot.message_handler(commands=['led_on', 'led_off'])
def request_code(message):
    command = message.text[1:]
    user_id = message.from_user.id

    if user_id != CHAT_ID:
        bot.reply_to(message, "Доступ заборонено!")
        return

    user_state[user_id] = {'command': command, 'waiting_code': True}
    bot.reply_to(message, "Введи секретний код:")

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    user_id = message.from_user.id

    if user_id in user_state and user_state[user_id].get('waiting_code', False):
        code = message.text.strip()
        if code == SECRET_CODE:
            command = user_state[user_id]['command']
            url = ""

            if command == 'led_on':
                url = f"http://{ESP_IP}/led/on"
                action = "увімкнено"
            elif command == 'led_off':
                url = f"http://{ESP_IP}/led/off"
                action = "вимкнено"

            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    bot.reply_to(message, f"Світлодіод {action} успішно! 💡")
                else:
                    bot.reply_to(message, f"Помилка: {response.status_code}")
            except Exception as e:
                bot.reply_to(message, f"Не вдалося підключитися до ESP32: {str(e)}")

            del user_state[user_id]
        else:
            bot.reply_to(message, "Неправильний код!")
    else:
        bot.reply_to(message, "Напиши /start, /status або /history")

# ==================================================
@app.route('/data', methods=['POST'])
def receive_data():
    try:
        data = request.get_json(force=True)
        print(f"Отримано: {data}")

        m = Measurement(
            light=int(data.get('light', data.get('soil', 0))),
            temp=float(data['temp']),
            hum=float(data['hum']),
            motion=bool(data.get('motion', False)),
            gas=bool(data.get('gas', False))
        )

        db.session.add(m)
        db.session.commit()

        if m.gas:
            send_notification("🚨 Виявлено газ/дим!\nВідчиніть вікно та викличіть 104!")

        if m.motion:
            send_notification("🚨 Небезпека вторгнення!\nPIR-датчик спрацював!")

        if m.temp > 28:
            send_notification(f"🌡️ У будинку жарко: {m.temp}°C!\n"
                              f"Рекомендую увімкнути вентилятор для комфортної температури.")

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"Помилка: {e}")
        return jsonify({"error": str(e)}), 400

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data')
def api_data():
    limit = request.args.get('limit', 1000, type=int)
    measurements = Measurement.query.order_by(Measurement.timestamp.desc()).limit(limit).all()
    measurements.reverse()
    return jsonify([m.to_dict() for m in measurements])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
