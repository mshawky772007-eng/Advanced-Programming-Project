"""
Pencil Manufacturing Production Line - Backend
Run with Docker Compose or: pip install flask flask-cors influxdb-client
"""

import os, random, time, threading
from flask import Flask, jsonify
from flask_cors import CORS
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

app = Flask(__name__)
CORS(app)

# ── InfluxDB setup ─────────────────────────────────────────────────────────────
INFLUX_URL    = os.getenv("INFLUX_URL",    "http://influxdb:8086")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN",  "mytoken")
INFLUX_ORG    = os.getenv("INFLUX_ORG",    "pencilorg")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "production")

influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = influx_client.write_api(write_options=SYNCHRONOUS)

def influx_write(fields: dict, tags: dict = {}):
    try:
        p = Point("production_metrics")
        for k, v in tags.items():   p = p.tag(k, v)
        for k, v in fields.items(): p = p.field(k, v)
        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=p)
    except Exception as e:
        print(f"InfluxDB write failed: {e}")

# ── Machine state ──────────────────────────────────────────────────────────────
state = {
    "running":     False,
    "produced":    0,
    "defective":   0,
    "history":     [],
    "last_error":  None,
    "stage_temps": [22.0, 22.0, 22.0, 22.0],
}

STAGES         = ["Graphite Core", "Body", "Eraser", "Eraser Holder"]
DEFECT_RATES   = [0.05, 0.04, 0.06, 0.03]
DEFECT_REASONS = [
    "Graphite core fractured during insertion",
    "Pencil body split — wood grain defect",
    "Eraser misaligned or missing",
    "Eraser holder crimp failure",
]

def produce_unit():
    for i in range(4):
        state["stage_temps"][i] = round(
            max(18.0, min(35.0, state["stage_temps"][i] + random.uniform(-0.3, 0.4))), 1
        )
        if random.random() < DEFECT_RATES[i]:
            return False, f"Stage {i+1} ({STAGES[i]}): {DEFECT_REASONS[i]}"
    return True, None

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.post("/start")
def start():
    state["running"] = True
    state["last_error"] = None
    influx_write({"event": "start", "running": 1.0})
    return jsonify({"ok": True})

@app.post("/stop")
def stop():
    state["running"] = False
    influx_write({"event": "stop", "running": 0.0})
    return jsonify({"ok": True})

@app.post("/reset")
def reset():
    state.update({"running": False, "produced": 0, "defective": 0,
                  "history": [], "last_error": None,
                  "stage_temps": [22.0, 22.0, 22.0, 22.0]})
    influx_write({"event": "reset", "running": 0.0})
    return jsonify({"ok": True})

@app.post("/tick")
def tick():
    if not state["running"]:
        return jsonify({"ok": False})

    ok, reason = produce_unit()
    state["produced"] += 1
    if not ok:
        state["defective"] += 1
        state["last_error"] = reason

    state["history"].append({"id": state["produced"], "ok": ok, "defect": reason or "—"})
    if len(state["history"]) > 50:
        state["history"].pop(0)

    good = state["produced"] - state["defective"]
    yield_pct = round(good / state["produced"] * 100, 1) if state["produced"] else 0.0

    # Write to InfluxDB
    influx_write({
        "produced":    float(state["produced"]),
        "defective":   float(state["defective"]),
        "good":        float(good),
        "yield_pct":   yield_pct,
        "temp_stage1": state["stage_temps"][0],
        "temp_stage2": state["stage_temps"][1],
        "temp_stage3": state["stage_temps"][2],
        "temp_stage4": state["stage_temps"][3],
        "unit_ok":     1.0 if ok else 0.0,
    })

    return jsonify({"ok": True, "unit_ok": ok, "defect": reason})

@app.get("/status")
def status():
    good = state["produced"] - state["defective"]
    yield_pct = round(good / state["produced"] * 100, 1) if state["produced"] else 0.0
    return jsonify({**state, "good": good, "yield_pct": yield_pct})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
