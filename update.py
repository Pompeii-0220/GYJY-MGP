import json
import requests
from datetime import datetime, timezone, timedelta

with open("data.json", "r", encoding="utf-8") as f:
    data = json.load(f)

guide_prices = data["guide_prices"]
prod_speed = data["production_speed"]
category = data["category"]
wage_per_hour = data.get("wage_per_hour", {})

url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(url)
resp.raise_for_status()
retail_items = resp.json().get("rows", [])

# 1. 计算终端品加权平均倍率
total_weight = 0.0
sum_mult = 0.0
for item in retail_items:
    name = item.get("name", "")
    if name in guide_prices and name in prod_speed:
        mult = item["multiplier"]
        speed = prod_speed[name]
        sum_mult += mult * speed
        total_weight += speed

unified_mult = sum_mult / total_weight if total_weight > 0 else 1.0

# 2. 所有价格 = 均衡指导价 × 统一倍率
prices = {}
for item, bp in guide_prices.items():
    prices[item] = round(bp * unified_mult, 2)

# 3. 终端零售价
retail_prices_api = {}
for item in retail_items:
    name = item.get("name", "")
    if name in guide_prices:
        retail_prices_api[name] = item["retailPrice"]

# 4. 输出数据
beijing_tz = timezone(timedelta(hours=8))
update_time = datetime.now(tz=beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

output = {
    "update_time": update_time,
    "unified_multiplier": round(unified_mult, 4),
    "items": [],
    "recipes": data["recipes"],
    "prod_speed": prod_speed,
    "wage_per_hour": wage_per_hour,
    "category": category,
    "retail_prices": retail_prices_api
}
for item in guide_prices:
    output["items"].append({
        "name": item,
        "price": prices[item],
        "retail_price": retail_prices_api.get(item),
        "cat": category.get(item, "")
    })

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

# 5. 生成网页
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
  <div class="info">更新时间：{update_time}　｜　统一市场倍率：{unified_mult:.2f}</div>
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

print("✅ 统一倍率网页已生成，数据不会爆炸")
