# 规则4: 卧室门开关 + 卧室开关 → 双控卧室大灯（Shuai卧室灯）
name = "卧室开关双控大灯"
enabled = True
schedule = None
trigger = {"device": "bedroom_door_switch", "field": "action", "value": "single"}
trigger2 = {"device": "bedroom_switch", "field": "action", "value": "single"}


async def run(home):
    current = home.get("bedroom_main_light").get("state", "OFF")
    new_state = "OFF" if current == "ON" else "ON"
    await home.set("bedroom_main_light", {"state": new_state})
