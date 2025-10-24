import serial
import time
import json
import paho.mqtt.client as mqtt
import threading

# ========================
# CONFIGURATION
# ========================
SERIAL_PORT = 'COM3'      # Change to match Arduino
BAUD_RATE = 9600
READ_INTERVAL = 2         # seconds
MQTT_BROKER = 'test.mosquitto.org'
MQTT_PORT = 1883
MQTT_PUB_TOPIC = 'electrolyzer/data'
MQTT_SUB_TOPIC = 'electrolyzer/control'

ser = None
mqtt_client = None

# ========================
# HELPERS
# ========================
def adc_to_voltage(adc_value):
    return adc_value * (5.0 / 1023.0)

def acs712_to_current(adc_value, sensitivity=0.185):
    voltage = adc_to_voltage(adc_value)
    return (voltage - 2.5) / sensitivity  # for ACS712-05B

def voltage_divider(adc_value, R1=30000, R2=7500): 
    # Example divider 30k:7.5k → adjust for your circuit
    Vout = adc_to_voltage(adc_value)
    Vin = Vout * (R1 + R2) / R2
    return Vin

# ========================
# MQTT CALLBACKS
# ========================
def on_connect(client, userdata, flags, rc, properties=None):
    print(f"[MQTT] Connected with result code {rc}")
    client.subscribe(MQTT_SUB_TOPIC)

def on_message(client, userdata, msg):
    command = msg.payload.decode().strip().upper()
    print(f"[MQTT] Received control command: {command}")
    if command in ['LED1_ON', 'LED1_OFF', 'LED2_ON', 'LED2_OFF', 'SHUTDOWN']:
        try:
            ser.write(f"CMD:{command}\n".encode())
            print(f"[SERIAL] Sent to Arduino: CMD:{command}")
        except Exception as e:
            print(f"[SERIAL] Failed to send command: {e}")

# ========================
# SERIAL SETUP
# ========================
def init_serial():
    global ser
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        print("[SERIAL] Connected to Arduino")
    except serial.SerialException:
        print("[ERROR] Could not connect to Arduino. Exiting...")
        exit(1)

# ========================
# PARSE DATA
# ========================
def parse_data(raw_line):
    try:
        parts = [float(x.strip()) for x in raw_line.split(",")]
        if len(parts) != 4:
            raise ValueError("Expected 4 values: gas,temp,current,voltage")

        gas_adc, temp_c, current_adc, voltage_adc = parts

        data = {
            "gas_adc": gas_adc,
            "temperature_c": temp_c,
            "current_a": acs712_to_current(current_adc),
            "voltage_v": voltage_divider(voltage_adc),
            "timestamp": time.time()
        }
        return data
    except Exception as e:
        print(f"[PARSER] Failed to parse: {raw_line} | Error: {e}")
        return None

# ========================
# SENSOR THREAD
# ========================
def sensor_reader():
    while True:
        try:
            raw_line = ser.readline().decode().strip()
            if raw_line:
                data = parse_data(raw_line)
                if data:
                    mqtt_client.publish(MQTT_PUB_TOPIC, json.dumps(data))
                    print(f"[MQTT] Published: {data}")
        except Exception as e:
            print(f"[SERIAL] Error: {e}")
        time.sleep(READ_INTERVAL)

# ========================
# MAIN
# ========================
def main():
    global mqtt_client
    init_serial()

    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)

    t = threading.Thread(target=sensor_reader, daemon=True)
    t.start()

    mqtt_client.loop_forever()

if __name__ == "__main__":
    main()