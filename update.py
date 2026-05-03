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
wage_per_hour = data.get("wage_per_hour", {})

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

# 4. 计算物理需求（终端销量向上游传导，迭代至收敛）
virtual_demand = {}
for item in guide_prices:
    virtual_demand[item] = 0.0
for name in known_multipliers:
    if name in prod_speed:
        virtual_demand[name] = prod_speed[name]

while True:
    new_demand = {}
    for item in guide_prices:
        if item in consumers:
            total = 0.0
            for down_prod, amount_per in consumers[item]:
                if virtual_demand.get(down_prod, 0) > 0:
                    total += virtual_demand[down_prod] * amount_per
            new_demand[item] = total
        else:
            new_demand[item] = virtual_demand[item]
    changed = False
    for k in guide_prices:
        if abs(new_demand[k] - virtual_demand[k]) > 0.001:
            changed = True
            break
    if not changed:
        break
    virtual_demand = new_demand

# 5. 按“依赖高度”自底向上计算倍率
all_items = list(guide_prices.keys())
height = {}
for item in all_items:
    if item in known_multipliers:
        height[item] = 0
    else:
        height[item] = -1

changed = True
while changed:
    changed = False
    for product, ingredients in recipes.items():
        if height.get(product, -1) >= 0:
            for ing, amount_per in ingredients:
                if height.get(ing, -1) < height[product] + 1:
                    height[ing] = height[product] + 1
                    changed = True

sorted_items = sorted(all_items, key=lambda x: height.get(x, 999))

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
        multipliers[item] = round(weighted_mult / total_demand, 4)
    else:
        multipliers[item] = 1.0

# 6. 最终价格
prices = {}
for item, base_price in guide_prices.items():
    mult = multipliers.get(item, 1.0)
    prices[item] = round(base_price * mult, 2)

# 7. 输出 data_output.json（供网页实时计算）
beijing_tz = timezone(timedelta(hours=8))
update_time = datetime.now(tz=beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

output = {
    "update_time": update_time,
    "items": [],
    "recipes": recipes,
    "prod_speed": prod_speed,
    "wage_per_hour": wage_per_hour,
    "category": category
}
for item in guide_prices:
    output["items"].append({
        "name": item,
        "base_price": guide_prices[item],
        "multiplier": multipliers.get(item, 1.0),
        "price": prices[item],
        "cat": category.get(item, "")
    })

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print("✅ data_output.json 已生成")

# 8. 生成 HTML（简洁版，只显示更新时间，内容由 JS 动态渲染）
html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>市场指导价与利润计算器</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background: #f5f5f5; margin: 0; padding: 20px; }}
  .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 25px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }}
  h1 {{ text-align: center; color: #2c3e50; }}
  .update-time {{ text-align: center; color: #888; font-size: 14px; margin-bottom: 25px; }}
  .controls {{ background: #f0f4ff; padding: 15px; border-radius: 8px; margin-bottom: 30px; display: flex; flex-wrap: wrap; gap: 15px; align-items: center; }}
  .controls label {{ font-weight: 600; margin-right: 5px; }}
  .controls input {{ width: 80px; padding: 5px; border: 1px solid #ccc; border-radius: 5px; }}
  .category {{ margin-bottom: 32px; }}
  .category h2 {{ background: #2c3e50; color: white; padding: 10px 15px; font-size: 18px; border-radius: 6px; margin: 0 0 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ padding: 8px 6px; text-align: left; border-bottom: 1px solid #e0e0e0; }}
  th {{ background: #fafafa; font-weight: 600; color: #555; }}
  .price {{ font-weight: 600; color: #e67e22; }}
  .profit {{ color: #27ae60; }}
  .limit {{ color: #e74c3c; font-weight: 600; }}
  @media (max-width: 600px) {{ .controls {{ flex-direction: column; align-items: flex-start; }} }}
</style>
</head>
<body>
<div class="container">
  <h1>🏭 零加成市场指导价 & 利润计算器</h1>
  <div class="update-time">数据更新时间：<span id="update-time"></span></div>
  <div class="controls">
    <label>生产加成% <input id="prod-bonus" type="number" value="0" step="1"></label>
    <label>销售加成% <input id="sale-bonus" type="number" value="0" step="1"></label>
    <label>管理减免% <input id="mgt-reduction" type="number" value="0" step="1"></label>
    <label>其他建筑总等级 <input id="other-levels" type="number" value="0" step="1"></label>
    <label>其他建筑总工资 <input id="other-wages" type="number" value="0" step="100"></label>
    <button onclick="renderAll()">刷新计算</button>
  </div>
  <div id="tables-container"></div>
</div>
<script src="app.js"></script>
</body>
</html>"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)
print("✅ index.html 已生成")

# 9. 生成 app.js（利润计算核心）
js_code = """
// 全局数据
let DATA = null;
let items = [], recipes, prodSpeed, wagePerHour, category, multipliers, prices;

// 加载数据
fetch('data_output.json')
  .then(r => r.json())
  .then(json => {
    DATA = json;
    document.getElementById('update-time').innerText = json.update_time;
    items = json.items;
    recipes = json.recipes;
    prodSpeed = json.prod_speed;
    wagePerHour = json.wage_per_hour || {};
    category = json.category;
    multipliers = {};
    prices = {};
    items.forEach(it => {
      multipliers[it.name] = it.multiplier;
      prices[it.name] = it.price;
    });
    renderAll();
  });

function getInput(id) {
  return parseFloat(document.getElementById(id).value) || 0;
}

// 计算某物品1级时的毛利（管理费=0）
function calcGrossProfit(itemName) {
  const price = prices[itemName] || 0;
  const speed1 = prodSpeed[itemName] || 0;
  if (speed1 === 0) return 0;
  const prodBonus = 1 + getInput('prod-bonus')/100;
  const saleBonus = 1 + getInput('sale-bonus')/100;
  const revenue = speed1 * price * prodBonus * saleBonus;

  // 原料成本
  let materialCost = 0;
  if (recipes[itemName]) {
    for (let [mat, amt] of recipes[itemName]) {
      const matPrice = prices[mat] || 0;
      materialCost += speed1 * amt * matPrice * prodBonus;
    }
  }

  const wage1 = wagePerHour[itemName] || 0;
  return revenue - materialCost - wage1;
}

// 迭代计算最高等级
function calcMaxLevel(itemName) {
  const wage1 = wagePerHour[itemName] || 0;
  if (wage1 === 0) return 0;

  const otherLevels = getInput('other-levels');
  const otherWages = getInput('other-wages');
  const mgtReduction = getInput('mgt-reduction');

  let level = 1;
  while (level < 10000) {
    const nextLevel = level + 1;
    const totalLevels = otherLevels + nextLevel;
    const mgtRate = totalLevels * 0.0058 * (1 - mgtReduction/100);
    const mgtCostNext = wage1 * nextLevel * mgtRate + otherWages * mgtRate;

    const totalLevelsCur = otherLevels + level;
    const mgtRateCur = totalLevelsCur * 0.0058 * (1 - mgtReduction/100);
    const mgtCostCur = wage1 * level * mgtRateCur + otherWages * mgtRateCur;

    const grossNext = calcGrossProfit(itemName) * nextLevel;
    const netNext = grossNext - mgtCostNext;
    const grossCur = calcGrossProfit(itemName) * level;
    const netCur = grossCur - mgtCostCur;

    if (netNext <= netCur) break;
    level = nextLevel;
  }
  return level;
}

// 极限利润
function calcLimitProfit(itemName) {
  const maxLevel = calcMaxLevel(itemName);
  if (maxLevel === 0) return 0;
  const gross = calcGrossProfit(itemName) * maxLevel;
  const otherLevels = getInput('other-levels');
  const otherWages = getInput('other-wages');
  const mgtReduction = getInput('mgt-reduction');
  const totalLevels = otherLevels + maxLevel;
  const mgtRate = totalLevels * 0.0058 * (1 - mgtReduction/100);
  const wage1 = wagePerHour[itemName] || 0;
  const mgtCost = wage1 * maxLevel * mgtRate + otherWages * mgtRate;
  return Math.round(gross - mgtCost);
}

// 渲染表格
function renderAll() {
  const container = document.getElementById('tables-container');
  const cats = ["电力与基础资源","农场产品","牧场产品","加工中间品","中央厨房产品","时装/工业产品"];
  let html = '';
  for (const c of cats) {
    const itemsInCat = items.filter(it => category[it.name] === c);
    if (!itemsInCat.length) continue;
    html += `<div class="category"><h2>${c}</h2><table>
      <tr><th>商品</th><th>指导价</th><th>每级时利润</th><th>最高等级</th><th>极限利润</th></tr>`;
    for (const it of itemsInCat) {
      const profit = Math.round(calcGrossProfit(it.name));
      const maxLv = calcMaxLevel(it.name);
      const limitProfit = calcLimitProfit(it.name);
      html += `<tr>
        <td>${it.name}</td>
        <td class="price">${it.price} 元（倍率 ${it.multiplier.toFixed(2)}）</td>
        <td class="profit">${profit} 元/h</td>
        <td>${maxLv} 级</td>
        <td class="limit">${limitProfit} 元/h</td>
      </tr>`;
    }
    html += '</table></div>';
  }
  container.innerHTML = html;
}
"""

with open("app.js", "w", encoding="utf-8") as f:
    f.write(js_code)
print("✅ app.js 已生成")
