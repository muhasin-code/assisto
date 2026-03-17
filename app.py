import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime
import socket as sock_module
import websocket
import time

app = Flask(__name__)
app.secret_key = 'assisto-super-secret-2025'  # Change in production

# ─── SocketIO ─────────────────────────────────
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ====================== USER MODEL ======================
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect('assisto.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, username FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return User(user[0], user[1]) if user else None

# ====================== DATABASE ======================
def init_db():
    conn = sqlite3.connect('assisto.db')
    cursor = conn.cursor()

    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS wheelchairs (
            id INTEGER PRIMARY KEY,
            unique_id TEXT UNIQUE NOT NULL,
            user_id INTEGER,
            name TEXT,
            registered_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY,
            wheelchair_id INTEGER,
            start_time TEXT,
            end_time TEXT,
            FOREIGN KEY (wheelchair_id) REFERENCES wheelchairs(id)
        );

        CREATE TABLE IF NOT EXISTS sensor_data (
            id INTEGER PRIMARY KEY,
            trip_id INTEGER,
            timestamp TEXT,
            lat REAL,
            lng REAL,
            speed REAL DEFAULT 0.0,
            heart_rate INTEGER,
            fall_detected INTEGER DEFAULT 0,
            fall_confidence REAL DEFAULT 0.0,
            FOREIGN KEY (trip_id) REFERENCES trips(id)
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY,
            wheelchair_id INTEGER,
            timestamp TEXT,
            type TEXT,
            message TEXT,
            severity TEXT,
            FOREIGN KEY (wheelchair_id) REFERENCES wheelchairs(id)
        );
    ''')
    conn.commit()
    conn.close()

init_db()

# ====================== HELPERS ======================
def get_user_wheelchair(user_id):
    conn = sqlite3.connect('assisto.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, unique_id, name FROM wheelchairs WHERE user_id = ? LIMIT 1", (user_id,))
    wc = cursor.fetchone()
    conn.close()
    return wc

def get_or_create_active_trip(wc_id):
    """Returns the active trip_id for a wheelchair, creating one if none exists."""
    conn = sqlite3.connect('assisto.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM trips WHERE wheelchair_id = ? AND end_time IS NULL ORDER BY id DESC LIMIT 1", (wc_id,))
    trip = cursor.fetchone()
    if trip:
        trip_id = trip[0]
    else:
        cursor.execute("INSERT INTO trips (wheelchair_id, start_time) VALUES (?, ?)", (wc_id, datetime.now().isoformat()))
        trip_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return trip_id

# ====================== AUTH ROUTES ======================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        wheelchair_id = request.form['wheelchair_id']
        
        try:
            conn = sqlite3.connect('assisto.db')
            cursor = conn.cursor()
            
            cursor.execute("SELECT id FROM wheelchairs WHERE unique_id = ?", (wheelchair_id,))
            if cursor.fetchone():
                flash('This Wheelchair ID is already registered.', 'danger')
                conn.close()
                return render_template('register.html')

            cursor.execute("INSERT INTO users (username, email, password, created_at) VALUES (?, ?, ?, ?)",
                           (username, email, password, datetime.now().isoformat()))
            user_id = cursor.lastrowid
            
            cursor.execute("INSERT INTO wheelchairs (unique_id, user_id, name, registered_at) VALUES (?, ?, ?, ?)",
                           (wheelchair_id, user_id, f"{username}'s Wheelchair", datetime.now().isoformat()))
            
            conn.commit()
            flash('Registration successful! Your wheelchair is bound to your account.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username or email already taken.', 'danger')
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect('assisto.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id, password FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        conn.close()
        if user and check_password_hash(user[1], password):
            login_user(User(user[0], username))
            return redirect(url_for('command_center'))
        flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ====================== MAIN PAGES ======================
@app.route('/')
@login_required
def overview():
    return redirect(url_for('command_center'))

@app.route('/live_tracking')
@login_required
def live_tracking():
    return render_template('live_tracking.html')

@app.route('/command_center')
@login_required
def command_center():
    wc = get_user_wheelchair(current_user.id)
    if not wc:
        return redirect(url_for('configuration'))
    
    conn = sqlite3.connect('assisto.db')
    cursor = conn.cursor()
    # Get recent history for the unified view
    cursor.execute('''
        SELECT sd.* FROM sensor_data sd
        JOIN trips t ON sd.trip_id = t.id
        WHERE t.wheelchair_id = ?
        ORDER BY sd.timestamp DESC LIMIT 5
    ''', (wc[0],))
    recent_history = cursor.fetchall()
    
    # Get vital history for charts if needed
    cursor.execute('''
        SELECT sd.timestamp, sd.heart_rate 
        FROM sensor_data sd
        JOIN trips t ON sd.trip_id = t.id
        WHERE t.wheelchair_id = ? AND t.end_time IS NULL
        ORDER BY sd.timestamp DESC LIMIT 30
    ''', (wc[0],))
    vital_history = cursor.fetchall()
    conn.close()
    
    vital_history.reverse()
    return render_template('command_center.html', wheelchair=wc, recent_history=recent_history, vital_history=vital_history)

@app.route('/health_vitals')
@login_required
def health_vitals():
    wc = get_user_wheelchair(current_user.id)
    if not wc:
        return redirect(url_for('configuration'))
    
    conn = sqlite3.connect('assisto.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT sd.timestamp, sd.heart_rate 
        FROM sensor_data sd
        JOIN trips t ON sd.trip_id = t.id
        WHERE t.wheelchair_id = ? AND t.end_time IS NULL
        ORDER BY sd.timestamp DESC LIMIT 30
    ''', (wc[0],))
    history = cursor.fetchall()
    conn.close()
    history.reverse()
    return render_template('health_vitals.html', wheelchair=wc, history=history)

@app.route('/trip_history')
@login_required
def trip_history():
    wc = get_user_wheelchair(current_user.id)
    conn = sqlite3.connect('assisto.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT t.id, t.start_time, t.end_time, 
               COUNT(sd.id) as data_count,
               ROUND(AVG(sd.heart_rate), 1) as avg_hr
        FROM trips t 
        LEFT JOIN sensor_data sd ON sd.trip_id = t.id
        WHERE t.wheelchair_id = ?
        GROUP BY t.id
        ORDER BY t.start_time DESC
    ''', (wc[0],))
    trips = cursor.fetchall()
    conn.close()
    return render_template('trip_history.html', trips=trips, wheelchair=wc)

@app.route('/configuration', methods=['GET', 'POST'])
@login_required
def configuration():
    conn = sqlite3.connect('assisto.db')
    cursor = conn.cursor()
    
    if request.method == 'POST':
        name = request.form.get('name')
        
        cursor.execute("SELECT id FROM wheelchairs WHERE user_id = ?", (current_user.id,))
        wc = cursor.fetchone()
        
        if wc:
            cursor.execute("UPDATE wheelchairs SET name = ? WHERE user_id = ?",
                           (name, current_user.id))
            conn.commit()
            flash('Configuration updated successfully!', 'success')
        else:
            unique_id = request.form.get('unique_id')
            if unique_id:
                try:
                    cursor.execute("INSERT INTO wheelchairs (unique_id, user_id, name, registered_at) VALUES (?, ?, ?, ?)",
                                   (unique_id, current_user.id, name, datetime.now().isoformat()))
                    conn.commit()
                    flash('Wheelchair registered successfully!', 'success')
                except sqlite3.IntegrityError:
                    flash('This Unique ID is already registered.', 'danger')
            else:
                flash('Please provide a Unique ID if not already bound.', 'warning')
                
    cursor.execute("SELECT * FROM wheelchairs WHERE user_id = ?", (current_user.id,))
    wheelchairs = cursor.fetchall()
    conn.close()
    return render_template('configuration.html', wheelchairs=wheelchairs)

@app.route('/alerts')
@login_required
def alerts_page():
    wc = get_user_wheelchair(current_user.id)
    if not wc:
        return redirect(url_for('configuration'))
    
    conn = sqlite3.connect('assisto.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM alerts WHERE wheelchair_id = ? ORDER BY timestamp DESC", (wc[0],))
    alerts_list = cursor.fetchall()
    conn.close()
    return render_template('alerts.html', alerts=alerts_list, wheelchair=wc)

# ====================== TRIP REST API (kept for simulator) ======================
@app.route('/api/start_trip', methods=['POST'])
def start_trip():
    device_id = request.json.get('device_id')
    conn = sqlite3.connect('assisto.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM wheelchairs WHERE unique_id = ?", (device_id,))
    wc = cursor.fetchone()
    if not wc:
        conn.close()
        return jsonify({'status': 'error', 'message': 'Wheelchair not found'}), 404
    wc_id = wc[0]
    cursor.execute("SELECT id FROM trips WHERE wheelchair_id = ? AND end_time IS NULL", (wc_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO trips (wheelchair_id, start_time) VALUES (?, ?)",
                       (wc_id, datetime.now().isoformat()))
        conn.commit()
    conn.close()
    return jsonify({'status': 'success'})

@app.route('/api/end_trip', methods=['POST'])
def end_trip():
    device_id = request.json.get('device_id')
    conn = sqlite3.connect('assisto.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM wheelchairs WHERE unique_id = ?", (device_id,))
    wc = cursor.fetchone()
    if wc:
        cursor.execute("UPDATE trips SET end_time = ? WHERE wheelchair_id = ? AND end_time IS NULL",
                       (datetime.now().isoformat(), wc[0]))
        conn.commit()

# ─── ESP32 Bridge State ──────────────────────

esp_ws = None
esp_ip = None
bridge_active = False
bridge_thread = None

def esp_bridge_worker(target_ip, wc_id):
    global esp_ws, bridge_active

    # Normalize: strip ws:// or wss:// if user pasted full URL
    target = target_ip.strip()
    if target.startswith('ws://'):
        target = target[5:]
    elif target.startswith('wss://'):
        target = target[6:]

    # Build URL: host:port -> ws://host:port, else ws://host:81
    if ':' in target:
        ws_url = f"ws://{target}"
    else:
        ws_url = f"ws://{target}:81"
    
    while bridge_active:
        try:
            print(f"[Bridge] Connecting to {ws_url}...")
            esp_ws = websocket.create_connection(ws_url, timeout=5)
            with app.app_context():
                socketio.emit('device_status', {'status': 'connected', 'ip': target_ip})
            eventlet.sleep(0)  # yield so eventlet can flush the emit to clients
            print(f"[Bridge] Connected to {target_ip}")
            esp_ws.settimeout(1.0)  # allow recv to yield so we can respond to disconnect

            while bridge_active:
                try:
                    msg = esp_ws.recv()
                except (sock_module.timeout, TimeoutError):
                    continue  # no data yet, check bridge_active on next loop
                except Exception:
                    break  # connection closed or error
                if not msg:
                    break
                
                print(f"[Bridge] Received from ESP: {msg}")
                # Forward to browser and save with attribution
                handle_device_data_internal(msg, wc_id)
                
        except Exception as e:
            error_msg = str(e)
            print(f"[Bridge] Error: {error_msg}")
            with app.app_context():
                socketio.emit('device_status', {'status': 'disconnected', 'error': error_msg})
            if bridge_active:
                time.sleep(3) # Retry delay
            else:
                break
        finally:
            if esp_ws:
                try: esp_ws.close()
                except: pass
                esp_ws = None

# ═══════════════════════════════════════════════════════════════════
#   WEBSOCKET EVENTS  —  Proxy & Command logic
# ═══════════════════════════════════════════════════════════════════

@socketio.on('toggle_bridge')
def handle_toggle_bridge(data):
    global bridge_active, bridge_thread, esp_ip
    
    action = data.get('action') # 'start' or 'stop'
    ip = data.get('ip')
    
    if action == 'start' and ip:
        if not bridge_active:
            wc = get_user_wheelchair(current_user.id)
            if not wc:
                socketio.emit('device_status', {'status': 'disconnected', 'error': 'No wheelchair bound to account'})
                return
                
            esp_ip = ip
            bridge_active = True
            bridge_thread = socketio.start_background_task(esp_bridge_worker, ip, wc[0])
            print(f"[WS] Bridge started for IP: {ip} for WC: {wc[0]}")
    else:
        bridge_active = False
        if esp_ws:
            try:
                esp_ws.close()
            except Exception:
                pass
        socketio.emit('device_status', {'status': 'disconnected'})
        print("[WS] Bridge stopping...")

@socketio.on('web_command')
def handle_web_command(data):
    """
    Receives key:value command strings from the browser.
    Forwards them over the raw WebSocket connection to the ESP32.
    """
    msg = str(data)
    print(f"[WS web_command] {msg}")
    
    # Bridge forward (Proxy mode)
    if esp_ws:
        try:
            esp_ws.send(msg)
            print(f"[Bridge] Forwarded to ESP: {msg}")
        except Exception as e:
            print(f"[Bridge] Send error: {e}")
    
    # Keep legacy broadcast for internal sim testing
    socketio.emit('device_command', msg)

# ─── Device → Server Handlers ───
@socketio.on('device_data')
def handle_device_data(data):
    """Legacy/Public handler for direct SocketIO data from device/browser."""
    wc = get_user_wheelchair(current_user.id)
    wc_id = wc[0] if wc else None
    handle_device_data_internal(data, wc_id)

def handle_device_data_internal(data, wc_id=None):
    """
    Core data processor. 
    Accepts data string and optional target wc_id.
    """
    msg = str(data)
    # Broadcast to browsers
    with app.app_context():
        socketio.emit('esp_data', msg)
    eventlet.sleep(0)
    
    # Parse and save to DB
    if ':' not in msg: return
    key, value = msg.split(':', 1)
    
    # If no wc_id provided and no current_user, we can't save
    if not wc_id:
        # Fallback to current_user if called in a request context
        try:
            wc = get_user_wheelchair(current_user.id)
            if wc: wc_id = wc[0]
        except: pass
        
    if not wc_id:
        print(f"[Data] Dropping message (no WC attribution): {msg}")
        return

    conn = sqlite3.connect('assisto.db')
    cursor = conn.cursor()

    if key == 'heartrate':
        try:
            bpm = int(value)
            trip_id = get_or_create_active_trip(wc_id)
            cursor.execute('INSERT INTO sensor_data (trip_id, timestamp, heart_rate, fall_detected) VALUES (?, ?, ?, 0)', 
                           (trip_id, datetime.now().isoformat(), bpm))
            if bpm > 100:
                cursor.execute('INSERT INTO alerts (wheelchair_id, timestamp, type, message, severity) VALUES (?, ?, ?, ?, ?)', 
                               (wc_id, datetime.now().isoformat(), 'HIGH_HR', f'High heart rate detected: {bpm} BPM', 'WARNING'))
            conn.commit()
        except: pass
    elif key == 'location':
        try:
            parts = value.split(',')
            lat, lng = float(parts[0]), float(parts[1])
            trip_id = get_or_create_active_trip(wc_id)
            cursor.execute('UPDATE sensor_data SET lat = ?, lng = ? WHERE trip_id = ? AND id = (SELECT id FROM sensor_data WHERE trip_id = ? ORDER BY id DESC LIMIT 1)', 
                           (lat, lng, trip_id, trip_id))
            conn.commit()
        except: pass
    elif key == 'fall' and value == 'detected':
        trip_id = get_or_create_active_trip(wc_id)
        cursor.execute('INSERT INTO sensor_data (trip_id, timestamp, fall_detected, fall_confidence) VALUES (?, ?, 1, 0.97)', (trip_id, datetime.now().isoformat()))
        cursor.execute('INSERT INTO alerts (wheelchair_id, timestamp, type, message, severity) VALUES (?, ?, ?, ?, ?)', (wc_id, datetime.now().isoformat(), 'FALL', 'Possible fall detected!', 'CRITICAL'))
        conn.commit()
    conn.close()


# ─── Connection lifecycle ────────────────────────────────────────────
@socketio.on('connect')
def handle_connect():
    global bridge_active, esp_ws, esp_ip
    print(f"[WS] Client connected: {request.sid}")
    # Send current bridge status so new clients see correct state (e.g. page refresh while bridge is up)
    if bridge_active and esp_ws:
        emit('device_status', {'status': 'connected', 'ip': esp_ip or 'Connected'})

@socketio.on('disconnect')
def handle_disconnect():
    print(f"[WS] Client disconnected: {request.sid}")


# ═══════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)