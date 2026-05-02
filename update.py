import json
import requests
from datetime import datetime

# 1. 读取本地数据
with open("data.json", "r", encoding="utf-8") as f:
    data = json.load(f)

guide_prices = data["guide_prices"]
recipes = data["recipes"]
prod_speed = data["production_speed"]
category = data["category"]

# 2. 从 API 获取终端物品倍率（API 里的名称就是物品名，不再加“出售”前缀）
url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(url)
resp.raise_for_status()
retail_items = resp.json().get("rows", [])

known_multipliers = {}  # 直接已知倍率的物品（来自API）
for item in retail_items:
    api_name = item.get("name", "")
    if api_name and api_name in guide_prices:
        known_multipliers[api_name] = item["multiplier"]

print(f"✅ 从API获取到 {len(known_multipliers)} 个终端物品倍率")

# 3. 构建消耗关系（下游消耗了哪些上游原料）
consumers = {}
for product, ingredients in recipes.items():
    for ing, amount in ingredients:
        if ing not in consumers:
            consumers[ing] = []
        consumers[ing].append((product, amount))

# 4. 计算每个物品的“有效物理需求速率”（终端销量向上游传导）
#    先找出所有终端零售品（即 API 里有倍率的物品），它们在 prod_speed 中的速度就是终端销量
terminal_speed = {}
for name, mult in known_multipliers.items():
    if name in prod_speed:
        terminal_speed[name] = prod_speed[name]
    else:
        print(f"⚠️ 终端物品 {name} 缺少生产速度数据，跳过")

#    虚拟需求：每个物品因为下游终端销量而产生的每小时需求量
virtual_demand = {}
for item in guide_prices:
    virtual_demand[item] = 0.0

#    从终端开始，向上游累加需求
for term_name, speed in terminal_speed.items():
    virtual_demand[term_name] = max(virtual_demand[term_name], speed)

#    反复向上游传递，直到所有需求稳定
changed = True
while changed:
    changed = False
    for product, ingredients in recipes.items():
        if virtual_demand.get(product, 0) > 0:
            # 把 product 的需求按配方分摊到它的原料上
            for ing, amount_per in ingredients:
                # 原料 ing 因为 product 而产生的需求 = product 的需求 × 每产1个 product 消耗的 ing 数量
                added_demand = virtual_demand[product] * amount_per
                if added_demand > virtual_demand[ing]:
                    virtual_demand[ing] = added_demand
                    changed = True

# 5. 用物理需求速率计算所有物品的加权倍率
#    对于每个物品，倍率 = Σ (下游需求速率 × 下游倍率) / Σ (下游需求速率)
multipliers = {}
multipliers.update(known_multipliers)

all_items = list(guide_prices.keys())
changed = True
while changed:
    changed = False
    for item in all_items:
        if item in multipliers:
            continue
        if item not in consumers:
            multipliers[item] = 1.0
            changed = True
            continue

        downstream = consumers[item]
        total_demand = 0.0
        weighted_mult = 0.0
        for down_prod, amount_per in downstream:
            demand = virtual_demand.get(down_prod, 0)
            if demand > 0 and down_prod in multipliers:
                weighted_mult += demand * multipliers[down_prod]
                total_demand += demand
        if total_demand > 0:
            multipliers[item] = round(weighted_mult / total_demand, 4)
            changed = True

# 6. 计算最终价格
prices = {}
for item, base_price in guide_prices.items():
    mult = multipliers.get(item, 1.0)
    prices[item] = round(base_price * mult, 2)

# 7. 生成 HTML
update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

cat_order = [
    "电力与基础资源",
    "农场产品",
    "牧场产品",
    "加工中间品",
    "中央厨房产品",
    "时装/工业产品"
]
items_by_cat = {c: [] for c in cat_order}
for item, cat in category.items():
    if cat in items_by_cat:
        items_by_cat[cat].append(item)

html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>市场指导价</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f5f5f5; color: #1a1a1a; margin: 0; padding: 20px; }}
  .container {{ max-width: 900px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }}
  h1 {{ text-align: center; color: #2c3e50; margin-bottom: 10px; }}
  .update-time {{ text-align: center; color: #888; font-size: 14px; margin-bottom: 30px; }}
  .category {{ margin-bottom: 32px; }}
  .category h2 {{ background: #2c3e50; color: white; padding: 10px 15px; font-size: 18px; border-radius: 6px; margin: 0 0 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 15px; }}
  th, td {{ padding: 10px 8px; text-align: left; border-bottom: 1px solid #e0e0e0; }}
  th {{ background: #fafafa; font-weight: 600; color: #555; }}
  .price {{ font-weight: 600; color: #e67e22; }}
  .mult {{ color: #27ae60; font-size: 13px; margin-left: 6px; }}
</style>
</head>
<body>
<div class="container">
  <h1>🏭 零加成市场指导价</h1>
  <div class="update-time">更新时间：{update_time}</div>
"""

for cat in cat_order:
    items = items_by_cat.get(cat, [])
    if not items:
        continue
    html += f'<div class="category"><h2>{cat}</h2><table><tr><th>商品</th><th>指导价</th></tr>'
    for item in items:
        price = prices.get(item, "?")
        mult = multipliers.get(item, 1.0)
        mult_str = f'（倍率 {mult:.2f}）' if abs(mult - 1.0) > 0.001 else ""
        html += f'<tr><td>{item}</td><td class="price">{price} 元{mult_str}</td></tr>'
    html += '</table></div>'

html += """
</div>
</body>
</html>
"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print("✅ index.html 已生成")
