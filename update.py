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

# 终端品价格直接取 API 的零售价
terminal_prices = {}
for item in retail_items:
    name = item.get("name", "")
    if name and name in guide_prices:
        terminal_prices[name] = item["retailPrice"]

prices = dict(terminal_prices)

# 构建消耗关系：原料 -> 下游列表
consumers = {item: [] for item in guide_prices}
for prod, ingredients in recipes.items():
    for ing, amount in ingredients:
        consumers[ing].append((prod, amount))

# 计算依赖高度（终端品高度为 0，向上递推）
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

# 按高度顺序计算非终端品价格（下游价格已知后算上游）
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

# 输出 data_output.json（供网页使用）
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

# 生成完整的 index.html（含所有滑块和 app.js 引用）
html_content = f"""<!DOCTYPE html>
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
    f.write(html_content)

# 生成 app.js（利润计算核心）
app_js = """
let DATA, items=[], recipes, prodSpeed, wagePerHour, category, prices;

fetch('data_output.json').then(r=>r.json()).then(json=>{
    DATA = json;
    document.getElementById('update-time').innerText = json.update_time;
    items = json.items;
    recipes = json.recipes;
    prodSpeed = json.prod_speed;
    wagePerHour = json.wage_per_hour || {};
    category = json.category;
    prices = {};
    items.forEach(it => prices[it.name] = it.price);
    renderAll();
});

function getInput(id) { return parseFloat(document.getElementById(id).value)||0; }

function calcGrossProfit(itemName) {
    const speed = prodSpeed[itemName] || 0;
    if (!speed) return 0;
    const prodBonus = 1 + getInput('prod-bonus')/100;
    const saleBonus = 1 + getInput('sale-bonus')/100;
    const price = prices[itemName] || 0;
    const revenue = speed * price * (itemName.startsWith("出售") ? saleBonus : 1) * prodBonus;
    let matCost = 0;
    if (recipes[itemName]) {
        for (let [mat, amt] of recipes[itemName]) {
            matCost += speed * amt * (prices[mat]||0) * prodBonus;
        }
    }
    const wage = wagePerHour[itemName] || 0;
    return revenue - matCost - wage;
}

function calcMaxLevel(itemName) {
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
        const grossNext = calcGrossProfit(itemName) * next;
        const netNext = grossNext - costNext;

        const totalCur = otherLv + lv;
        const mgrCur = totalCur * 0.0058 * (1-reduce);
        const costCur = wage * lv * mgrCur + otherWage * mgrCur;
        const grossCur = calcGrossProfit(itemName) * lv;
        const netCur = grossCur - costCur;

        if (netNext <= netCur) break;
        lv = next;
    }
    return lv;
}

function calcLimitProfit(itemName) {
    const maxLv = calcMaxLevel(itemName);
    if (!maxLv) return 0;
    const wage = wagePerHour[itemName]||0;
    const otherLv = getInput('other-levels');
    const otherWage = getInput('other-wages');
    const reduce = getInput('mgt-reduction')/100;
    const total = otherLv + maxLv;
    const mgr = total * 0.0058 * (1-reduce);
    const cost = wage * maxLv * mgr + otherWage * mgr;
    return Math.round(calcGrossProfit(itemName) * maxLv - cost);
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
            const gp = calcGrossProfit(it.name);
            const maxLv = calcMaxLevel(it.name);
            const limit = calcLimitProfit(it.name);
            html += `<tr>
              <td>${it.name}</td>
              <td>${it.price.toFixed(2)} 元</td>
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

print("✅ 网站文件已全部生成")
