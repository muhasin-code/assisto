/* =============================================================================
   ESP32 Command Center — Application Logic (Socket.IO version)
   Integrated with Assisto Flask — uses Socket.IO instead of raw WebSocket
   =============================================================================
   Message format: key:value strings (same as ESP32 reference)
   - heartrate:75, location:12.97,77.59, fall:detected, fall:safe
   - message:Hello, status:-42,192.168.1.100
   - Outgoing: emergency:stop, emergency:release, command:led on
   ============================================================================= */

(function () {
    'use strict';

    if (typeof socket === 'undefined') {
        console.error('[CommandCenter] socket (Socket.IO) not found. Ensure base.html loads it.');
        return;
    }

    const s = socket;

    // ── State ──────────────────────────────────
    const state = {
        isConnected: false,
        bridgeConnected: false,
        connectTime: null,
        emergencyActive: false,
        fallDetected: false,
        heartRateHistory: [],
        hrMin: Infinity,
        hrMax: -Infinity,
        hrSum: 0,
        hrCount: 0,
        locationTrail: [],
        currentX: 0,
        currentY: 0,
        isDemoMode: false,
        demoInterval: null,
    };

    // ── DOM References ─────────────────────────
    const dom = {};
    const selectors = {
        connectionStatus: 'cc-connection-status',
        statusText: 'cc-status-text',
        clock: 'cc-clock',
        fallAlertBanner: 'cc-fall-alert-banner',
        dismissFallAlert: 'cc-dismiss-fall-alert',
        deviceStatus: 'cc-device-status',
        statusLabel: 'cc-status-label',
        uptimeValue: 'cc-uptime-value',
        signalValue: 'cc-signal-value',
        ipValue: 'cc-ip-value',
        hrValue: 'cc-hr-value',
        hrStatusBadge: 'cc-hr-status-badge',
        hrChart: 'cc-hr-chart',
        hrMin: 'cc-hr-min',
        hrAvg: 'cc-hr-avg',
        hrMax: 'cc-hr-max',
        emergencyBtn: 'btn-emergency-stop',
        emergencyReleaseBtn: 'btn-emergency-release',
        fallStatus: 'cc-fall-status',
        fallIconWrap: 'cc-fall-icon-wrap',
        fallLabel: 'cc-fall-label',
        messagesContainer: 'cc-messages-container',
        clearMessagesBtn: 'cc-clear-messages-btn',
        sendMessageInput: 'cc-send-message-input',
        sendMessageBtn: 'cc-send-message-btn',
        leafletMap: 'cc-leaflet-map',
        coordX: 'cc-coord-x',
        coordY: 'cc-coord-y',
        coordTime: 'cc-coord-time',
        wsDemoBtn: 'cc-ws-demo-btn',
        toastContainer: 'cc-toast-container',
    };

    function initDOM() {
        for (const [key, id] of Object.entries(selectors)) {
            const el = document.getElementById(id);
            if (el) dom[key] = el;
        }
        return dom.hrChart && dom.messagesContainer;
    }

    // ── Heart Rate Chart Context ───────────────
    let hrCtx = null;
    let leafletMap = null;
    let mapMarker = null;
    let mapTrailLine = null;
    const mapTrailCoords = [];

    // ── Utilities ──────────────────────────────
    function formatTime(date) {
        return date.toLocaleTimeString('en-US', { hour12: true, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    function showToast(message, type = 'info', duration = 3500) {
        const container = dom.toastContainer;
        if (!container) return;
        const icons = { success: 'fa-check-circle', error: 'fa-circle-exclamation', warning: 'fa-triangle-exclamation', info: 'fa-circle-info' };
        const toast = document.createElement('div');
        toast.className = `cc-toast toast-${type}`;
        toast.innerHTML = `<i class="fas ${icons[type] || icons.info}"></i> ${message}`;
        container.appendChild(toast);
        setTimeout(() => {
            toast.classList.add('toast-exit');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    // ── Clock ──────────────────────────────────
    function updateClock() {
        if (dom.clock) dom.clock.textContent = formatTime(new Date());
    }

    // ── Uptime Tracker ─────────────────────────
    function updateUptime() {
        if (!dom.uptimeValue) return;
        if (!state.connectTime) {
            dom.uptimeValue.textContent = '--:--:--';
            return;
        }
        const diff = Math.floor((Date.now() - state.connectTime) / 1000);
        const h = String(Math.floor(diff / 3600)).padStart(2, '0');
        const m = String(Math.floor((diff % 3600) / 60)).padStart(2, '0');
        const s = String(diff % 60).padStart(2, '0');
        dom.uptimeValue.textContent = `${h}:${m}:${s}`;
    }

    // ── Connection Status ──────────────────────
    function setOnline(ip) {
        state.isConnected = true;
        state.connectTime = Date.now();
        if (dom.connectionStatus) dom.connectionStatus.className = 'status-badge online';
        if (dom.statusText) dom.statusText.textContent = 'Online';
        if (dom.deviceStatus) dom.deviceStatus.className = 'cc-big-status online';
        if (dom.statusLabel) dom.statusLabel.textContent = 'ONLINE';
        if (dom.ipValue) dom.ipValue.textContent = ip || 'Connected';
        
        // Also update sub-status if present
        const subDot = document.getElementById('device-status-dot');
        const subLabel = document.getElementById('device-status-label');
        if (subDot) subDot.style.background = '#22c55e';
        if (subLabel) { subLabel.innerText = 'Connected'; subLabel.className = 'small text-success'; }
    }

    function setOffline() {
        state.isConnected = false;
        state.connectTime = null;
        if (dom.connectionStatus) dom.connectionStatus.className = 'status-badge offline';
        if (dom.statusText) dom.statusText.textContent = 'Offline';
        if (dom.deviceStatus) dom.deviceStatus.className = 'cc-big-status offline';
        if (dom.statusLabel) dom.statusLabel.textContent = 'OFFLINE';
        if (dom.uptimeValue) dom.uptimeValue.textContent = '--:--:--';
        if (dom.signalValue) dom.signalValue.textContent = '-- dBm';
        if (dom.ipValue) dom.ipValue.textContent = '---.---.---.---';

        // Also update sub-status if present
        const subDot = document.getElementById('device-status-dot');
        const subLabel = document.getElementById('device-status-label');
        if (subDot) subDot.style.background = '#6b7280';
        if (subLabel) { subLabel.innerText = 'Disconnected'; subLabel.className = 'small text-muted'; }
    }

    // ── Heart Rate ─────────────────────────────
    function updateHeartRate(bpm) {
        bpm = Math.round(bpm);
        if (dom.hrValue) dom.hrValue.textContent = bpm;

        if (dom.hrValue) {
            dom.hrValue.classList.remove('heartbeat-anim');
            void dom.hrValue.offsetWidth;
            dom.hrValue.classList.add('heartbeat-anim');
        }

        state.heartRateHistory.push(bpm);
        if (state.heartRateHistory.length > 80) state.heartRateHistory.shift();
        if (bpm < state.hrMin) state.hrMin = bpm;
        if (bpm > state.hrMax) state.hrMax = bpm;
        state.hrSum += bpm;
        state.hrCount++;

        if (dom.hrMin) dom.hrMin.textContent = state.hrMin === Infinity ? '--' : state.hrMin;
        if (dom.hrMax) dom.hrMax.textContent = state.hrMax === -Infinity ? '--' : state.hrMax;
        if (dom.hrAvg) dom.hrAvg.textContent = Math.round(state.hrSum / state.hrCount);

        if (dom.hrStatusBadge) {
            if (bpm > 120) {
                dom.hrStatusBadge.className = 'cc-hr-status critical';
                dom.hrStatusBadge.textContent = 'Critical';
            } else if (bpm > 100) {
                dom.hrStatusBadge.className = 'cc-hr-status elevated';
                dom.hrStatusBadge.textContent = 'Elevated';
            } else {
                dom.hrStatusBadge.className = 'cc-hr-status normal';
                dom.hrStatusBadge.textContent = 'Normal';
            }
        }

        drawHRChart();
    }

    function drawHRChart() {
        if (!dom.hrChart || !hrCtx) return;
        const canvas = dom.hrChart;
        const width = canvas.parentElement ? canvas.parentElement.clientWidth - 48 : 300;
        const height = 120;
        canvas.width = width * (window.devicePixelRatio || 1);
        canvas.height = height * (window.devicePixelRatio || 1);
        canvas.style.width = width + 'px';
        canvas.style.height = height + 'px';
        hrCtx.setTransform(1, 0, 0, 1, 0, 0);
        hrCtx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);

        hrCtx.clearRect(0, 0, width, height);

        const data = state.heartRateHistory;
        if (data.length < 2) return;

        const minVal = Math.min(...data) - 10;
        const maxVal = Math.max(...data) + 10;
        const range = maxVal - minVal || 1;

        hrCtx.strokeStyle = 'rgba(99, 102, 241, 0.06)';
        hrCtx.lineWidth = 1;
        for (let i = 0; i < 5; i++) {
            const y = (i / 4) * height;
            hrCtx.beginPath();
            hrCtx.moveTo(0, y);
            hrCtx.lineTo(width, y);
            hrCtx.stroke();
        }

        const grad = hrCtx.createLinearGradient(0, 0, 0, height);
        grad.addColorStop(0, 'rgba(244, 63, 94, 0.25)');
        grad.addColorStop(1, 'rgba(244, 63, 94, 0)');

        const step = width / (data.length - 1);
        hrCtx.beginPath();
        data.forEach((val, i) => {
            const x = i * step;
            const y = height - ((val - minVal) / range) * (height - 16) - 8;
            if (i === 0) hrCtx.moveTo(x, y);
            else hrCtx.lineTo(x, y);
        });

        hrCtx.strokeStyle = '#f43f5e';
        hrCtx.lineWidth = 2.5;
        hrCtx.lineJoin = 'round';
        hrCtx.stroke();

        hrCtx.lineTo((data.length - 1) * step, height);
        hrCtx.lineTo(0, height);
        hrCtx.closePath();
        hrCtx.fillStyle = grad;
        hrCtx.fill();

        const lastX = (data.length - 1) * step;
        const lastY = height - ((data[data.length - 1] - minVal) / range) * (height - 16) - 8;
        hrCtx.beginPath();
        hrCtx.arc(lastX, lastY, 4, 0, Math.PI * 2);
        hrCtx.fillStyle = '#f43f5e';
        hrCtx.fill();
    }

    // ── Leaflet Map ─────────────────────────────
    function initMap() {
        const mapEl = dom.leafletMap;
        if (!mapEl || !window.L) return;

        leafletMap = L.map(mapEl, {
            center: [12.9716, 77.5946],
            zoom: 16,
            zoomControl: true,
            attributionControl: true,
        });

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
            maxZoom: 19,
        }).addTo(leafletMap);

        // Ensure container is ready
        setTimeout(() => leafletMap.invalidateSize(), 500);

        const pulseIcon = L.divIcon({
            className: '',
            html: '<div class="leaflet-marker-pulse"></div>',
            iconSize: [16, 16],
            iconAnchor: [8, 8],
        });

        mapMarker = L.marker([12.9716, 77.5946], { icon: pulseIcon }).addTo(leafletMap);
        mapMarker.bindPopup('<b>ESP32 Device</b><br>Waiting for GPS data...');

        mapTrailLine = L.polyline([], {
            color: '#22d3ee',
            weight: 3,
            opacity: 0.7,
            dashArray: '8, 4',
        }).addTo(leafletMap);
    }

    function updateLocation(x, y) {
        state.currentX = x;
        state.currentY = y;

        if (dom.coordX) dom.coordX.textContent = x.toFixed(6);
        if (dom.coordY) dom.coordY.textContent = y.toFixed(6);
        if (dom.coordTime) dom.coordTime.textContent = formatTime(new Date());

        if (!leafletMap || !mapMarker) return;

        const latLng = [x, y];
        mapMarker.setLatLng(latLng);
        mapMarker.setPopupContent(`<b>ESP32 Device</b><br>Lat: ${x.toFixed(6)}<br>Lng: ${y.toFixed(6)}`);

        mapTrailCoords.push(latLng);
        if (mapTrailCoords.length > 500) mapTrailCoords.shift();
        mapTrailLine.setLatLngs(mapTrailCoords);

        leafletMap.panTo(latLng, { animate: true, duration: 0.5 });
    }

    // ── Messages ───────────────────────────────
    function addMessage(text, type = 'incoming') {
        if (!dom.messagesContainer) return;
        const placeholder = dom.messagesContainer.querySelector('.cc-message-placeholder');
        if (placeholder) placeholder.remove();

        const msg = document.createElement('div');
        msg.className = `cc-message-item ${type}`;
        const div = document.createElement('div');
        div.textContent = text;
        msg.innerHTML = `<span class="cc-message-time">${formatTime(new Date())}</span> <span class="cc-message-text">${div.innerHTML}</span>`;
        dom.messagesContainer.appendChild(msg);
        dom.messagesContainer.scrollTop = dom.messagesContainer.scrollHeight;

        const items = dom.messagesContainer.querySelectorAll('.cc-message-item');
        if (items.length > 200) items[0].remove();
    }

    // ── Fall Detection ─────────────────────────
    function setFallDetected(detected) {
        state.fallDetected = detected;
        if (dom.fallStatus) {
            dom.fallStatus.className = detected ? 'cc-fall-indicator danger' : 'cc-fall-indicator safe';
            if (dom.fallIconWrap) dom.fallIconWrap.innerHTML = detected ? '<i class="fas fa-person-falling"></i>' : '<i class="fas fa-person-walking"></i>';
            if (dom.fallLabel) dom.fallLabel.textContent = detected ? '⚠ FALL DETECTED!' : 'No Fall Detected';
        }
        if (dom.fallAlertBanner) dom.fallAlertBanner.classList.toggle('d-none', !detected);
        if (detected) showToast('⚠ Fall Detected! Check on the user immediately!', 'error', 8000);
    }

    // ── Emergency Stop ─────────────────────────
    function handleEmergencyStop() {
        // State is managed by global sendEmergency in base.html
        // This handler is just for local visual feedback if needed
    }

    // ── Send to ESP32 via Socket.IO ─────────────
    function sendToESP32(text) {
        if (s && s.connected) {
            s.emit('web_command', text);
        } else if (state.isDemoMode) {
            addMessage(`[Demo] Sent: ${text}`, 'outgoing');
        } else {
            showToast('Not connected', 'warning');
        }
    }

    // ── Handle esp_data (from Socket.IO bridge) ──
    function handleESP32Data(raw) {
        const colonIndex = ('' + raw).indexOf(':');
        if (colonIndex === -1) {
            addMessage(raw, 'incoming');
            return;
        }

        const key = ('' + raw).substring(0, colonIndex).trim().toLowerCase();
        const value = ('' + raw).substring(colonIndex + 1).trim();

        switch (key) {
            case 'heartrate':
                updateHeartRate(parseFloat(value) || 0);
                break;
            case 'location': {
                const parts = value.split(',');
                const x = parseFloat(parts[0]) || 0;
                const y = parseFloat(parts[1]) || 0;
                updateLocation(x, y);
                break;
            }
            case 'fall':
                setFallDetected(value === 'detected');
                break;
            case 'message':
                addMessage(value, 'incoming');
                break;
            case 'status': {
                const statusParts = value.split(',');
                if (statusParts[0] && dom.signalValue) dom.signalValue.textContent = statusParts[0].trim() + ' dBm';
                if (statusParts[1] && dom.ipValue) dom.ipValue.textContent = statusParts[1].trim();
                break;
            }
            default:
                addMessage(raw, 'incoming');
        }
    }

    // ── Demo Mode ──────────────────────────────
    function startDemoMode() {
        state.isDemoMode = true;
        setOnline('Demo Mode');
        if (dom.ipValue) dom.ipValue.textContent = '192.168.1.100';
        addMessage('Demo mode started — simulating ESP32 data', 'system');
        showToast('Demo mode active', 'info');

        let demoX = 12.971600, demoY = 77.594600, demoBPM = 72, demoTick = 0;

        state.demoInterval = setInterval(() => {
            demoTick++;
            demoBPM += (Math.random() - 0.48) * 4;
            demoBPM = Math.max(55, Math.min(140, demoBPM));
            updateHeartRate(demoBPM);

            demoX += (Math.random() - 0.5) * 0.0003;
            demoY += (Math.random() - 0.5) * 0.0003;
            updateLocation(demoX, demoY);

            if (demoTick % 8 === 0) {
                const msgs = ['Battery level: 78%', 'Motion detected: Walking', 'Data sync complete'];
                addMessage(msgs[Math.floor(Math.random() * msgs.length)], 'incoming');
            }

            const sig = Math.floor(-30 - Math.random() * 30);
            if (dom.signalValue) dom.signalValue.textContent = sig + ' dBm';

            if (demoTick === 50) {
                setFallDetected(true);
                setTimeout(() => setFallDetected(false), 8000);
            }
        }, 1200);
    }

    function stopDemoMode() {
        state.isDemoMode = false;
        clearInterval(state.demoInterval);
        setOffline();
        addMessage('Demo mode stopped', 'system');
    }

    // ── Pre-define handlers for listener removal ──
    const handleESPDataEvent = (e) => {
        handleESP32Data(e.detail.key + ':' + e.detail.value);
    };

    const handleStatusEvent = (e) => {
        const data = e.detail;
        state.bridgeConnected = (data.status === 'connected');
        if (state.bridgeConnected) {
            setOnline(data.ip || 'Connected');
        } else if (!state.isDemoMode) {
            setOffline();
        }
    };

    // ── Init & Event Listeners ─────────────────
    function init() {
        if (!initDOM()) return;

        hrCtx = dom.hrChart.getContext('2d');

        setInterval(updateClock, 1000);
        updateClock();
        setInterval(updateUptime, 1000);

        setOffline();

        // Apply last known status immediately if available
        if (window.lastDeviceStatus) {
            handleStatusEvent({ detail: window.lastDeviceStatus });
        }

        // Listen to global events dispatched by base.html
        window.addEventListener('esp_data', handleESPDataEvent);
        window.addEventListener('device_status', handleStatusEvent);

        // Socket connect/disconnect
        // We do NOT call setOnline here. Only device_status (ESP bridge) decides "ONLINE" for user.
        s.on('connect', () => { 
            console.log('[CommandCenter] Server connected'); 
        });
        s.on('disconnect', () => { setOffline(); });

        // Emergency - handled by base.html onclick="sendEmergency(...)"

        if (dom.dismissFallAlert) dom.dismissFallAlert.addEventListener('click', () => {
            if (dom.fallAlertBanner) dom.fallAlertBanner.classList.add('d-none');
        });

        if (dom.clearMessagesBtn) dom.clearMessagesBtn.addEventListener('click', () => {
            if (dom.messagesContainer) {
                dom.messagesContainer.innerHTML = '<div class="cc-message-placeholder text-center text-muted py-5"><i class="fas fa-satellite-dish fa-3x mb-3"></i><p>Waiting for ESP32 messages...</p></div>';
            }
        });

        function sendUserMessage() {
            const text = dom.sendMessageInput ? dom.sendMessageInput.value.trim() : '';
            if (!text) return;
            addMessage(text, 'outgoing');
            sendToESP32('command:' + text);
            if (dom.sendMessageInput) dom.sendMessageInput.value = '';
        }

        if (dom.sendMessageBtn) dom.sendMessageBtn.addEventListener('click', sendUserMessage);
        if (dom.sendMessageInput) dom.sendMessageInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendUserMessage(); });

        if (dom.wsDemoBtn) dom.wsDemoBtn.addEventListener('click', () => {
            if (state.isDemoMode) stopDemoMode();
            else startDemoMode();
        });

        setTimeout(() => {
            initMap();
            drawHRChart();
        }, 300);

        window.addEventListener('resize', () => {
            setTimeout(() => {
                if (state.heartRateHistory.length > 1) drawHRChart();
                if (leafletMap) leafletMap.invalidateSize();
            }, 200);
        });
    }

    function tryInit() {
        if (typeof socket === 'undefined') return false;
        init();
        return true;
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => tryInit());
    } else {
        tryInit();
    }

    window.addEventListener('app:page-changed', (e) => {
        if (e.detail && e.detail.path === '/command_center') tryInit();
    });

    window.initCommandCenter = tryInit;
})();
