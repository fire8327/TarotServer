from flask import Flask, jsonify

app = Flask(__name__)

# Твои пакеты — копия из бота
PACKAGES = {
    "pack_1": {"name": "1 расклад", "price_stars": 75, "readings": 1},
    "pack_5": {"name": "5 раскладов", "price_stars": 250, "readings": 5},
    "pack_30": {"name": "Подписка на месяц (30 шт.)", "price_stars": 500, "readings": 30},
}

@app.route('/invoice/<pack_id>')
def get_invoice(pack_id):
    if pack_id not in PACKAGES:
        return jsonify({"error": "Invalid pack"}), 400

    pack = PACKAGES[pack_id]
    return jsonify({
        "title": f"🔮 {pack['name']}",
        "description": f"Ты получаешь {pack['readings']} раскладов. Магия уже зовёт!",
        "payload": pack_id,  # важно — для идентификации в боте
        "currency": "XTR",   # Telegram Stars
        "prices": [{"label": "Расклады", "amount": pack['price_stars']}]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
