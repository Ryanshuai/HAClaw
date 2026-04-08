"""Smart Home Service — aiomqtt + FastAPI + Rules Engine"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiomqtt
from fastapi import FastAPI, HTTPException

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
RULES_DIR = Path(__file__).parent / "rules"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("smart-home")

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
devices: dict[str, dict[str, Any]] = {}      # device_name -> latest state
device_list: list[dict[str, Any]] = []        # from zigbee2mqtt/bridge/devices
rules: dict[str, dict[str, Any]] = {}         # rule_name -> {module, meta...}

# 全局 aiomqtt client（在 startup 时赋值）
_mqtt_client: aiomqtt.Client | None = None

# ---------------------------------------------------------------------------
# Home object（注入到规则的 run(home) 中）
# ---------------------------------------------------------------------------

class Home:
    def get(self, device: str) -> dict[str, Any]:
        return devices.get(device, {})

    def get_all(self) -> dict[str, dict[str, Any]]:
        return dict(devices)

    async def set(self, device: str, payload: dict[str, Any]) -> None:
        topic = f"zigbee2mqtt/{device}/set"
        if _mqtt_client is None:
            log.warning("MQTT client not ready, cannot set %s", device)
            return
        await _mqtt_client.publish(topic, json.dumps(payload))
        log.info("SET %-30s %s", device, payload)

    async def notify(self, msg: str) -> None:
        if _mqtt_client:
            await _mqtt_client.publish("smart-home/notify", json.dumps({"message": msg}))
        log.info("NOTIFY: %s", msg)


home = Home()

# ---------------------------------------------------------------------------
# Rules engine
# ---------------------------------------------------------------------------

def load_rule(filepath: Path) -> dict[str, Any] | None:
    name = filepath.stem
    try:
        spec = importlib.util.spec_from_file_location(f"rule_{name}", filepath)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        # 支持多 trigger: trigger + trigger2, trigger3, ...
        triggers = []
        t = getattr(mod, "trigger", None)
        if t:
            triggers.append(t)
        for i in range(2, 10):
            t = getattr(mod, f"trigger{i}", None)
            if t:
                triggers.append(t)
        return {
            "module": mod,
            "name": getattr(mod, "name", name),
            "enabled": getattr(mod, "enabled", True),
            "schedule": getattr(mod, "schedule", None),
            "triggers": triggers,
            "filepath": str(filepath),
        }
    except Exception as e:
        log.error("Failed to load rule %s: %s", name, e)
        return None


def load_all_rules() -> None:
    rules.clear()
    RULES_DIR.mkdir(parents=True, exist_ok=True)
    for f in sorted(RULES_DIR.glob("*.py")):
        rule = load_rule(f)
        if rule:
            rules[f.stem] = rule
            log.info("Loaded rule: %s (schedule=%s triggers=%s)",
                     rule["name"], rule["schedule"], rule["triggers"])


def reload_rule(name: str) -> None:
    filepath = RULES_DIR / f"{name}.py"
    if filepath.exists():
        rule = load_rule(filepath)
        if rule:
            rules[name] = rule
            log.info("Reloaded rule: %s", rule["name"])
    elif name in rules:
        del rules[name]
        log.info("Removed rule: %s", name)


def _match_trigger(trigger: dict[str, Any], device_name: str, payload: dict[str, Any]) -> bool:
    if trigger.get("device") != device_name:
        return False
    field = trigger.get("field")
    if field and field not in payload:
        return False
    value = payload.get(field) if field else None
    if "value" in trigger and value != trigger["value"]:
        return False
    if "above" in trigger and (value is None or value <= trigger["above"]):
        return False
    if "below" in trigger and (value is None or value >= trigger["below"]):
        return False
    return True


async def check_triggers(device_name: str, payload: dict[str, Any]) -> None:
    """MQTT 消息到达时，检查所有 trigger 规则是否匹配。"""
    for rule_name, rule in list(rules.items()):
        if not rule["enabled"] or not rule["triggers"]:
            continue
        if not any(_match_trigger(t, device_name, payload) for t in rule["triggers"]):
            continue
        try:
            import inspect
            sig = inspect.signature(rule["module"].run)
            if len(sig.parameters) >= 3:
                await rule["module"].run(home, device_name, payload)
            else:
                await rule["module"].run(home)
            log.info("Trigger fired: %s (by %s)", rule["name"], device_name)
        except Exception as e:
            log.error("Rule %s error: %s", rule["name"], e)


async def schedule_loop() -> None:
    """每分钟整点检查 schedule 规则（精度 1min，不重复触发）。"""
    import datetime
    last_fired: dict[str, str] = {}
    while True:
        # 等到下一个整分钟
        now = datetime.datetime.now()
        sleep_secs = 60 - now.second
        await asyncio.sleep(sleep_secs)

        now = datetime.datetime.now()
        time_str = now.strftime("%H:%M")
        weekday = now.weekday()  # 0=Mon … 6=Sun

        for rule_name, rule in list(rules.items()):
            if not rule["enabled"] or not rule["schedule"]:
                continue
            sched = rule["schedule"]

            # 支持 {"time": "HH:MM", "weekdays": [0,1,2,3,4]} 或简单字符串 "HH:MM"
            if isinstance(sched, dict):
                sched_time = sched.get("time", "")
                sched_days = sched.get("weekdays")  # None = every day
            else:
                sched_time = sched
                sched_days = None

            if sched_time != time_str:
                continue
            if sched_days is not None and weekday not in sched_days:
                continue
            if last_fired.get(rule_name) == time_str:
                continue  # 本分钟已触发过

            last_fired[rule_name] = time_str
            try:
                await rule["module"].run(home)
                log.info("Schedule fired: %s", rule["name"])
            except Exception as e:
                log.error("Scheduled rule %s error: %s", rule["name"], e)


# ---------------------------------------------------------------------------
# File watcher（watchdog 热加载 rules/）
# ---------------------------------------------------------------------------

def start_watcher() -> None:
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        class RuleHandler(FileSystemEventHandler):
            def on_any_event(self, event):
                src = getattr(event, "src_path", "")
                if src.endswith(".py"):
                    name = Path(src).stem
                    log.info("Rule file changed: %s", name)
                    reload_rule(name)

        observer = Observer()
        observer.schedule(RuleHandler(), str(RULES_DIR), recursive=False)
        observer.daemon = True
        observer.start()
        log.info("File watcher started on %s", RULES_DIR)
    except ImportError:
        log.warning("watchdog not installed, hot-reload disabled")


# ---------------------------------------------------------------------------
# MQTT listener loop
# ---------------------------------------------------------------------------

async def mqtt_loop() -> None:
    global _mqtt_client
    reconnect_delay = 5
    while True:
        try:
            async with aiomqtt.Client(MQTT_HOST, MQTT_PORT) as client:
                _mqtt_client = client
                log.info("MQTT connected to %s:%s", MQTT_HOST, MQTT_PORT)
                await client.subscribe("zigbee2mqtt/#")
                async for message in client.messages:
                    topic = str(message.topic)
                    try:
                        payload = json.loads(message.payload)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue

                    # Z2M 设备列表
                    if topic == "zigbee2mqtt/bridge/devices":
                        device_list.clear()
                        if isinstance(payload, list):
                            device_list.extend(payload)
                        log.info("Discovered %d devices", len(device_list))
                        continue

                    # 设备状态: zigbee2mqtt/{name}
                    parts = topic.split("/")
                    if len(parts) == 2 and parts[1] not in ("bridge",):
                        device_name = parts[1]
                        if isinstance(payload, dict):
                            devices[device_name] = payload
                            await check_triggers(device_name, payload)

        except aiomqtt.MqttError as e:
            _mqtt_client = None
            log.warning("MQTT disconnected (%s), retry in %ds", e, reconnect_delay)
            await asyncio.sleep(reconnect_delay)


# ---------------------------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_all_rules()
    start_watcher()
    mqtt_task = asyncio.create_task(mqtt_loop())
    sched_task = asyncio.create_task(schedule_loop())
    log.info("Smart Home Service started")
    yield
    mqtt_task.cancel()
    sched_task.cancel()
    log.info("Smart Home Service stopped")


app = FastAPI(title="Smart Home", lifespan=lifespan)

# ---------------------------------------------------------------------------
# REST API — Devices
# ---------------------------------------------------------------------------

@app.get("/api/devices")
async def api_get_devices():
    return {"devices": devices, "device_list": device_list}


@app.get("/api/devices/{name}")
async def api_get_device(name: str):
    if name not in devices:
        raise HTTPException(404, f"Device '{name}' not found")
    return devices[name]


@app.post("/api/devices/{name}")
async def api_set_device(name: str, payload: dict[str, Any]):
    await home.set(name, payload)
    return {"ok": True}


# ---------------------------------------------------------------------------
# REST API — Rules
# ---------------------------------------------------------------------------

@app.get("/api/rules")
async def api_get_rules():
    return {
        key: {
            "name": r["name"],
            "enabled": r["enabled"],
            "schedule": r["schedule"],
            "triggers": r["triggers"],
        }
        for key, r in rules.items()
    }


@app.get("/api/rules/{name}")
async def api_get_rule(name: str):
    filepath = RULES_DIR / f"{name}.py"
    if not filepath.exists():
        raise HTTPException(404, f"Rule '{name}' not found")
    return {"name": name, "code": filepath.read_text(encoding="utf-8")}


@app.put("/api/rules/{name}")
async def api_put_rule(name: str, body: dict[str, Any]):
    code: str = body.get("code", "")
    if not code.strip():
        raise HTTPException(400, "Missing 'code' field")
    filepath = RULES_DIR / f"{name}.py"
    filepath.write_text(code, encoding="utf-8")
    reload_rule(name)
    return {"ok": True, "name": name}


@app.delete("/api/rules/{name}")
async def api_delete_rule(name: str):
    filepath = RULES_DIR / f"{name}.py"
    if filepath.exists():
        filepath.unlink()
    rules.pop(name, None)
    return {"ok": True}


@app.post("/api/rules/{name}/enable")
async def api_enable_rule(name: str, body: dict[str, Any] | None = None):
    if name not in rules:
        raise HTTPException(404, f"Rule '{name}' not found")
    enabled = (body or {}).get("enabled", True)
    rules[name]["enabled"] = enabled
    return {"ok": True, "enabled": enabled}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def api_health():
    return {
        "status": "ok",
        "mqtt_connected": _mqtt_client is not None,
        "devices": len(devices),
        "rules": len(rules),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
