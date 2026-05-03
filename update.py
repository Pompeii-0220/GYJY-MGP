import json
import requests
from datetime import datetime, timezone, timedelta

with open("data.json", "r", encoding="utf-8") as f:
    data = json.load(f)

guide_prices = data["guide_prices"]
recipes = data["recipes"]
prod_speed = data["production_speed"]
category = data["category"]
wage_per_hour = data.get("wage_per_hour", {})

url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(url)
resp.raise_for_status()
retail_items = resp.json().get("rows", [])

# 终端品价格直接取API零售价
terminal_prices = {}
for item in retail_items:
    name = item.get("name", "")
    if name and name in guide_prices:
        terminal_prices[name] = item["retailPrice"]

# 初始化价格为终端品价格
prices = dict(terminal_prices)

# 构建反向消耗：原料->下游列表
consumers = {item: [] for item in guide_prices}
for prod, ingredients in recipes.items():
    for ing, amount in ingredients:
        consumers[ing].append((prod, amount))

# 计算依赖高度
all_items = list(guide_prices.keys())
height = {}
for item in all_items:
    height[item] = 0 if item in terminal_prices else -1

changed = True
while changed:
    changed = False
    for prod, ings in recipes.items():
        if height.get(prod, -1) >= 0:
            for ing, amt in ings:
                if height.get(ing, -1) < height[prod] + 1:
                    height[ing] = height[prod] + 1
                    changed = True

sorted_items = sorted(all_items, key=lambda x: height.get(x, 999))

# 按高度从低到高计算价格
for item in sorted_items:
    if item in prices:
        continue
    if item not in consumers:
        prices[item] = 1.0
        continue
    total_w = 0.0
    sum_wp = 0.0
    for down_prod, amt in consumers[item]:
        speed = prod_speed.get(down_prod, 0)
        if speed > 0 and down_prod in prices:
            w = speed * amt
            sum_wp += w * prices[down_prod]
            total_w += w
    prices[item] = round(sum_wp / total_w, 2) if total_w > 0 else 1.0

# 输出data_output.json
beijing_tz = timezone(timedelta(hours=8))
update_time = datetime.now(tz=beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

output = {
    "update_time": update_time,
    "items": [],
    "recipes": recipes,
    "prod_speed": prod_speed,
    "wage_per_hour": wage_per_hour,
    "category": category,
    "terminal_prices": terminal_prices
}
for item in guide_prices:
    output["items"].append({
        "name": item,
        "price": prices[item],
        "cat": category.get(item, "")
    })

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

# 生成简单的index.html（无需改动，保持以前的即可）
with open("index.html", "w", encoding="utf-8") as f:
    f.write("""<!DOCTYPE html><html lang="zh-CN">... (保留原本HTML，包含滑块和app.js引用) ...</html>""")
