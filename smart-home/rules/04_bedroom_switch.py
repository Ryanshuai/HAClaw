# 规则4: 卧室门开关 + 卧室开关 → 双控卧室大灯（Shuai卧室灯）
name = "卧室开关双控大灯"
enabled = True
schedule = None
trigger = {"device": "Shuai 卧室 门开关", "field": "action", "value": "single"}
trigger2 = {"device": "Shuai 卧室开关", "field": "action", "value": "single"}


async def run(home):
    current = home.get("Shuai卧室灯").get("state", "OFF")
    new_state = "OFF" if current == "ON" else "ON"
    await home.set("Shuai卧室灯", {"state": new_state})
