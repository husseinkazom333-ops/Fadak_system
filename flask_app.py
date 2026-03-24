from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import requests
import base64
import json
import os
import sqlite3
import time
import traceback

app = Flask(__name__)
CORS(app) 

# معلومات التليكرام
TELEGRAM_BOT_TOKEN = "8636256430:AAGOR9GTpPj4DozwbdyF9177NAcWCd_KoPM"
TELEGRAM_CHAT_ID = "161011809"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "database.db") 

# 🌟 دالة الاتصال السحرية (التي تمنع القفل وتتحمل الضغط العالي) 🌟
def get_db_conn():
    # timeout=30 يخلي السيرفر ينتظر بذكاء بدل ما يرفض الطلب فوراً
    conn = sqlite3.connect(DB_FILE, timeout=30)
    # تفعيل نظام WAL اللي يسمح بالقراءة والكتابة المتزامنة (نفس اللحظة)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=NORMAL;')
    return conn

def init_db():
    conn = get_db_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS app_data (key TEXT PRIMARY KEY, value TEXT)''')
    
    default_data = {
        "products": "[]", "agents": "[]", "orders": "[]", 
        "returns": "[]", "payments": "[]", "expenses": "[]",
        "employees": "[]",
        "stats": '{"sales": 0, "cash": 0, "completed": 0}',
        "db_version": str(time.time())
    }
    for k, v in default_data.items():
        c.execute("INSERT OR IGNORE INTO app_data (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()

init_db()

def load_db():
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT key, value FROM app_data")
    rows = c.fetchall()
    conn.close()
    return {row[0]: json.loads(row[1]) if row[0] != 'db_version' else row[1] for row in rows}

def save_db(key, data):
    conn = get_db_conn()
    try:
        c = conn.cursor()
        val_str = json.dumps(data, ensure_ascii=False)
        # استخدام REPLACE لتسريع التحديثات وتجنب الأخطاء
        c.execute("INSERT OR REPLACE INTO app_data (key, value) VALUES (?, ?)", (key, val_str))
        c.execute("INSERT OR REPLACE INTO app_data (key, value) VALUES (?, ?)", ("db_version", str(time.time())))
        conn.commit()
    finally:
        conn.close()

def send_telegram_text(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try: requests.post(url, json=payload, timeout=5)
    except: pass

def send_telegram_photo(caption, b64_img):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        if "," in b64_img: b64_img = b64_img.split(",")[1]
        img_bytes = base64.b64decode(b64_img)
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"}, files={"photo": ("image.jpg", img_bytes, "image/jpeg")}, timeout=10)
    except:
        send_telegram_text(caption)

@app.route('/api/employee_login', methods=['POST'])
def employee_login():
    try:
        req = request.json
        username = str(req.get('username', '')).strip()
        password = str(req.get('password', '')).strip()
        
        db = load_db()
        employees = db.get('employees', [])
        
        if not employees or len(employees) == 0:
            employees = [{"id": 1, "name": "المدير العام", "username": "admin", "password": "123", "role": "admin"}]
            save_db('employees', employees)
            
        user = next((e for e in employees if str(e.get('username')) == username and str(e.get('password')) == password), None)
        
        if user: return jsonify({"status": "success", "user": user})
        return jsonify({"status": "error", "message": "اسم المستخدم أو كلمة المرور غير صحيحة"}), 401
    except Exception as e:
        return jsonify({"status": "error", "message": f"خطأ سيرفر: {str(e)}"}), 500

@app.route('/api/check_update', methods=['GET'])
def check_update():
    conn = get_db_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM app_data WHERE key = 'db_version'")
    row = c.fetchone()
    version = row[0] if row else ""
    conn.close()
    return jsonify({"version": version})

@app.route('/api/agent_login', methods=['POST'])
def agent_login():
    try:
        code = str(request.json.get('code', '')).strip()
        db = load_db()
        agents = db.get('agents', [])
        agent = next((a for a in agents if str(a.get('code', '')).strip() == code), None)
        if agent:
            agent_orders = [o for o in db.get('orders', []) if str(o.get('agentId')) == str(agent.get('id'))]
            agent_payments = [p for p in db.get('payments', []) if str(p.get('agentId')) == str(agent.get('id'))]
            return jsonify({"status": "success", "agent": agent, "products": db.get('products', []), "orders": agent_orders, "payments": agent_payments})
        return jsonify({"status": "error", "message": "الرمز غير صحيح"}), 401
    except Exception as e:
        return jsonify({"status": "error", "message": f"خطأ سيرفر: {str(e)}"}), 500

@app.route('/api/db', methods=['GET'])
def get_db():
    resp = make_response(jsonify(load_db()))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '-1'
    return resp

@app.route('/api/update', methods=['POST'])
def update_db():
    try:
        req = request.json
        if not req or 'key' not in req or 'data' not in req:
            return jsonify({"status": "error", "message": "بيانات فارغة مرسلة"}), 400
            
        save_db(req.get('key'), req.get('data'))
        
        resp = make_response(jsonify({"status": "success"}))
        resp.headers['Cache-Control'] = 'no-store, no-cache'
        return resp
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({"status": "error", "message": f"عطل في السيرفر أثناء الحفظ: {str(e)}"}), 500

@app.route('/api/submit_order', methods=['POST'])
def submit_order():
    try:
        data = request.json
        data['status'] = 'pending' 
        db = load_db()
        if 'orders' not in db: db['orders'] = []
        db['orders'].append(data)
        save_db('orders', db['orders'])
        
        msg = f"🟢 <b>طلبية جديدة رقم: {data.get('id')}</b>\n👤 <b>الوكيل:</b> {data.get('agentName')}\n📅 <b>التاريخ:</b> {data.get('date')}\n💰 <b>المبلغ الكلي:</b> {data.get('total'):,} د.ع\n\n📦 <b>المواد المطلوبة:</b>\n"
        items = data.get('items', [])
        b64_img = items[0].get('img') if items and len(items) > 0 else None
        for item in items: 
            req_qty = item.get('requested_qty', item.get('qty', 0))
            msg += f"▪️ {item['name']} (العدد: {req_qty})\n"
        msg += f"━━━━━━━━━━━━━━━\n⚡ <i>الرجاء فتح النظام للتجهيز.</i>"
        
        if b64_img: send_telegram_photo(msg, b64_img)
        else: send_telegram_text(msg)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/submit_return', methods=['POST'])
def submit_return():
    try:
        data = request.json
        db = load_db()
        if 'returns' not in db: db['returns'] = []
        db['returns'].append(data)
        save_db('returns', db['returns'])
        msg = f"🔴 <b>طلب إرجاع بضاعة</b>\n👤 <b>الوكيل:</b> {data.get('agentName')}\n📅 <b>التاريخ:</b> {data.get('date')}\n📦 <b>المادة:</b> {data.get('itemName')} (العدد: {data.get('qty')})\n⚠️ <b>السبب:</b> {data.get('reason')}"
        send_telegram_text(msg)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/submit_payment', methods=['POST'])
def submit_payment():
    try:
        data = request.json
        db = load_db()
        if 'payments' not in db: db['payments'] = []
        db['payments'].append(data)
        save_db('payments', db['payments'])
        msg = f"💸 <b>إشعار تسديد دين!</b>\n━━━━━━━━━━━━━━━\n👤 <b>الوكيل:</b> {data.get('agentName')}\n📅 <b>تاريخ الرفع:</b> {data.get('date')}\n💵 <b>المبلغ:</b> {data.get('amount'):,} د.ع\n📝 <b>الملاحظة:</b> {data.get('note')}\n━━━━━━━━━━━━━━━\n⚡ <i>افتح النظام للموافقة وتنزيل الدين.</i>"
        send_telegram_text(msg)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)