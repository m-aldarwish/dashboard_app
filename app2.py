from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for
from datetime import timedelta
import threading
import json
import paho.mqtt.client as mqtt
import time

app = Flask(__name__)
app.secret_key = "secret_key_for_demo"
app.permanent_session_lifetime = timedelta(minutes=10)

# -------------------- GLOBAL DATA --------------------
system_state = {"on": True}
latest_data = {
    "sensor_data": {"gas_adc": 0, "temperature_c": 0, "current_a": 0, "voltage_v": 0},
    "RUL": 100,
    "system_on": True,
    "maintenance_alert": "",
    "history": []
}

# -------------------- MQTT CONFIG --------------------
MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
DATA_TOPIC = "electrolyzer/data"
CONTROL_TOPIC = "electrolyzer/control"

# Subscriber client (for incoming sensor data)
def on_connect(client, userdata, flags, rc):
    print("[MQTT] Connected with result code", rc)
    client.subscribe(DATA_TOPIC)

def on_message(client, userdata, msg):
    global latest_data
    try:
        payload = json.loads(msg.payload.decode())
        gas = payload.get("gas_adc", 0)
        temp = payload.get("temperature_c", 0)
        curr = payload.get("current_a", 0)
        volt = payload.get("voltage_v", 0)
        ts = payload.get("timestamp", time.time())

        latest_data.update({
            "sensor_data": {
                "gas_adc": gas,
                "temperature_c": temp,
                "current_a": curr,
                "voltage_v": volt
            },
            "system_on": system_state["on"],
        })

        # Compute mock RUL trend
        latest_data["RUL"] = max(0, 100 - abs(curr) * 0.5)
        latest_data["maintenance_alert"] = (
            "⚠️ Maintenance required soon!" if latest_data["RUL"] < 60 else ""
        )

        # Rolling history
        latest_data["history"].append({
            "timestamp": ts,
            "gas_adc": gas,
            "temperature_c": temp,
            "current_a": curr,
            "voltage_v": volt,
            "RUL": latest_data["RUL"]
        })
        latest_data["history"] = latest_data["history"][-100:]

        print(f"[MQTT] Updated: Gas={gas}, Temp={temp}, Current={curr}, Voltage={volt}")

    except Exception as e:
        print("[MQTT ERROR]", e)

def start_mqtt_listener():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_forever()

mqtt_thread = threading.Thread(target=start_mqtt_listener, daemon=True)
mqtt_thread.start()

# Publisher client (for control commands)
mqtt_pub_client = mqtt.Client()
mqtt_pub_client.connect(MQTT_BROKER, MQTT_PORT, 60)
mqtt_pub_client.loop_start()

# -------------------- ROUTES --------------------
@app.route("/")
def main_page():
    return render_template("main.html")

@app.route("/api/sensors")
def api_sensors():
    latest_data["system_on"] = system_state["on"]
    return jsonify(latest_data)

@app.route("/stream")
def stream():
    def event_stream():
        last_timestamp = None
        while True:
            if latest_data["history"]:
                current_ts = latest_data["history"][-1]["timestamp"]
                if current_ts != last_timestamp:
                    yield f"data: {json.dumps(latest_data)}\n\n"
                    last_timestamp = current_ts
            time.sleep(0.1)
    return Response(event_stream(), mimetype="text/event-stream")

# --- NEW: Control API ---
@app.route("/api/control", methods=["POST"])
def control():
    try:
        command = request.json.get("command", "").upper()
        if command not in ["LED1_ON", "LED1_OFF", "LED2_ON", "LED2_OFF", "SHUTDOWN"]:
            return jsonify({"error": "Invalid command"}), 400

        mqtt_pub_client.publish(CONTROL_TOPIC, command)
        print(f"[CONTROL] Published: {command}")
        return jsonify({"status": "ok", "command": command}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)