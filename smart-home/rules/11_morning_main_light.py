# 规则11: 工作日 09:58 开 Shuai卧室灯（卧室大灯）
name = "工作日早上开卧室大灯"
enabled = True
schedule = {"time": "09:58", "weekdays": [0, 1, 2, 3, 4]}


async def run(home):
    await home.set("bedroom_main_light", {"state": "ON"})
