from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, time
import telebot
import threading
import time
import requests

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

    def to_dict(self):
        return {
            "timestamp": self.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            "light": self.light,
            "temp": round(self.temp, 1),
            "hum": round(self.hum, 1)
        }

with app.app_context():
    db.create_all()

# === НАЛАШТУВАННЯ TELEGRAM БОТА ===
TELEGRAM_TOKEN = '8561971309:AAG7dKvFlGYO5weT42p9OBdCD5ZkbyL2daQ'
CHAT_ID = 1481541168
SECRET_CODE = '1234'

ESP_IP = "192.168.1.107"  # Заміни на актуальну IP ESP32

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

# Запускаємо polling бота
def run_bot_polling():
    print("[Telegram] Запущено polling бота...")
    try:
        bot.polling(none_stop=True, interval=0, timeout=30)
    except Exception as e:
        print(f"[Telegram] Polling помилка: {e}")

threading.Thread(target=run_bot_polling, daemon=True).start()

# Тестове повідомлення при запуску
send_notification("Розумний будинок онлайн 🏠\nНапиши /start")

# === ОБРОБНИКИ КОМАНД БОТА ===

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привіт! Це бот моніторингу та керування розумним будинком 🏠\n"
                          "Команди:\n"
                          "/start — привітання\n"
                          "/status — останні дані\n"
                          "/history HH:MM HH:MM — дані за період (наприклад /history 15:00 16:00)\n"
                          "/led_on — увімкнути LED\n/led_off — вимкнути LED")

@bot.message_handler(commands=['status'])
def send_status(message):
    with app.app_context():
        last = Measurement.query.order_by(Measurement.timestamp.desc()).first()
        if last:
            reply = (
                f"Останні дані:\n"
                f"Температура: {last.temp} °C\n"
                f"Вологість: {last.hum} %\n"
                f"Освітленість: {last.light}\n"
                f"Час: {last.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            bot.reply_to(message, reply)
        else:
            bot.reply_to(message, "Даних ще немає 😔")

@bot.message_handler(commands=['history'])
def send_history(message):
    args = message.text.split()[1:]  # все після /history
    if len(args) != 2:
        bot.reply_to(message, "Формат: /history HH:MM HH:MM\nПриклад: /history 15:00 16:00")
        return

    try:
        start_time_str, end_time_str = args
        start_time = datetime.strptime(start_time_str, "%H:%M").time()
        end_time = datetime.strptime(end_time_str, "%H:%M").time()

        today = datetime.now().date()

        with app.app_context():
            records = Measurement.query.filter(
                db.func.date(Measurement.timestamp) == today,
                db.func.time(Measurement.timestamp) >= start_time,
                db.func.time(Measurement.timestamp) <= end_time
            ).order_by(Measurement.timestamp.asc()).all()

            if not records:
                bot.reply_to(message, f"За період {start_time_str}–{end_time_str} даних немає 😔")
                return

            reply = f"Дані за період {start_time_str}–{end_time_str}:\n\n"
            for r in records:
                reply += (
                    f"{r.timestamp.strftime('%H:%M:%S')}\n"
                    f"  Темп: {r.temp} °C\n"
                    f"  Вол: {r.hum} %\n"
                    f"  Освітл: {r.light}\n\n"
                )

            bot.reply_to(message, reply)

    except ValueError:
        bot.reply_to(message, "Неправильний формат часу! Використовуй HH:MM (наприклад 15:00)")

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
        bot.reply_to(message, "Напиши /start або /status")

# ==================================================
@app.route('/data', methods=['POST'])
def receive_data():
    try:
        data = request.get_json(force=True)
        print(f"Отримано: {data}")

        m = Measurement(
            light=int(data.get('light', data.get('soil', 0))),
            temp=float(data['temp']),
            hum=float(data['hum'])
        )
        db.session.add(m)
        db.session.commit()

        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(e)
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
