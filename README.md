# 🦽 Assisto — Smart Wheelchair Monitoring System

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-blue?style=for-the-badge&logo=python" alt="Python">
  <img src="https://img.shields.io/badge/Flask-2.x-black?style=for-the-badge&logo=flask" alt="Flask">
  <img src="https://img.shields.io/badge/SocketIO-realtime-green?style=for-the-badge&logo=socket.io" alt="SocketIO">
  <img src="https://img.shields.io/badge/ESP32-IoT-red?style=for-the-badge&logo=espressif" alt="ESP32">
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="License">
</p>

**Assisto** is a real-time smart wheelchair monitoring web application built with Flask and WebSockets. It bridges an ESP32-based wheelchair device to a live web dashboard — tracking location, health vitals, fall detection, and sending instant alerts, all from a beautiful, responsive interface.

---

## ✨ Features

| Feature                       | Description                                                                            |
| ----------------------------- | -------------------------------------------------------------------------------------- |
| 🗺️ **Live GPS Tracking**      | Real-time map view of the wheelchair's location using Leaflet.js                       |
| ❤️ **Health Vitals**          | Continuous heart rate monitoring with historical charts                                |
| ⚠️ **Fall Detection**         | Automatic alert generation when a fall event is detected by the ESP32                  |
| 🔔 **Alert Center**           | Severity-based log of all critical and warning events                                  |
| 📋 **Trip History**           | Per-session trip logs with average heart rate and duration                             |
| 🔌 **ESP32 WebSocket Bridge** | Server-initiated connection to any ESP32 by IP — no port-forwarding required           |
| 📡 **Device Simulator**       | Built-in `wheelchair.py` WebSocket server to simulate a real device during development |
| 🔐 **User Authentication**    | Secure login, registration, and per-user device binding                                |
| ⚙️ **Configuration**          | Register and name your wheelchair device, bound to your user account                   |

---

## 🖥️ Dashboard Preview

> The command center provides a unified view of live vitals, device status, and recent history in one glance.

---

## 🏗️ Architecture

```
Browser (Socket.IO Client)
        │
        ▼
Flask + Socket.IO Server  ◄──── WebSocket Bridge ────►  ESP32 / Simulator
        │
        ▼
   SQLite Database
   (users, wheelchairs, trips, sensor_data, alerts)
```

The Flask server acts as a **proxy/bridge**: it initiates a raw WebSocket connection to the ESP32 using the IP address provided by the user, then relays data bidirectionally between the ESP32 and all connected browser clients via Socket.IO.

---

## 🗂️ Project Structure

```
assisto-flask/
├── app.py                  # Main Flask application (routes, SocketIO events, ESP32 bridge)
├── wheelchair.py           # ESP32 device simulator (WebSocket server)
├── requirements.txt        # Python dependencies
├── assisto.db              # SQLite database (auto-created on first run)
├── static/
│   ├── css/                # Stylesheets
│   ├── js/                 # Client-side JavaScript
│   └── images/             # Static images/assets
└── templates/
    ├── base.html           # Base layout with sidebar navigation
    ├── login.html          # Login page
    ├── register.html       # Registration page
    ├── command_center.html # Main dashboard (vitals + live data)
    ├── live_tracking.html  # Real-time GPS map
    ├── health_vitals.html  # Heart rate history charts
    ├── alerts.html         # Alert log
    ├── trip_history.html   # Trip session log
    └── configuration.html  # Device pairing settings
```

---

## ⚙️ Tech Stack

- **Backend**: Python 3, Flask, Flask-SocketIO, Eventlet
- **Database**: SQLite 3 (via Python's built-in `sqlite3`)
- **Authentication**: Flask-Login, Werkzeug password hashing
- **Real-time**: Socket.IO (server) + WebSocket client (`websocket-client`)
- **Frontend**: Jinja2 templates, Vanilla JS, Leaflet.js (maps), Chart.js (vitals)
- **IoT Device**: ESP32 (or the included Python simulator)

---

## 🚀 Getting Started

### Prerequisites

- Python 3.8 or higher
- `pip` package manager
- (Optional) An ESP32 device running the Assisto firmware

### 1. Clone the repository

```bash
git clone https://github.com/<your-username>/assisto-flask.git
cd assisto-flask
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the application

```bash
python app.py
```

The server will start at **http://0.0.0.0:5000**. Open your browser and navigate to `http://localhost:5000`.

> The SQLite database (`assisto.db`) is created automatically on the first run.

---

## 🤖 Running the Device Simulator

If you don't have a physical ESP32, you can use the included simulator. It runs a WebSocket server that broadcasts fake sensor data (heart rate, GPS location, and random fall events).

Open a **second terminal** and run:

```bash
python wheelchair.py
```

The simulator starts on `ws://0.0.0.0:8081`.

Then in the Assisto web dashboard, go to the **Command Center** → enter `localhost:8081` (or `127.0.0.1:8081`) in the device IP field and click **Connect**.

---

## 📡 Connecting a Real ESP32

1. Flash your ESP32 with firmware that broadcasts data over a WebSocket server on port `81` (default).
2. Ensure the ESP32 and the machine running Assisto are on the same network.
3. In the Assisto dashboard → Command Center → enter the ESP32's local IP address and click **Connect**.

The server will initiate the WebSocket connection and start streaming data to your browser in real time.

### Data Protocol

The ESP32 should send plain-text messages in the `key:value` format:

| Message                    | Description                    |
| -------------------------- | ------------------------------ |
| `heartrate:75`             | Heart rate in BPM              |
| `location:10.9348,76.0022` | GPS coordinates (lat,lng)      |
| `fall:detected`            | Triggers a CRITICAL fall alert |
| `status:-60,192.168.1.100` | Signal strength & device IP    |

Commands sent **from** the browser to the ESP32:

| Command             | Description             |
| ------------------- | ----------------------- |
| `emergency:stop`    | Activate emergency stop |
| `emergency:release` | Release emergency stop  |
| `command:<cmd>`     | Custom command string   |

---

## 🗄️ Database Schema

```sql
users         (id, username, email, password, created_at)
wheelchairs   (id, unique_id, user_id, name, registered_at)
trips         (id, wheelchair_id, start_time, end_time)
sensor_data   (id, trip_id, timestamp, lat, lng, speed, heart_rate, fall_detected, fall_confidence)
alerts        (id, wheelchair_id, timestamp, type, message, severity)
```

---

## 🌐 API Endpoints

### REST API

| Method | Endpoint          | Description                           |
| ------ | ----------------- | ------------------------------------- |
| `POST` | `/api/start_trip` | Start a new trip session for a device |
| `POST` | `/api/end_trip`   | End the active trip session           |

### Socket.IO Events

| Event (Client → Server) | Description                                   |
| ----------------------- | --------------------------------------------- |
| `toggle_bridge`         | Start/stop the ESP32 WebSocket bridge         |
| `web_command`           | Send a command string to the ESP32            |
| `device_data`           | Send sensor data directly (simulator/testing) |

| Event (Server → Client) | Description                                           |
| ----------------------- | ----------------------------------------------------- |
| `esp_data`              | Raw sensor data string from the ESP32                 |
| `device_status`         | Bridge connection status (`connected`/`disconnected`) |
| `device_command`        | Command echo (for local testing)                      |

---

## 🚢 Deployment

### Running as a systemd Service (Linux)

Create a service file at `/etc/systemd/system/assisto.service`:

```ini
[Unit]
Description=Assisto Smart Wheelchair Server
After=network.target

[Service]
User=<your-user>
WorkingDirectory=/path/to/assisto-flask
ExecStart=/path/to/assisto-flask/venv/bin/python app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable assisto
sudo systemctl start assisto
```

### Production Notes

- Change `app.secret_key` in `app.py` to a strong, random secret before deploying.
- Run behind a reverse proxy (e.g., **Nginx**) with SSL for HTTPS support.
- Eventlet is used as the WSGI server — it handles WebSocket and async tasks natively.
- For production builds, consider using **Gunicorn + Eventlet workers**.

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome!

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m 'Add some feature'`
4. Push to the branch: `git push origin feature/your-feature`
5. Open a Pull Request

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

<p align="center">Made with ❤️ for accessibility and smart mobility</p>
