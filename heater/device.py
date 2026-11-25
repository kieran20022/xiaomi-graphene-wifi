"""Heater model: loads the MIoT spec and maps it to named features."""
import json
import os
import sys
from pathlib import Path

import requests

from .miio import MiioDevice

DEFAULT_MODEL = "xiaomi.heater.ma8"
SPEC_HOST = "https://miot-spec.org/miot-spec-v2"

# feature key -> (service type, property type)
FEATURES = {
    "power": ("heater", "on"),
    "fault": ("heater", "fault"),
    "mode": ("heater", "mode"),
    "target_temp": ("heater", "target-temperature"),
    "temperature": ("environment", "temperature"),
    "child_lock": ("physical-controls-locked", "physical-controls-locked"),
    "beep": ("alarm", "alarm"),
    "swing": ("fan-control", "horizontal-swing"),
    "fan_level": ("fan-control", "fan-level"),
    "timer": ("delay", "delay"),
    "timer_hours": ("delay", "delay-time"),
    "timer_remaining": ("delay", "delay-remain-time"),
    "light": ("indicator-light", "on"),
    "brightness": ("indicator-light", "brightness"),
    "humidity": ("environment", "relative-humidity"),
}

INFO_PROPS = ("manufacturer", "model", "serial-number", "firmware-revision")


def _urn_name(urn: str) -> str:
    return urn.split(":")[3]


def app_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home())) / "GrapheneHeater"
    base.mkdir(parents=True, exist_ok=True)
    return base


def resource(rel: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / rel


def load_spec(model: str) -> dict:
    """Bundled spec -> cached spec -> download from miot-spec.org."""
    name = f"spec_{model}.json"
    for p in (resource(f"heater/{name}"), app_dir() / name):
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    inst = requests.get(f"{SPEC_HOST}/instances?status=all", timeout=15).json()["instances"]
    matches = [i for i in inst if i["model"] == model]
    if not matches:
        raise RuntimeError(f"No MIoT spec found for {model}")
    urn = max(matches, key=lambda i: i["version"])["type"]
    spec = requests.get(f"{SPEC_HOST}/instance", params={"type": urn}, timeout=15).json()
    (app_dir() / name).write_text(json.dumps(spec), encoding="utf-8")
    return spec


def build_schema(spec: dict) -> dict:
    """Turn a MIoT spec into {feature: {siid, piid, format, access, range, values}}."""
    schema = {}
    info = {}
    toggle = None
    for svc in spec["services"]:
        sname = _urn_name(svc["type"])
        for prop in svc.get("properties", []):
            pname = _urn_name(prop["type"])
            entry = {
                "siid": svc["iid"],
                "piid": prop["iid"],
                "format": prop["format"],
                "writable": "write" in prop["access"],
                "unit": prop.get("unit"),
                "range": prop.get("value-range"),
                "values": [
                    {"value": v["value"], "label": v["description"]} for v in prop.get("value-list", [])
                ],
            }
            if sname == "device-information" and pname in INFO_PROPS:
                info[pname] = entry
                continue
            for key, (s, p) in FEATURES.items():
                if pname == p and sname == s:
                    schema.setdefault(key, entry)
        if sname == "heater":
            for act in svc.get("actions", []):
                if _urn_name(act["type"]) == "toggle":
                    toggle = (svc["iid"], act["iid"])
    return {"features": schema, "info": info, "toggle": toggle}


class Heater:
    def __init__(self, ip: str, token: str):
        self.dev = MiioDevice(ip, token)
        self.model = None
        self.schema = None
        self.device_info = {}

    def connect(self):
        try:
            info = self.dev.info() or {}
            self.model = info.get("model") or DEFAULT_MODEL
            self.device_info = {
                "model": self.model,
                "firmware": info.get("fw_ver"),
                "mac": info.get("mac"),
                "wifi_rssi": (info.get("ap") or {}).get("rssi"),
            }
        except Exception:
            # Some firmwares don't answer miIO.info; fall back to the known model
            self.model = DEFAULT_MODEL
            self.device_info = {"model": self.model}
        try:
            spec = load_spec(self.model)
        except Exception:
            spec = load_spec(DEFAULT_MODEL)
        self.schema = build_schema(spec)
        # Validate the token with a real MIoT read
        self.read_state()

    def read_state(self) -> dict:
        feats = self.schema["features"]
        pairs = [(f["siid"], f["piid"]) for f in feats.values()]
        values = self.dev.get_properties(pairs)
        return {k: values.get((f["siid"], f["piid"])) for k, f in feats.items()}

    def set(self, feature: str, value):
        f = self.schema["features"][feature]
        if f["format"] == "bool":
            value = bool(value)
        elif f["format"].startswith(("uint", "int")):
            value = int(value)
        elif f["format"] == "float":
            value = float(value)
        self.dev.set_property(f["siid"], f["piid"], value)
