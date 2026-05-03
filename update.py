import json
import requests
from datetime import datetime, timezone, timedelta

# 读取数据
with open("data.json", "r", encoding="utf-8") as f:
    data = json.load(f)

guide_prices = data["guide_prices"]
recipes = data["recipes"]
prod_speed = data["production_speed"]
category = data["category"]
wage_per_hour = data.get("wage_per_hour", {})

# 获取API倍率
url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(url)
resp.raise_for_status()
rows = resp.json().get("rows", [])

# 获取终端品的倍率（API中每个item）
multipliers_api = {}
for item in rows:
    name = item.get("name", "")
    if name and name in guide_prices:
        multipliers_api[name] = item["multiplier"]

# 计算所有物品的倍率（加权反推）
# 构建反向消耗
consumers_map = {item: [] for item in guide_prices}
for prod, ingredients in recipes.items():
    for ing, amount in ingredients:
        consumers_map[ing].append((prod, amount))

all_items = list(guide_prices.keys())

# 初始化倍率为终端品的API倍率，其他未知
multipliers = {}
for name in multipliers_api:
    multipliers[name] = multipliers_api[name]

# 计算高度
height = {}
for name in all_items:
    height[name] = 0 if name in multipliers_api else -1

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

# 按高度顺序计算未知倍率（加权）
for item in sorted_items:
    if item in multipliers:
        continue
    if item not in consumers_map:
        multipliers[item] = 1.0
        continue
    tw = 0.0
    sw = 0.0
    for down_prod, amt in consumers_map[item]:
        speed = prod_speed.get(down_prod, 0)
        if speed > 0 and down_prod in multipliers:
            w = speed * amt
            sw += w * multipliers[down_prod]
            tw += w
    multipliers[item] = round(sw / tw, 4) if tw > 0 else 1.0

# 计算指导价 = 均衡指导价 × 倍率
prices = {}
for item in guide_prices:
    mult = multipliers.get(item, 1.0)
    prices[item] = round(guide_prices[item] * mult, 2)

# 输出 data_output.json 供前端使用
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
        "price": prices[item],
        "multiplier": multipliers.get(item, 1.0),
        "cat": category.get(item, "")
    })

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

# 生成 index.html  (包含极限利润与最高等级的计算，默认其他建筑为0)
html = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>市场指导价</title>
<style>
  body { font-family: -apple-system, sans-serif; background: #f5f5f5; margin: 0; padding: 20px; }
  .container { max-width: 1100px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }
  h1 { text-align: center; color: #2c3e50; }
  .update-time { text-align: center; color: #888; font-size: 14px; margin-bottom: 20px; }
  .category { margin-bottom: 28px; }
  .category h2 { background: #2c3e50; color: white; padding: 8px 15px; font-size: 18px; border-radius: 6px; margin: 0 0 10px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { padding: 8px; text-align: left; border-bottom: 1px solid #e0e0e0; }
  th { background: #fafafa; font-weight: 600; }
  .price { font-weight: 600; color: #e67e22; }
  .profit { color: #27ae60; }
  .limit { color: #e74c3c; font-weight: 600; }
</style>
</head>
<body>
<div class="container">
  <h1>🏭 零加成市场指导价</h1>
  <div class="update-time">更新时间：<span id="update-time"></span></div>
  <div id="tables-container"></div>
</div>
<script>
let DATA, items, recipes, prodSpeed, wagePerHour, category;

fetch('data_output.json').then(r=>r.json()).then(json=>{
    DATA = json;
    document.getElementById('update-time').innerText = json.update_time;
    items = json.items;
    recipes = json.recipes;
    prodSpeed = json.prod_speed;
    wagePerHour = json.wage_per_hour || {};
    category = json.category;
    renderAll();
});

function calcGrossProfit(itemName) {
    const price = items.find(i=>i.name===itemName).price;
    const speed = prodSpeed[itemName] || 0;
    if (!speed) return 0;
    let revenue = speed * price;
    let matCost = 0;
    if (recipes[itemName]) {
        for (let [mat, amt] of recipes[itemName]) {
            const matPrice = items.find(i=>i.name===mat).price || 0;
            matCost += speed * amt * matPrice;
        }
    }
    const wage = wagePerHour[itemName] || 0;
    return revenue - matCost - wage;
}

function calcMaxLevelAndLimit(itemName) {
    const wage = wagePerHour[itemName] || 0;
    if (!wage) return { level: 0, limitProfit: 0 };
    let level = 1;
    while (level < 5000) {
        const next = level + 1;
        const mgrRateNext = next * 0.0058;   // 管理费率 = 等级 * 0.58%，假设无其他建筑
        const mgrNext = wage * next * mgrRateNext;
        const grossNext = calcGrossProfit(itemName) * next;
        const netNext = grossNext - mgrNext;

        const mgrRateCur = level * 0.0058;
        const mgrCur = wage * level * mgrRateCur;
        const grossCur = calcGrossProfit(itemName) * level;
        const netCur = grossCur - mgrCur;

        if (netNext <= netCur) break;
        level = next;
    }
    const mgrRate = level * 0.0058;
    const mgr = wage * level * mgrRate;
    const limitProfit = Math.round(calcGrossProfit(itemName) * level - mgr);
    return { level: level, limitProfit: limitProfit };
}

function renderAll() {
    const cats = ["电力与基础资源","农场产品","牧场产品","加工中间品","中央厨房产品","时装/工业产品"];
    let html = '';
    for (let c of cats) {
        const list = items.filter(i=>category[i.name]===c);
        if (!list.length) continue;
        html += `<div class="category"><h2>${c}</h2><table>
          <tr><th>商品</th><th>指导价</th><th>每级时利润</th><th>最高等级</th><th>极限利润</th></tr>`;
        for (let it of list) {
            const profit = Math.round(calcGrossProfit(it.name));
            const {level, limitProfit} = calcMaxLevelAndLimit(it.name);
            html += `<tr>
              <td>${it.name}</td>
              <td class="price">${it.price.toFixed(2)} 元 (×${it.multiplier.toFixed(2)})</td>
              <td class="profit">${profit} 元/h</td>
              <td>${level} 级</td>
              <td class="limit">${limitProfit} 元/h</td>
            </tr>`;
        }
        html += '</table></div>';
    }
    document.getElementById('tables-container').innerHTML = html;
}
</script>
</body>
</html>
"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print("✅ 网站文件已生成，使用均衡指导价×市场倍率，极限利润基于单建筑独立计算")
