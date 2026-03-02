from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import telebot
import threading
import time

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
            "timestamp": self.timestamp.isoformat(),
            "light": self.light,
            "temp": round(self.temp, 1),
            "hum": round(self.hum, 1)
        }

with app.app_context():
    db.create_all()

# === НАЛАШТУВАННЯ TELEGRAM БОТА ===
TELEGRAM_TOKEN = '8561971309:AAG7dKvFlGYO5weT42p9OBdCD5ZkbyL2daQ'
CHAT_ID = 1481541168   # твій особистий chat ID

bot = telebot.TeleBot(TELEGRAM_TOKEN)

def send_notification(message):
    try:
        bot.send_message(CHAT_ID, message)
        print(f"[Telegram] Надіслано: {message}")
    except Exception as e:
        print(f"[Telegram] Помилка: {e}")

# Фонова перевірка небезпечних значень
def check_alerts():
    while True:
        with app.app_context():
            last = Measurement.query.order_by(Measurement.timestamp.desc()).first()
            if last:
                alert = ""
                if last.temp > 30:     alert += f"Висока температура: {last.temp}°C! "
                if last.hum > 70:      alert += f"Висока вологість: {last.hum}%! "
                if last.light < 200:   alert += f"Низька освітленість: {last.light}! "

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
send_notification("Сервер запущено! Бот готовий надсилати сповіщення 🏠")

# === ОБРОБНИКИ КОМАНД БОТА ===

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привіт! Я бот моніторингу розумного будинку 🏠\n"
                          "Надсилаю сповіщення про небезпеку.\n"
                          "Команди:\n/start — привітання\n/status — останні дані")

@bot.message_handler(commands=['status'])
def send_status(message):
    with app.app_context():
        last = Measurement.query.order_by(Measurement.timestamp.desc()).first()
        if last:
            reply = (
                f"Останні дані з датчиків:\n\n"
                f"🌡️ Температура: {last.temp} °C\n"
                f"💧 Вологість повітря: {last.hum} %\n"
                f"☀️ Освітленість: {last.light} (raw)\n"
                f"🕒 Час: {last.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            bot.reply_to(message, reply)
        else:
            bot.reply_to(message, "Ще немає даних у базі 😔\n"
                                  "Зачекай, поки ESP32 надішле перші показники.")

@bot.message_handler(func=lambda m: True)
def echo_all(message):
    bot.reply_to(message, "Я отримав твоє повідомлення, але поки вмію тільки:\n"
                          "/start — привітання\n/status — показати дані")

# ==================================================
# Ендпоінт для даних від ESP32
@app.route('/data', methods=['POST'])
def receive_data():
    try:
        data = request.get_json(force=True)
        print(f"Отримано від ESP32: {data}")

        measurement = Measurement(
            light=int(data.get('soil', data.get('light', 0))),
            temp=float(data['temp']),
            hum=float(data['hum'])
        )

        db.session.add(measurement)
        db.session.commit()

        # Миттєве сповіщення при критичних значеннях
        if measurement.temp > 30 or measurement.hum > 70 or measurement.light < 200:
            send_notification(
                f"🚨 НЕБЕЗПЕКА!\n"
                f"Температура: {measurement.temp}°C\n"
                f"Вологість: {measurement.hum}%\n"
                f"Освітленість: {measurement.light}\n"
                f"Час: {measurement.timestamp.strftime('%H:%M:%S')}"
            )

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"Помилка обробки даних: {e}")
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
# === Керування пристроями через бот ===
ESP_IP = "192.168.1.107"  # Заміни на актуальну IP-адресу твого ESP32 (можна зробити змінною)

@bot.message_handler(commands=['led_on', 'led_off'])
def control_led(message):
    command = message.text[1:]  # led_on або led_off
    user_id = message.from_user.id

    if user_id != CHAT_ID:
        bot.reply_to(message, "Доступ заборонено! Тільки власник може керувати.")
        return

    user_state[user_id] = {'command': command, 'waiting_code': True}
    bot.reply_to(message, "Введи секретний код для керування пристроями:")

@bot.message_handler(func=lambda m: True)
def handle_code_or_text(message):
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
                import requests
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    bot.reply_to(message, f"Світлодіод {action} успішно! 💡")
                else:
                    bot.reply_to(message, f"Помилка: ESP32 відповів {response.status_code}")
            except Exception as e:
                bot.reply_to(message, f"Не вдалося підключитися до ESP32: {str(e)}")

            del user_state[user_id]
        else:
            bot.reply_to(message, "Неправильний код! Спробуй ще раз.")
    else:
        # Якщо не код — звичайна відповідь
        bot.reply_to(message, "Напиши /start або /status")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
