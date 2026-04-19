# 规则12: 土壤湿度自动浇水
#
# 任一花盆 (soil_blue / soil_green) 在 2 小时滚动窗口内
# soil_moisture < 35 命中 >= 3 次 → 开水阀 3 分钟
#
# 安全:
#   1. 阀门本地倒计时 (on_time=180): Zigbee onWithTimedOff,
#      即使 RPi / Z2M / MQTT 全挂也会自己关
#   2. asyncio 兜底: 第二层冗余，3 分 10 秒后再发一次 OFF
#   3. 浇水后 2h 冷却，避免传感器未更新导致重复浇
#   4. sanity check: 丢弃 moisture <= 0 或 >= 100 的异常读数

import asyncio
import time
from collections import deque

name = "土壤湿度自动浇水"
enabled = True
trigger = {"device": "soil_blue", "field": "soil_moisture"}
trigger2 = {"device": "soil_green", "field": "soil_moisture"}

THRESHOLD = 35
WINDOW_SEC = 2 * 60 * 60
REQUIRED_HITS = 3
VALVE_OPEN_SEC = 180
COOLDOWN_SEC = 2 * 60 * 60

_hits: dict[str, deque] = {
    "soil_blue": deque(),
    "soil_green": deque(),
}
_backup_close_task: asyncio.Task | None = None
_cooldown_until = 0.0


async def _backup_close(home):
    try:
        await asyncio.sleep(VALVE_OPEN_SEC + 10)
    except asyncio.CancelledError:
        return
    await home.set("water_valve", {"state": "OFF"})


async def run(home, device, payload):
    global _backup_close_task, _cooldown_until

    if device not in _hits:
        return

    moisture = payload.get("soil_moisture")
    if not isinstance(moisture, (int, float)):
        return
    if moisture <= 0 or moisture >= 100:
        return

    now = time.monotonic()

    q = _hits[device]
    while q and now - q[0] > WINDOW_SEC:
        q.popleft()

    if moisture < THRESHOLD:
        q.append(now)

    if now < _cooldown_until:
        return
    if _backup_close_task and not _backup_close_task.done():
        return
    if home.get("water_valve").get("state") == "ON":
        return

    if any(len(_hits[p]) >= REQUIRED_HITS for p in _hits):
        await home.set("water_valve", {"state": "ON", "on_time": VALVE_OPEN_SEC})
        _cooldown_until = now + VALVE_OPEN_SEC + COOLDOWN_SEC
        _backup_close_task = asyncio.create_task(_backup_close(home))
        for q2 in _hits.values():
            q2.clear()
        blue = home.get("soil_blue").get("soil_moisture")
        green = home.get("soil_green").get("soil_moisture")
        await home.notify(
            f"土壤偏干，开水阀 {VALVE_OPEN_SEC}s (blue={blue}, green={green})"
        )
