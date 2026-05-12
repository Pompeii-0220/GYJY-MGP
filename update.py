import json
import requests
from datetime import datetime, timezone, timedelta

# ---------- 加载静态数据 ----------
with open("game_data.json", "r", encoding="utf-8") as f:
    gd = json.load(f)

prod_data = gd["production"]
retail_data = gd["retail"]
mgmt_rate = gd["management_rate"]

# ---------- 抓取 API 数据 ----------
api_url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(api_url)
resp.raise_for_status()
api_json = resp.json()
retail_rows = api_json.get("rows", [])

# 建立零售品名称 -> 零售价 映射
retail_price_map = {item["name"]: item["retailPrice"] for item in retail_rows}

# ---------- 构建依赖图（用于后续加权，这里先保留） ----------
# 实际上加权计价在 compute_prices 中会用到 prod_data 的配方，所以不需要额外的依赖图

# ---------- 计算指导价（给定毛利率） ----------
def compute_prices(margin, retail_price_map):
    prices = {}
    # 先设定零售品的“进价”
    for prod_name, retail_price in retail_price_map.items():
        prices[prod_name] = round(retail_price * (1 - margin), 2)

    # 迭代计算中间品价格（加权平均所有下游需求）
    changed = True
    while changed:
        changed = False
        for product, info in prod_data.items():
            if product in prices:
                continue
            recipe = info["recipe"]
            batch = info.get("batch", 1)
            weight_sum = 0.0
            val_sum = 0.0
            all_known = True
            for ing, amount in recipe.items():
                per_unit = amount / batch
                if ing not in prices:
                    all_known = False
                    break
                # 下游的消耗速率 = 产品时产 × 单位消耗
                output_per_hour = prod_data[product]["output"]
                demand = output_per_hour * per_unit
                weight_sum += demand
                val_sum += demand * prices[ing]
            if all_known and weight_sum > 0:
                new_price = round(val_sum / weight_sum, 2)
                if product not in prices or prices[product] != new_price:
                    prices[product] = new_price
                    changed = True
    return prices

# ---------- 计算一个建筑（或零售品）的极限利润 ----------
def calc_limit_profit(item_name, margin, prices):
    # 如果是生产建筑
    if item_name in prod_data:
        info = prod_data[item_name]
        wage = info["wage"]
        output = info["output"]
        product_price = prices.get(item_name, 1.0)
        recipe = info["recipe"]
        batch = info.get("batch", 1)
        mat_cost = 0.0
        for ing, amount in recipe.items():
            per_unit = amount / batch
            mat_cost += per_unit * prices.get(ing, 1.0)
        gross_profit = output * product_price - output * mat_cost - wage
        if gross_profit <= 0:
            return 0, 0, 0
        n_opt = int(gross_profit / (2 * wage * mgmt_rate) - 0.5)
        if n_opt < 1:
            n_opt = 1
        limit = gross_profit * n_opt - wage * (n_opt ** 2) * mgmt_rate
        return round(limit, 0), n_opt, round(gross_profit, 2)

    # 如果是零售建筑
    for shop, data in retail_data.items():
        if item_name in data["items"]:
            wage = data["wage"]
            retail_price = retail_price_map.get(item_name, None)
            if retail_price is None:
                continue
            buy_price = prices.get(item_name, retail_price)
            sales_per_hour = data["items"][item_name]
            gross_profit = sales_per_hour * (retail_price - buy_price) - wage
            if gross_profit <= 0:
                return 0, 0, 0
            n_opt = int(gross_profit / (2 * wage * mgmt_rate) - 0.5)
            if n_opt < 1:
                n_opt = 1
            limit = gross_profit * n_opt - wage * (n_opt ** 2) * mgmt_rate
            return round(limit, 0), n_opt, round(gross_profit, 2)
    return 0, 0, 0

# ---------- 寻找最优零售毛利率 ----------
best_margin = 0.20
best_diff = float('inf')
best_prices = None

for margin in [0.15, 0.18, 0.20, 0.22, 0.25]:
    prices = compute_prices(margin, retail_price_map)
    prod_profits = []
    retail_profits = []
    for pname in prod_data:
        limit, _, _ = calc_limit_profit(pname, margin, prices)
        if limit > 0:
            prod_profits.append(limit)
    for shop, data in retail_data.items():
        for rname in data["items"]:
            if rname in retail_price_map:
                limit, _, _ = calc_limit_profit(rname, margin, prices)
                if limit > 0:
                    retail_profits.append(limit)
    if not prod_profits or not retail_profits:
        continue
    avg_prod = sum(prod_profits) / len(prod_profits)
    avg_retail = sum(retail_profits) / len(retail_profits)
    diff = abs(avg_prod - avg_retail) / ((avg_prod + avg_retail) / 2)
    if diff < best_diff:
        best_diff = diff
        best_margin = margin
        best_prices = prices

print(f"最优毛利率: {best_margin*100:.1f}%，生产/零售极限利润差异: {best_diff*100:.1f}%")
prices = best_prices

# ---------- 生成 data_output.json ----------
beijing_tz = timezone(timedelta(hours=8))
update_time = datetime.now(tz=beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

output = {
    "update_time": update_time,
    "margin": round(best_margin, 4),
    "items": [],
    "retail_prices": retail_price_map
}

# 收集所有物品（生产 + 零售）
all_items = set(prod_data.keys()) | {name for r in retail_data.values() for name in r["items"].keys()}

for item in all_items:
    price = prices.get(item, 0)
    is_retail = item in retail_price_map
    output["items"].append({
        "name": item,
        "price": price,
        "retail_price": retail_price_map.get(item, None),
        "is_retail": is_retail
    })

# 附加每个建筑的极限利润（供前端可选展示）
building_profits = {}
for pname in prod_data:
    limit, opt_lv, gross = calc_limit_profit(pname, best_margin, prices)
    building_profits[pname] = {"limit": limit, "opt_level": opt_lv, "gross": gross}
for shop, data in retail_data.items():
    for rname in data["items"]:
        if rname in retail_price_map:
            limit, opt_lv, gross = calc_limit_profit(rname, best_margin, prices)
            building_profits[f"零售_{rname}"] = {"limit": limit, "opt_level": opt_lv, "gross": gross}

output["building_profits"] = building_profits

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print("data_output.json 已生成。")

# ---------- 生成简洁的 index.html（可根据需要修改） ----------
# 为了快速看到数据，这里生成一个简单的表格页面，展示指导价和极限利润。
# 如果已有现成的前端，可跳过此步，直接用现有的 index.html 和 app.js。
html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>动态市场指导价</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background: #f5f5f5; margin: 0; padding: 20px; }}
  .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 25px; border-radius: 10px; }}
  h1 {{ text-align: center; color: #2c3e50; }}
  .info {{ text-align: center; color: #888; margin-bottom: 20px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #e0e0e0; }}
  th {{ background: #fafafa; font-weight: 600; }}
  .price {{ font-weight: 600; color: #e67e22; }}
  .limit {{ font-weight: 600; color: #e74c3c; }}
</style>
</head>
<body>
<div class="container">
  <h1>🏭 动态加权指导价</h1>
  <div class="info">更新时间：<span id="update-time"></span> | 最优零售毛利率：<span id="margin"></span></div>
  <div id="tables"></div>
</div>
<script>
fetch('data_output.json').then(r=>r.json()).then(data => {{
  document.getElementById('update-time').innerText = data.update_time;
  document.getElementById('margin').innerText = (data.margin * 100).toFixed(1) + '%';
  let items = data.items;
  // 简单表格：展示所有商品的指导价和零售价
  let html = '<table><tr><th>商品</th><th>指导价</th><th>零售价（若零售）</th><th>极限利润（参考）</th></tr>';
  items.forEach(it => {{
    let profitInfo = data.building_profits?.[it.name];
    let limitStr = profitInfo ? profitInfo.limit.toLocaleString() + ' 元/h' : '';
    html += `<tr>
      <td>${{it.name}}</td>
      <td class="price">${{it.price.toFixed(2)}} 元</td>
      <td>${{it.retail_price ? it.retail_price.toFixed(2) + ' 元' : '—'}}</td>
      <td class="limit">${{limitStr}}</td>
    </tr>`;
  }});
  html += '</table>';
  document.getElementById('tables').innerHTML = html;
}});
</script>
</body>
</html>
"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)
print("index.html 已生成（简单展示版）。")
