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

# 1. 获取终端零售价和倍率，同时记录终端品名称
terminal_mult = {}
terminal_price = {}
for item in retail_items:
    name = item.get("name", "")
    if name and name in guide_prices:
        terminal_mult[name] = item["multiplier"]
        terminal_price[name] = item["retailPrice"]

# 2. 构建消耗关系（下游→上游）
consumers = {item: [] for item in guide_prices}
for prod, ingredients in recipes.items():
    for ing, amount in ingredients:
        consumers[ing].append((prod, amount))

all_items = list(guide_prices.keys())

# 3. 计算物理需求（从终端出发，向上游传导，且受产能限制）
demand = {item: 0.0 for item in all_items}
# 终端品的需求初始值 = 它们的生产速度（被限制在最大值）
for name in terminal_mult:
    if name in prod_speed:
        demand[name] = prod_speed[name]   # 终端品自身需求就是其最大产能

# 迭代直至收敛
while True:
    new_demand = dict(demand)
    for ing in all_items:
        if ing in consumers:
            total_required = 0.0
            for down_prod, amount_per in consumers[ing]:
                # 下游产品的实际产量（产能限制后）
                down_output = demand.get(down_prod, 0)
                total_required += down_output * amount_per
            # 原料的需求量不能超过它自己的产能（如果它也作为中间品有生产速度限制）
            capacity = prod_speed.get(ing, float('inf'))
            new_demand[ing] = min(total_required, capacity) if total_required > 0 else 0.0

    # 检查是否变化
    changed = False
    for k in all_items:
        if abs(new_demand[k] - demand[k]) > 0.001:
            changed = True
            break
    if not changed:
        break
    demand = new_demand

# 4. 基于需求权重，计算每个物品的价格（终端品价格已知，非终端品加权）
prices = dict(terminal_price)
# 按依赖高度排序（终端为0）
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

for item in sorted_items:
    if item in prices:
        continue
    if item not in consumers:
        prices[item] = 1.0
        continue
    total_w = 0.0
    sum_wp = 0.0
    for down_prod, amt in consumers[item]:
        # 使用需求加权（不是产能），因为需求反映了终端真实拉动
        w = demand.get(down_prod, 0) * amt   # 下游消耗该原料的速率
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

# 6. 生成网页（展示指导价、每级时利润、极限利润，无输入要求）
html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>市场指导价</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background: #f5f5f5; margin: 0; padding: 20px; }}
  .container {{ max-width: 1000px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; }}
  h1 {{ text-align: center; color: #2c3e50; }}
  .info {{ text-align: center; color: #888; font-size: 14px; margin-bottom: 15px; }}
  .category {{ margin-bottom: 28px; }}
  .category h2 {{ background: #2c3e50; color: white; padding: 8px 15px; font-size: 18px; border-radius: 6px; margin: 0 0 10px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #e0e0e0; }}
  th {{ background: #fafafa; }}
  .price {{ font-weight: 600; color: #e67e22; }}
  .profit {{ color: #27ae60; }}
  .limit {{ color: #e74c3c; font-weight: 600; }}
</style>
</head>
<body>
<div class="container">
  <h1>🏭 零加成市场指导价</h1>
  <div class="info">更新时间：{update_time}</div>
  <div id="tables-container"></div>
</div>
<script>
let DATA, items, recipes, prodSpeed, wagePerHour, category, retailPrices, prices;

fetch('data_output.json').then(r=>r.json()).then(json=>{{
    DATA = json;
    items = json.items;
    recipes = json.recipes;
    prodSpeed = json.prod_speed;
    wagePerHour = json.wage_per_hour;
    category = json.category;
    retailPrices = json.retail_prices;
    prices = {{}};
    items.forEach(it => prices[it.name] = it.price);
    renderAll();
}});

function calcGrossProfit(itemName) {{
    const speed = prodSpeed[itemName] || 0;
    if (!speed) return 0;
    const price = prices[itemName] || 0;
    const retailPrice = retailPrices[itemName];
    const revenue = speed * (retailPrice ? retailPrice : price);
    let matCost = 0;
    if (recipes[itemName]) {{
        for (let [mat, amt] of recipes[itemName]) {{
            matCost += speed * amt * (prices[mat] || 0);
        }}
    }}
    const wage = wagePerHour[itemName] || 0;
    return revenue - matCost - wage;
}}

function calcMaxLevel(itemName) {{
    const wage = wagePerHour[itemName] || 0;
    if (!wage) return 0;
    let lv = 1;
    while (lv < 5000) {{
        const next = lv + 1;
        const mgtNext = next * 0.0058 * wage * next;
        const netNext = calcGrossProfit(itemName) * next - mgtNext;
        const mgtCur = lv * 0.0058 * wage * lv;
        const netCur = calcGrossProfit(itemName) * lv - mgtCur;
        if (netNext <= netCur) break;
        lv = next;
    }}
    return lv;
}}

function calcLimitProfit(itemName) {{
    const maxLv = calcMaxLevel(itemName);
    if (!maxLv) return 0;
    const wage = wagePerHour[itemName] || 0;
    const mgt = maxLv * 0.0058 * wage * maxLv;
    return Math.round(calcGrossProfit(itemName) * maxLv - mgt);
}}

function renderAll() {{
    const cats = ["电力与基础资源","农场产品","牧场产品","加工中间品","中央厨房产品","时装/工业产品"];
    let html = '';
    for (let c of cats) {{
        const list = items.filter(i=>category[i.name]===c);
        if (!list.length) continue;
        html += `<div class="category"><h2>${{c}}</h2><table>
          <tr><th>商品</th><th>指导价</th><th>每级时利润</th><th>最高等级</th><th>极限利润</th></tr>`;
        for (let it of list) {{
            const gp = Math.round(calcGrossProfit(it.name));
            const maxLv = calcMaxLevel(it.name);
            const limit = calcLimitProfit(it.name);
            html += `<tr>
              <td>${{it.name}}</td>
              <td class="price">${{it.price.toFixed(2)}} 元</td>
              <td class="profit">${{gp}} 元/h</td>
              <td>${{maxLv}} 级</td>
              <td class="limit">${{limit}} 元/h</td>
            </tr>`;
        }}
        html += '</table></div>';
    }}
    document.getElementById('tables-container').innerHTML = html;
}}
</script>
</body>
</html>"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print("✅ 已修正产能限制，饲料权重恢复正常")
