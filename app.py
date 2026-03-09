from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import telebot
import threading
import time
import matplotlib.pyplot as plt
import io
from matplotlib.dates import DateFormatter
from zoneinfo import ZoneInfo

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

bot = telebot.TeleBot(TELEGRAM_TOKEN)

KYIV_TZ = ZoneInfo("Europe/Kyiv")

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
                if last.temp > 28:
                    send_notification(f"🌡️ У будинку жарко: {last.temp}°C!\n"
                                      f"Рекомендую увімкнути вентилятор для комфортної температури.")
                if last.gas:
                    send_notification("🚨 Виявлено газ/дим!\nВідчиніть вікно та викличіть 104!")
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
    bot.reply_to(message, "Привіт! Це бот моніторингу розумного будинку 🏠\n"
                          "Я надсилаю сповіщення про температуру та газ/дим.\n\n"
                          "Команди:\n"
                          "/start — привітання\n"
                          "/status — останні дані\n"
                          "/history [дата] HH:MM HH:MM — графік за період\n\n"
                          "Приклади:\n/history 15:00 16:00\n/history 2025-03-01 10:00 12:00")

@bot.message_handler(commands=['status'])
def send_status(message):
    with app.app_context():
        last = Measurement.query.order_by(Measurement.timestamp.desc()).first()
        if last:
            local_time = last.timestamp.astimezone(KYIV_TZ)
            reply = (
                f"Останні дані з датчиків:\n\n"
                f"🌡️ Температура: {last.temp} °C\n"
                f"💧 Вологість повітря: {last.hum} %\n"
                f"☀️ Освітленість: {last.light} (raw)\n"
                f"🔥 Газ: {'Так' if last.gas else 'Ні'}\n"
                f"🚶 Рух: {'Так' if last.motion else 'Ні'}\n"
                f"🕒 Час (Київ): {local_time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            bot.reply_to(message, reply)
        else:
            bot.reply_to(message, "Ще немає даних у базі 😔\n"
                                  "Зачекай, поки датчики надішлють перші показники.")

@bot.message_handler(commands=['history'])
def send_history(message):
    args = message.text.split()[1:]
    if len(args) not in (2, 3):
        bot.reply_to(message, "Формат:\n/history HH:MM HH:MM\nабо\n/history YYYY-MM-DD HH:MM HH:MM\nПриклад:\n/history 15:00 16:00")
        return
    try:
        kyiv_tz = ZoneInfo("Europe/Kyiv")
        today = datetime.now(kyiv_tz).strftime("%Y-%m-%d")
        
        if len(args) == 2:
            date_str = today
            start_str, end_str = args
        else:
            date_str = args[0]
            start_str, end_str = args[1], args[2]

        start_str = f"{date_str} {start_str}:00"
        end_str   = f"{date_str} {end_str}:59"

        start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=kyiv_tz)
        end_dt   = datetime.strptime(end_str,   "%Y-%m-%d %H:%M:%S").replace(tzinfo=kyiv_tz)

        start_utc = start_dt.astimezone(ZoneInfo("UTC"))
        end_utc   = end_dt.astimezone(ZoneInfo("UTC"))

        with app.app_context():
            records = Measurement.query.filter(
                Measurement.timestamp >= start_utc,
                Measurement.timestamp <= end_utc
            ).order_by(Measurement.timestamp.asc()).all()

            if not records:
                bot.reply_to(message, f"За період {start_str.split()[-1]}–{end_str.split()[-1]} ({date_str}) даних немає.")
                return

            times = [r.timestamp.astimezone(kyiv_tz) for r in records]
            temps = [r.temp for r in records]
            hums  = [r.hum for r in records]
            lights = [r.light for r in records]

            fig, ax1 = plt.subplots(figsize=(12, 7))
            ax1.set_xlabel('Час (Київ)', fontsize=12)
            ax1.set_ylabel('Температура (°C) / Вологість (%)', color='tab:blue', fontsize=12)
            ax1.plot(times, temps, color='tab:red', label='Температура', linewidth=2.5)
            ax1.plot(times, hums, color='tab:blue', label='Вологість', linewidth=2.5)
            ax1.tick_params(axis='y', labelcolor='tab:blue')
            ax1.legend(loc='upper left', fontsize=10)

            ax2 = ax1.twinx()
            ax2.set_ylabel('Освітленість (raw)', color='tab:orange', fontsize=12)
            ax2.plot(times, lights, color='tab:orange', label='Освітленість', linewidth=2.5)
            ax2.tick_params(axis='y', labelcolor='tab:orange')
            ax2.legend(loc='upper right', fontsize=10)

            fig.suptitle(f'Дані за період {date_str} {start_str.split()[-1]} – {end_str.split()[-1]}', fontsize=16)
            fig.autofmt_xdate()
            ax1.xaxis.set_major_formatter(DateFormatter('%H:%M'))
            plt.tight_layout()

            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
            buf.seek(0)
            plt.close(fig)

            bot.send_photo(message.chat.id, buf, caption=f"Графік за {date_str} {start_str.split()[-1]} – {end_str.split()[-1]}")

    except ValueError:
        bot.reply_to(message, "Неправильний формат!\nПриклад:\n/history 15:00 16:00\n/history 2025-03-01 10:00 12:00")
    except Exception as e:
        bot.reply_to(message, f"Помилка: {str(e)}")

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
