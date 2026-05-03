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

# 1. 获取终端零售价
terminal_price = {}
for item in retail_items:
    name = item.get("name", "")
    if name and name in guide_prices:
        terminal_price[name] = item["retailPrice"]

# 2. 构建消耗关系（原料 -> 下游列表）
consumers = {item: [] for item in guide_prices}
for prod, ingredients in recipes.items():
    for ing, amount in ingredients:
        consumers[ing].append((prod, amount))

all_items = list(guide_prices.keys())

# 3. 计算物理需求（只限制终端品的产能，原料不限制）
demand = {item: 0.0 for item in all_items}
# 终端品的需求 = 该终端品的生产速度（最大产能）
for name in terminal_price:
    if name in prod_speed:
        demand[name] = prod_speed[name]

# 迭代传导：每个原料的需求 = sum(下游需求 × 单位消耗量)，不施加原料自身的产能上限
while True:
    new_demand = dict(demand)
    for ing in all_items:
        if ing in consumers and ing not in terminal_price:  # 非终端品才自动计算
            total = 0.0
            for down_prod, amt in consumers[ing]:
                total += demand.get(down_prod, 0) * amt
            new_demand[ing] = total
    # 检查收敛
    changed = False
    for k in all_items:
        if abs(new_demand[k] - demand[k]) > 0.001:
            changed = True
            break
    if not changed:
        break
    demand = new_demand

# 4. 按依赖高度从终端向上游计算价格
height = {item: 0 if item in terminal_price else -1 for item in all_items}
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

prices = dict(terminal_price)
for item in sorted_items:
    if item in prices:
        continue
    if item not in consumers:
        prices[item] = 1.0
        continue
    total_w = 0.0
    sum_wp = 0.0
    for down_prod, amt in consumers[item]:
        w = demand.get(down_prod, 0) * amt  # 下游消耗该原料的速率
        if w > 0 and down_prod in prices:
            sum_wp += w * prices[down_prod]
            total_w += w
    prices[item] = round(sum_wp / total_w, 2) if total_w > 0 else 1.0

# 5. 生成 data_output.json
beijing_tz = timezone(timedelta(hours=8))
update_time = datetime.now(tz=beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

output = {
    "update_time": update_time,
    "items": [],
    "recipes": recipes,
    "prod_speed": prod_speed,
    "wage_per_hour": wage_per_hour,
    "category": category,
    "retail_prices": terminal_price
}
for item in guide_prices:
    output["items"].append({
        "name": item,
        "price": prices[item],
        "retail_price": terminal_price.get(item),
        "cat": category.get(item, "")
    })

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

# 6. 生成网页（与之前极限利润展示相同，略，保持与之前一致的 HTML 即可）
#      这里复用上一条回复中的 HTML 生成代码，只修改 update_time 和删除其他无关部分
#      为了简洁，此处不重复贴出完整 HTML，你可以直接沿用之前统一倍率时的网页模板，
#      因为极限利润的计算方式没变，只是 data_output.json 中的价格变成了加权价格。
