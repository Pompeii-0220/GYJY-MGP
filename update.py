import json
import requests
from datetime import datetime, timezone, timedelta

# 1. 读取本地数据
with open("data.json", "r", encoding="utf-8") as f:
    data = json.load(f)

guide_prices = data["guide_prices"]
recipes = data["recipes"]
prod_speed = data["production_speed"]
category = data["category"]

# 2. 从 API 获取终端物品倍率
url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(url)
resp.raise_for_status()
retail_items = resp.json().get("rows", [])

known_multipliers = {}
for item in retail_items:
    api_name = item.get("name", "")
    if api_name and api_name in guide_prices:
        known_multipliers[api_name] = item["multiplier"]

print(f"✅ 从API获取到 {len(known_multipliers)} 个终端物品倍率")

# 3. 构建消耗关系
consumers = {}
for product, ingredients in recipes.items():
    for ing, amount in ingredients:
        if ing not in consumers:
            consumers[ing] = []
        consumers[ing].append((product, amount))

# 4. 计算物理需求（终端销量向上游传导，所有分支累加）
virtual_demand = {}
for item in guide_prices:
    virtual_demand[item] = 0.0
for name in known_multipliers:
    if name in prod_speed:
        virtual_demand[name] = prod_speed[name]

# 反复迭代直到需求停止增长
while True:
    updated = False
    for product, ingredients in recipes.items():
        if virtual_demand.get(product, 0) > 0:
            for ing, amount_per in ingredients:
                added = virtual_demand[product] * amount_per
                # 累加到原料上（每次迭代都累加）
                virtual_demand[ing] = virtual_demand.get(ing, 0.0) + added
                updated = True
    if not updated:
        break

# 5. 按“依赖高度”自底向上计算倍率（保证下游先算完）
#    先找出每个物品的“高度”（最长路径长度到终端品）
height = {}
for item in guide_prices:
    if item in known_multipliers:
        height[item] = 0   # 终端品高度为0
    else:
        height[item] = -1

changed = True
while changed:
    changed = False
    for product, ingredients in recipes.items():
        for ing, amount_per in ingredients:
            if height.get(ing, -1) < height.get(product, -1) + 1:
                height[ing] = height.get(product, 0) + 1
                changed = True

# 按高度从低到高排序（高度越低的越靠近终端，应该先算）
sorted_items = sorted(all_items, key=lambda x: height.get(x, 999))

# 开始计算倍率
multipliers = {}
multipliers.update(known_multipliers)

for item in sorted_items:
    if item in multipliers:
        continue
    if item not in consumers:
        multipliers[item] = 1.0
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
        # 保留你的调试信息，方便检查结果
        if item == "谷物":
            print(f"\n🔍 谷物倍率 debug (修复后):")
            print(f"  下游列表: {downstream}")
            for d, a in downstream:
                dmd = virtual_demand.get(d, 0)
                mlt = multipliers.get(d, "未知")
                print(f"    - {d}: demand={dmd}, mult={mlt}, 单位消耗={a}")
            print(f"  加权总和: {weighted_mult}, 总需求: {total_demand}")
            print(f"  => 谷物最终倍率: {weighted_mult/total_demand:.4f}")
        multipliers[item] = round(weighted_mult / total_demand, 4)
    else:
        multipliers[item] = 1.0

# 6. 最终价格
prices = {}
for item, base_price in guide_prices.items():
    mult = multipliers.get(item, 1.0)
    prices[item] = round(base_price * mult, 2)

# 7. 生成 HTML（北京时间）
beijing_tz = timezone(timedelta(hours=8))
update_time = datetime.now(tz=beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

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
