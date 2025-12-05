from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Measurement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    light = db.Column(db.Integer, nullable=False)    # тепер це освітленість (замість soil)
    temp = db.Column(db.Float, nullable=False)
    hum = db.Column(db.Float, nullable=False)

    def to_dict(self):
        return {
            "timestamp": self.timestamp.isoformat(),
            "light": self.light,
            "temp": round(self.temp, 1),   # 1 знак після коми
            "hum": round(self.hum, 1)
        }
