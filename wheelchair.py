import asyncio
import websockets
import random
import time
import json
from datetime import datetime

# ─── Configuration ────────────────────────────
WHEELCHAIR_ID = "ASSISTO-002"
WS_PORT = 8081 # Using 8081 to avoid permission errors on Linux (ports < 1024 require root)

# ─── State ────────────────────────────────────
emergency_stop = False
connected_clients = set()

async def handler(websocket):
    global emergency_stop
    print(f"🔌 Browser/Server connected from {websocket.remote_address}")
    connected_clients.add(websocket)
    
    try:
        async for message in websocket:
            print(f"📥 Received: {message}")
            
            if message == "emergency:stop":
                emergency_stop = True
                print("[EMERGENCY] >>> STOP ACTIVATED <<<")
                await websocket.send("message:Emergency STOP activated!")
            elif message == "emergency:release":
                emergency_stop = False
                print("[EMERGENCY] Stop released — resuming")
                await websocket.send("message:Emergency stop released.")
            elif message.startswith("command:"):
                cmd = message.split(":", 1)[1]
                print(f"[CUSTOM] Executing command: {cmd}")
                await websocket.send(f"message:Executed {cmd}")
                
    except websockets.exceptions.ConnectionClosedOK:
        pass
    finally:
        connected_clients.remove(websocket)
        print(f"🔌 Disconnected from {websocket.remote_address}")

async def sensor_broadcast():
    global emergency_stop
    while True:
        if connected_clients and not emergency_stop:
            # Send sensor data to all connected clients
            
            # 1. Heart Rate
            hr = random.randint(65, 85)
            # 2. Location (simulate movement)
            lat = 10.9348 + (random.uniform(-0.002, 0.002))
            lng = 76.0022 + (random.uniform(-0.002, 0.002))
            # 3. Status
            status = f"-{random.randint(30, 80)},192.168.1.100"
            
            messages = [
                f"heartrate:{hr}",
                f"location:{lat:.6f},{lng:.6f}",
                f"status:{status}"
            ]
            
            for ws in list(connected_clients):
                try:
                    for m in messages:
                        await ws.send(m)
                    
                    # Random fall (0.5% chance)
                    if random.random() < 0.005:
                        await ws.send("fall:detected")
                        print("⚠️ FALL DETECTED!")
                        await asyncio.sleep(2)
                        await ws.send("fall:safe")
                except:
                    pass
                    
        await asyncio.sleep(1)

async def main():
    print(f"🚀 ESP32 Simulator started on ws://0.0.0.0:{WS_PORT}")
    async with websockets.serve(handler, "0.0.0.0", WS_PORT):
        await sensor_broadcast()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n🛑 Simulator stopped.")