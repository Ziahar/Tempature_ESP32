from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import telebot
import threading
import time

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Ініціалізація бази даних
db = SQLAlchemy(app)

# Модель даних (тепер прямо в app.py, щоб не було проблем з імпортом)
class Measurement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    light = db.Column(db.Integer, nullable=False)   # освітленість (було soil)
    temp = db.Column(db.Float, nullable=False)
    hum = db.Column(db.Float, nullable=False)

    def to_dict(self):
        return {
            "timestamp": self.timestamp.isoformat(),
            "light": self.light,
            "temp": round(self.temp, 1),
            "hum": round(self.hum, 1)
        }

# Створюємо таблиці при першому запуску
with app.app_context():
    db.create_all()

# === НАЛАШТУВАННЯ TELEGRAM БОТА ===
TELEGRAM_TOKEN = '8561971309:AAG7dKvFlGYO5weT42p9OBdCD5ZkbyL2daQ'
CHAT_ID = '1481541168'  # ← це виглядає як chat_id бота, а не твій особистий!
                        # Заміни на СВІЙ chat_id (наприклад 123456789)
                        # Як дізнатися: надішли повідомлення боту і подивись в @userinfobot або @getidsbot

bot = telebot.TeleBot(TELEGRAM_TOKEN)

def send_notification(message):
    try:
        bot.send_message(CHAT_ID, message)
        print(f"[Telegram] Надіслано: {message}")
    except Exception as e:
        print(f"[Telegram] Помилка надсилання: {e}")

# Фонова перевірка останніх даних кожні 60 секунд
def check_alerts():
    while True:
        with app.app_context():
            last = Measurement.query.order_by(Measurement.timestamp.desc()).first()
            if last:
                temp = last.temp
                hum = last.hum
                light = last.light

                alert = ""
                if temp > 30:     alert += f"Висока температура: {temp}°C! "
                if hum > 70:      alert += f"Висока вологість: {hum}%! "
                if light < 200:   alert += f"Низька освітленість: {light}! "

                if alert:
                    send_notification(f"⚠️ Сповіщення!\n{alert}\nЧас: {last.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")

        time.sleep(60)

# Запускаємо перевірку в окремому потоці
threading.Thread(target=check_alerts, daemon=True).start()

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
                f"T: {measurement.temp}°C\n"
                f"H: {measurement.hum}%\n"
                f"Світло: {measurement.light}\n"
                f"Час: {measurement.timestamp.strftime('%H:%M:%S')}"
            )

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"Помилка обробки даних: {e}")
        return jsonify({"error": str(e)}), 400

# Головна сторінка з графіками
@app.route('/')
def index():
    return render_template('index.html')

# API для графіків
@app.route('/api/data')
def api_data():
    limit = request.args.get('limit', 1000, type=int)
    measurements = Measurement.query.order_by(Measurement.timestamp.desc()).limit(limit).all()
    measurements.reverse()
    return jsonify([m.to_dict() for m in measurements])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
