# 规则10: 工作日 09:45 开卧室背景灯
name = "工作日早上开卧室背景灯"
enabled = True
# 工作日 Mon-Fri = [0,1,2,3,4]
schedule = {"time": "09:45", "weekdays": [0, 1, 2, 3, 4]}


async def run(home):
    await home.set("卧室背景灯", {"state": "ON", "brightness": 128})
