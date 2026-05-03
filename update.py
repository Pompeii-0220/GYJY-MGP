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

# 获取终端零售价
retail_price_raw = {}
for item in retail_items:
    name = item.get("name", "")
    if name and name in guide_prices:
        retail_price_raw[name] = item["retailPrice"]

# 我们将利润率设为可调，这里不用固定，生成数据时终端指导价先用零售价（利润率0%）
# 前端会根据滑块动态调整
prices_base = dict(retail_price_raw)   # 初始等于零售价

# 构建下游关系
consumers = {item: [] for item in guide_prices}
for prod, ingredients in recipes.items():
    for ing, amount in ingredients:
        consumers[ing].append((prod, amount))

all_items = list(guide_prices.keys())
height = {item: 0 if item in retail_price_raw else -1 for item in all_items}
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

prices = dict(prices_base)
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

# 输出基础数据
beijing_tz = timezone(timedelta(hours=8))
update_time = datetime.now(tz=beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

output = {
    "update_time": update_time,
    "items": [],
    "recipes": recipes,
    "prod_speed": prod_speed,
    "wage_per_hour": wage_per_hour,
    "category": category,
    "retail_prices": retail_price_raw
}
for item in guide_prices:
    retail_price_val = retail_price_raw.get(item)
    output["items"].append({
        "name": item,
        "base_price": prices[item],   # 利润率0%时的价格
        "retail_price": retail_price_val,
        "cat": category.get(item, "")
    })

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

# 生成网页
html_content = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>市场指导价与利润计算器</title>
<style>
  body { font-family: -apple-system, sans-serif; background: #f5f5f5; margin: 0; padding: 20px; }
  .container { max-width: 1200px; margin: 0 auto; background: white; padding: 25px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }
  h1 { text-align: center; color: #2c3e50; }
  .update-time { text-align: center; color: #888; font-size: 14px; margin-bottom: 25px; }
  .controls { background: #f0f4ff; padding: 15px; border-radius: 8px; margin-bottom: 30px; display: flex; flex-wrap: wrap; gap: 15px; align-items: center; }
  .controls label { font-weight: 600; margin-right: 5px; }
  .controls input { width: 80px; padding: 5px; border: 1px solid #ccc; border-radius: 5px; }
  .category { margin-bottom: 32px; }
  .category h2 { background: #2c3e50; color: white; padding: 10px 15px; font-size: 18px; border-radius: 6px; margin: 0 0 12px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { padding: 8px 6px; text-align: left; border-bottom: 1px solid #e0e0e0; }
  th { background: #fafafa; font-weight: 600; color: #555; }
  .price { font-weight: 600; color: #e67e22; }
  .profit { color: #27ae60; }
  .limit { color: #e74c3c; font-weight: 600; }
  @media (max-width: 600px) { .controls { flex-direction: column; align-items: flex-start; } }
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
    <label>其他建筑总等级 <input id="other-levels" type="number" value="500" step="1"></label>
    <label>其他建筑总工资 <input id="other-wages" type="number" value="50000" step="100"></label>
    <label>销售利润率% <input id="margin" type="number" value="5" step="0.5"></label>
    <button onclick="renderAll()">刷新计算</button>
  </div>
  <div id="tables-container"></div>
</div>
<script src="app.js"></script>
</body>
</html>"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_content)

app_js = """
let DATA, items=[], recipes, prodSpeed, wagePerHour, category, retailPrices;

fetch('data_output.json').then(r=>r.json()).then(json=>{
    DATA = json;
    document.getElementById('update-time').innerText = json.update_time;
    items = json.items;
    recipes = json.recipes;
    prodSpeed = json.prod_speed;
    wagePerHour = json.wage_per_hour || {};
    category = json.category;
    retailPrices = json.retail_prices || {};
    renderAll();
});

function getInput(id) { return parseFloat(document.getElementById(id).value)||0; }

// 根据当前利润率计算所有物品的实时价格
function getPrices() {
    const margin = getInput('margin') / 100;  // 销售利润率
    let p = {};
    // 先复制终端品价格
    for (let name in retailPrices) {
        p[name] = retailPrices[name] * (1 - margin);
    }
    // 非终端品需要根据下游价格实时计算（这里简化：使用已有的base价格按比例缩放？）
    // 但base价格是用0利润率算的，当margin变化时，所有上游价格应该重新加权。
    // 为了简单且保证利润平衡，我们直接用利润率修改终端品价格，然后重新做一次加权。
    // 这里我们在前端重新计算所有物品价格以保持准确性。
    // 构建consumers
    let consumers = {};
    for (let prod in recipes) {
        for (let [mat, amt] of recipes[prod]) {
            if (!consumers[mat]) consumers[mat] = [];
            consumers[mat].push([prod, amt]);
        }
    }
    // 计算高度
    let height = {};
    for (let item of items) height[item.name] = (item.name in retailPrices) ? 0 : -1;
    let changed = true;
    while (changed) {
        changed = false;
        for (let prod in recipes) {
            if (height[prod] >= 0) {
                for (let [mat, amt] of recipes[prod]) {
                    if (height[mat] < height[prod] + 1) {
                        height[mat] = height[prod] + 1;
                        changed = true;
                    }
                }
            }
        }
    }
    let sorted = items.map(i=>i.name).sort((a,b)=>height[a]-height[b]);
    for (let name of sorted) {
        if (name in p) continue;
        let totalW = 0, sumWP = 0;
        if (consumers[name]) {
            for (let [down, amt] of consumers[name]) {
                let speed = prodSpeed[down] || 0;
                if (speed > 0 && down in p) {
                    let w = speed * amt;
                    sumWP += w * p[down];
                    totalW += w;
                }
            }
        }
        p[name] = totalW > 0 ? sumWP / totalW : 1.0;
    }
    return p;
}

function calcGrossProfit(itemName, prices) {
    const speed = prodSpeed[itemName] || 0;
    if (!speed) return 0;
    const prodBonus = 1 + getInput('prod-bonus')/100;
    const saleBonus = 1 + getInput('sale-bonus')/100;
    const retailPrice = retailPrices[itemName];
    const price = prices[itemName];
    const revenue = speed * (retailPrice ? retailPrice : price) * (itemName.startsWith("出售") ? saleBonus : 1) * prodBonus;
    let matCost = 0;
    if (recipes[itemName]) {
        for (let [mat, amt] of recipes[itemName]) {
            matCost += speed * amt * (prices[mat] || 0) * prodBonus;
        }
    }
    const wage = wagePerHour[itemName] || 0;
    return revenue - matCost - wage;
}

function calcMaxLevel(itemName, prices) {
    const wage = wagePerHour[itemName] || 0;
    if (!wage) return 0;
    const otherLv = getInput('other-levels');
    const otherWage = getInput('other-wages');
    const reduce = getInput('mgt-reduction')/100;
    let lv = 1;
    while (lv < 5000) {
        const next = lv+1;
        const totalNext = otherLv + next;
        const mgrNext = totalNext * 0.0058 * (1-reduce);
        const costNext = wage * next * mgrNext + otherWage * mgrNext;
        const grossNext = calcGrossProfit(itemName, prices) * next;
        const netNext = grossNext - costNext;
        const totalCur = otherLv + lv;
        const mgrCur = totalCur * 0.0058 * (1-reduce);
        const costCur = wage * lv * mgrCur + otherWage * mgrCur;
        const grossCur = calcGrossProfit(itemName, prices) * lv;
        const netCur = grossCur - costCur;
        if (netNext <= netCur) break;
        lv = next;
    }
    return lv;
}

function calcLimitProfit(itemName, prices) {
    const maxLv = calcMaxLevel(itemName, prices);
    if (!maxLv) return 0;
    const wage = wagePerHour[itemName]||0;
    const otherLv = getInput('other-levels');
    const otherWage = getInput('other-wages');
    const reduce = getInput('mgt-reduction')/100;
    const total = otherLv + maxLv;
    const mgr = total * 0.0058 * (1-reduce);
    const cost = wage * maxLv * mgr + otherWage * mgr;
    return Math.round(calcGrossProfit(itemName, prices) * maxLv - cost);
}

function renderAll() {
    const prices = getPrices();
    const cats = ["电力与基础资源","农场产品","牧场产品","加工中间品","中央厨房产品","时装/工业产品"];
    let html = '';
    for (let c of cats) {
        const list = items.filter(i=>category[i.name]===c);
        if (!list.length) continue;
        html += `<div class="category"><h2>${c}</h2><table>
          <tr><th>商品</th><th>指导价</th><th>每级时利润</th><th>最高等级</th><th>极限利润</th></tr>`;
        for (let it of list) {
            const gp = calcGrossProfit(it.name, prices);
            const maxLv = calcMaxLevel(it.name, prices);
            const limit = calcLimitProfit(it.name, prices);
            html += `<tr>
              <td>${it.name}</td>
              <td>${prices[it.name].toFixed(2)} 元</td>
              <td>${Math.round(gp)} 元/h</td>
              <td>${maxLv} 级</td>
              <td class="limit">${limit} 元/h</td>
            </tr>`;
        }
        html += '</table></div>';
    }
    document.getElementById('tables-container').innerHTML = html;
}
"""

with open("app.js", "w", encoding="utf-8") as f:
    f.write(app_js)

print("✅ 网站文件已生成，销售利润率滑块已启用")
