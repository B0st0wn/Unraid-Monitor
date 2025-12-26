from typing import Dict, Any
import re
import time
from utils import normalize_str

# Map apcupsd/raw keys -> normalized metric keys
UPS_FIELD_MAP = {
    "STATUS": "status",
    "LINEV": "line_voltage_v",
    "LOADPCT": "load_pct",
    "LOADW": "load_w",
    "BCHARGE": "battery_pct",
    "TIMELEFT": "time_left_min",
    "LINEFREQ": "line_freq_hz",
    "OUTPUTV": "output_voltage_v",
    "BATTV": "battery_voltage_v",
    "NOMPOWER": "nominal_power_w",
    "NOMINV": "nominal_input_v",
    "NOMBATTV": "nominal_battery_v",
    "MODEL": "model",
    "SERIALNO": "serial",
    "UPSNAME": "ups_name",
    "HOSTNAME": "ups_host",
    "CUMONBATT": "cum_on_batt_s",
    "TONBATT": "on_batt_s",
    "DATE": "reported_at",
}

# Per-metric HA discovery metadata
SENSOR_META: Dict[str, Dict[str, Any]] = {
    "status":               {"name": "UPS Status",               "icon": "mdi:power-plug"},
    "line_voltage_v":       {"name": "UPS Line Voltage",         "device_class": "voltage", "unit": "V",  "state_class": "measurement"},
    "load_pct":             {"name": "UPS Load",                 "unit": "%",               "state_class": "measurement"},
    "load_w":               {"name": "UPS Load Power",           "device_class": "power",   "unit": "W",  "state_class": "measurement"},
    "battery_pct":          {"name": "UPS Battery",              "device_class": "battery", "unit": "%",  "state_class": "measurement"},
    "time_left_min":        {"name": "UPS Time Left",            "unit": "min"},
    "line_freq_hz":         {"name": "UPS Line Frequency",       "unit": "Hz",              "state_class": "measurement"},
    "output_voltage_v":     {"name": "UPS Output Voltage",       "device_class": "voltage", "unit": "V",  "state_class": "measurement"},
    "battery_voltage_v":    {"name": "UPS Battery Voltage",      "device_class": "voltage", "unit": "V",  "state_class": "measurement"},
    "nominal_power_w":      {"name": "UPS Nominal Power",        "device_class": "power",   "unit": "W"},
    "nominal_input_v":      {"name": "UPS Nominal Input",        "device_class": "voltage", "unit": "V"},
    "nominal_battery_v":    {"name": "UPS Nominal Battery",      "device_class": "voltage", "unit": "V"},
    "model":                {"name": "UPS Model"},
    "serial":               {"name": "UPS Serial"},
    "ups_name":             {"name": "UPS Name"},
    "ups_host":             {"name": "UPS Host"},
    "cum_on_batt_s":        {"name": "UPS Cumulative On Battery","unit": "s"},
    "on_batt_s":            {"name": "UPS On Battery",           "unit": "s"},
    "reported_at":          {"name": "UPS Reported At"},
}

def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Convert apcupsd/raw keys to normalized keys used by topics/entities."""
    norm: Dict[str, Any] = {}
    for k, v in payload.items():
        key = UPS_FIELD_MAP.get(k, k.lower())
        norm[key] = v
    return norm

def _coerce_value(key: str, val: Any) -> Any:
    """
    Extract numeric value from strings with units when appropriate
    (e.g., '120.0 Volts' -> '120.0'), but leave non-numeric/status values intact.
    """
    meta = SENSOR_META.get(key, {})
    unit = meta.get("unit")
    if unit and isinstance(val, str):
        m = re.search(r'[-+]?\d*\.?\d+', val)
        if m:
            return m.group(0)
    return val

def publish_flat_topics(mqtt, base_topic: str, server_name: str, payload: Dict[str, Any]) -> None:
    """
    Publishes flat metrics under: {base_topic}/{server_name}/ups/<metric>
    Keeps your original flat-topic layout for tooling like Grafana/Node-RED.
    """
    topic_root = f"{base_topic}/{server_name}/ups"
    norm = _normalize_payload(payload)
    for key, v in norm.items():
        mqtt.publish(f"{topic_root}/{key}", _coerce_value(key, v), retain=True)

def publish_ha_entities(server, payload: Dict[str, Any], create_config: bool) -> None:
    """
    Publishes one HA sensor entity per metric using server.mqtt_publish for discovery.
    Each entity publishes to: unraid/<server_id>/<sensor_id>/state
    and config to: homeassistant/sensor/<unraid_id>_<sensor_id>/config
    """
    norm = _normalize_payload(payload)
    for key, value in norm.items():
        meta = SENSOR_META.get(key)
        if not meta:
            continue

        state = _coerce_value(key, value)

        # Build discovery payload
        cfg: Dict[str, Any] = {"name": meta["name"]}
        if "icon" in meta: cfg["icon"] = meta["icon"]
        if "device_class" in meta: cfg["device_class"] = meta["device_class"]
        if "unit" in meta: cfg["unit_of_measurement"] = meta["unit"]
        if "state_class" in meta: cfg["state_class"] = meta["state_class"]

        # server.mqtt_publish handles unique_id/device + topics; retain=True for stability
        server.mqtt_publish(
            payload=cfg,
            sensor_type="sensor",
            state_value=state,
            json_attributes=None,
            create_config=create_config,
            retain=True
        )

def handle_ups(server, payload: Dict[str, Any], create_config: bool) -> None:
    """
    Single entrypoint used by parsers:
      - Publishes per-metric flat topics
      - Publishes per-metric HA discovery entities
    """
    server_id = normalize_str(server.unraid_name)
    server.last_ups_payload = payload
    server.last_ups_time = time.time()
    publish_flat_topics(server.mqtt_client, server.base_topic, server_id, payload)
    publish_ha_entities(server, payload, create_config)
