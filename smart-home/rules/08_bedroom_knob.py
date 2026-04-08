# 规则8: 卧室旋钮
# 单击：开关灯  双击：切换白光/彩色模式
# 两种模式旋转都是调亮度（5档：2,65,128,191,254），第一档再逆时针关灯
# 白光按住旋转：调色温  彩色按住旋转：改变色相
name = "卧室旋钮控灯"
enabled = True
schedule = None
trigger = {"device": "卧室背景灯控制", "field": "action"}

import asyncio
import time

_color_mode = False
_last_hue = 0
_last_toggle_time = 0.0
_pending_toggle: asyncio.Task | None = None
BRIGHTNESS_LEVELS = [2, 65, 128, 191, 254]


def _nearest_level(brightness: int) -> int:
    min_diff = 999
    idx = 0
    for i, lv in enumerate(BRIGHTNESS_LEVELS):
        diff = abs(brightness - lv)
        if diff < min_diff:
            min_diff = diff
            idx = i
    return idx


async def run(home):
    global _color_mode, _last_hue, _last_toggle_time, _pending_toggle
    state = home.get("卧室背景灯控制")
    action = state.get("action", "")
    light = home.get("卧室背景灯")

    # 单击：延迟执行，等看有没有 double 跟上
    if action == "toggle":
        _last_toggle_time = time.monotonic()
        if _pending_toggle and not _pending_toggle.done():
            _pending_toggle.cancel()

        async def delayed_toggle():
            await asyncio.sleep(0.4)
            lt = home.get("卧室背景灯")
            if lt.get("state", "OFF") == "ON":
                await home.set("卧室背景灯", {"state": "OFF"})
            else:
                payload = {"state": "ON"}
                if lt.get("brightness", 0) < 2:
                    payload["brightness"] = 2
                await home.set("卧室背景灯", payload)

        _pending_toggle = asyncio.create_task(delayed_toggle())

    # 双击：取消 pending toggle，切换模式
    elif action == "double":
        if _pending_toggle and not _pending_toggle.done():
            _pending_toggle.cancel()
            _pending_toggle = None
        _color_mode = not _color_mode
        if _color_mode:
            await home.set("卧室背景灯", {"color": {"hue": _last_hue, "saturation": 100}, "state": "ON"})
        else:
            await home.set("卧室背景灯", {"color_temp": 325, "state": "ON"})

    # 旋转：调亮度（5档），第一档逆时针关灯
    elif action in ("brightness_step_up", "brightness_step_down"):
        current_brightness = light.get("brightness", 128)
        idx = _nearest_level(current_brightness)
        if action == "brightness_step_up":
            if light.get("state", "OFF") == "OFF":
                await home.set("卧室背景灯", {"brightness": BRIGHTNESS_LEVELS[0], "state": "ON"})
            else:
                idx = min(len(BRIGHTNESS_LEVELS) - 1, idx + 1)
                await home.set("卧室背景灯", {"brightness": BRIGHTNESS_LEVELS[idx], "state": "ON"})
        else:
            if idx <= 0:
                await home.set("卧室背景灯", {"state": "OFF"})
            else:
                idx -= 1
                await home.set("卧室背景灯", {"brightness": BRIGHTNESS_LEVELS[idx], "state": "ON"})

    # 按住旋转
    elif action in ("color_temperature_step_up", "color_temperature_step_down"):
        if _color_mode:
            delta = 5
            if action == "color_temperature_step_up":
                _last_hue = (_last_hue + delta) % 360
            else:
                _last_hue = (_last_hue - delta) % 360
            await home.set("卧室背景灯", {"color": {"hue": _last_hue, "saturation": 100}, "state": "ON"})
        else:
            step = state.get("action_step_size", 50)
            current_ct = light.get("color_temp", 325)
            if action == "color_temperature_step_up":
                new_ct = min(500, current_ct + step)
            else:
                new_ct = max(150, current_ct - step)
            await home.set("卧室背景灯", {"color_temp": new_ct, "state": "ON"})
