# 规则1: 自动灯光控制（合并客厅+餐厅+夜间模式）
#
# 白天（日出~日落前1h）：
#   餐厅检测到人 → 开餐厅灯，无人5分钟关
# 夜晚（日落前1h~23:30）：
#   任意检测到人 → 开客厅大灯
#   餐厅检测到人 → 也开餐厅灯，无人5分钟关
# 深夜（23:30~日出）：
#   23:30 自动关客厅大灯
#   任意检测到人 → 开餐厅灯，无人5分钟关
# 开关始终 toggle 客厅大灯，关灯后1分钟冷却

import asyncio
import time
from datetime import datetime, timedelta

from astral import LocationInfo
from astral.sun import sun

name = "自动灯光"
enabled = True
schedule = "23:30"
trigger = {"device": "客厅检测", "field": "presence", "value": True}
trigger2 = {"device": "卧室门检测", "field": "presence", "value": True}
trigger3 = {"device": "餐厅检测", "field": "presence"}
trigger4 = {"device": "厕所门检测", "field": "presence", "value": True}
trigger5 = {"device": "客厅灯开关", "field": "action", "value": "single"}
trigger6 = {"device": "餐厅灯开关", "field": "action", "value": "single"}

_cooldown_until = 0.0
_dining_off_task: asyncio.Task | None = None
_dining_lights = ("餐厅灯1", "餐厅灯2", "餐厅灯3")
_location = LocationInfo("Foster City", "USA", "US/Pacific", 37.5585, -122.2711)


def _get_mode() -> str:
    now = datetime.now().astimezone()
    s = sun(_location.observer, date=now.date(), tzinfo=now.tzinfo)
    sunrise = s["sunrise"]
    sunset = s["sunset"]
    evening_start = sunset - timedelta(hours=1)
    minutes = now.hour * 60 + now.minute
    if minutes >= 23 * 60 + 30 or now < sunrise:
        return "late_night"
    elif now >= evening_start:
        return "night"
    return "day"


async def _dining_on(home):
    for light in _dining_lights:
        await home.set(light, {"state": "ON"})


async def _dining_off_delayed(home):
    global _dining_off_task
    if _dining_off_task and not _dining_off_task.done():
        _dining_off_task.cancel()

    async def _do():
        await asyncio.sleep(300)
        if not home.get("餐厅检测").get("presence", False):
            for light in _dining_lights:
                await home.set(light, {"state": "OFF"})

    _dining_off_task = asyncio.create_task(_do())


async def run(home, device=None, payload=None):
    global _cooldown_until, _dining_off_task

    # --- 定时触发：23:30 关客厅大灯 ---
    if device is None:
        if home.get("客厅大灯").get("state") == "ON":
            await home.set("客厅大灯", {"state": "OFF"})
        return

    mode = _get_mode()

    # --- 客厅灯开关 ---
    if device == "客厅灯开关":
        current = home.get("客厅大灯").get("state", "OFF")
        if current == "ON":
            await home.set("客厅大灯", {"state": "OFF"})
            _cooldown_until = time.monotonic() + 60
        else:
            await home.set("客厅大灯", {"state": "ON"})
            _cooldown_until = 0.0
        return

    # --- 餐厅灯开关 ---
    if device == "餐厅灯开关":
        current = home.get("餐厅灯1").get("state", "OFF")
        new_state = "OFF" if current == "ON" else "ON"
        for light in _dining_lights:
            await home.set(light, {"state": new_state})
        if new_state == "OFF":
            _cooldown_until = time.monotonic() + 60
            if _dining_off_task and not _dining_off_task.done():
                _dining_off_task.cancel()
                _dining_off_task = None
        return

    # --- 餐厅检测 ---
    if device == "餐厅检测":
        presence = payload.get("presence", False)
        if presence:
            if _dining_off_task and not _dining_off_task.done():
                _dining_off_task.cancel()
                _dining_off_task = None
            await _dining_on(home)
            # 夜晚模式也开客厅大灯
            if mode == "night" and time.monotonic() >= _cooldown_until:
                await home.set("客厅大灯", {"state": "ON"})
        else:
            await _dining_off_delayed(home)
        return

    # --- 其他人体检测（客厅、卧室门、厕所门）---
    if time.monotonic() < _cooldown_until:
        return

    if mode == "night":
        await home.set("客厅大灯", {"state": "ON"})
    elif mode == "late_night":
        await _dining_on(home)
