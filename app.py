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
    motion = db.Column(db.Boolean, default=False)   # PIR
    gas = db.Column(db.Boolean, default=False)      # Газ/дим

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

bot = telebot.TeleBot(TELEGRAM_TOKEN)

def send_notification(message):
    try:
        bot.send_message(CHAT_ID, message)
        print(f"[Telegram] Надіслано: {message}")
    except Exception as e:
        print(f"[Telegram] Помилка: {e}")

# Фонова перевірка (жарко)
def check_alerts():
    while True:
        with app.app_context():
            last = Measurement.query.order_by(Measurement.timestamp.desc()).first()
            if last and last.temp > 28:
                send_notification(f"🌡️ У будинку жарко: {last.temp}°C!\n"
                                  f"Рекомендую увімкнути вентилятор для комфортної температури.")
        time.sleep(60)

threading.Thread(target=check_alerts, daemon=True).start()

# Запуск polling бота
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
    bot.reply_to(message, "Привіт! Я бот моніторингу розумного будинку 🏠\n"
                          "Команди:\n"
                          "/start — привітання\n"
                          "/status — останні дані\n"
                          "/history — дані за період")

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
    # ... (той самий хороший код з попереднього повідомлення, можу додати якщо потрібно)
    bot.reply_to(message, "Функція /history тимчасово вимкнена. Скоро додаю повну підтримку.")

# ==================================================

@app.route('/data', methods=['POST'])
def receive_data():
    try:
        data = request.get_json(force=True)
        print(f"Отримано від ESP32: {data}")

        m = Measurement(
            light=int(data.get('light', data.get('soil', 0))),
            temp=float(data['temp']),
            hum=float(data['hum']),
            motion=bool(data.get('motion', False)),
            gas=bool(data.get('gas', False))
        )

        db.session.add(m)
        db.session.commit()

        # === СПОВІЩЕННЯ ===
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
