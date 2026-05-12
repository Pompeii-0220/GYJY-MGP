import json
import requests
from datetime import datetime, timezone, timedelta
import sys

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

# ---------- 构建依赖图与拓扑排序 ----------
# 所有节点
all_items = set(prod_data.keys()) | {name for r in retail_data.values() for name in r["items"].keys()}

# 计算入度（每个原料被哪些产品依赖）
graph = {}  # item -> list of downstream items
for product, info in prod_data.items():
    recipe = info["recipe"]
    batch = info.get("batch", 1)  # 产出数量，默认1
    for ing, amount in recipe.items():
        # 标准化为每生产1个产品的消耗量
        per_unit_amount = amount / batch
        graph.setdefault(ing, []).append((product, per_unit_amount))

# 拓扑排序：先计算那些只作为原料、不生产的产品（如零售消耗的中间品）
# 这里简化：用 Kahn 算法，但最终零售品（出现在 retail 中的）也是节点
# 零售品不依赖配方，直接有价格，作为起点

# 为了计算加权，我们需要递归，因此采用多次迭代直至收敛
# 由于配方可能复杂，直接用迭代法：从零售品价格出发，向上游加权

# ---------- 迭代寻优零售毛利率 ----------
def compute_prices(margin, retail_price_map):
    prices = {}
    # 先设定零售品的“进价”
    for prod_name, retail_price in retail_price_map.items():
        prices[prod_name] = round(retail_price * (1 - margin), 2)

    # 迭代计算中间品价格
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

def calc_limit_profit(item_name, margin, prices):
    """计算某个生产或零售建筑的极限利润（元/h）"""
    # 区分是生产建筑还是零售建筑
    if item_name in prod_data:
        info = prod_data[item_name]
        wage = info["wage"]
        output = info["output"]
        # 产品自身价格（指导价）
        product_price = prices.get(item_name, 1.0)
        # 原料成本
        recipe = info["recipe"]
        batch = info.get("batch", 1)
        mat_cost = 0.0
        for ing, amount in recipe.items():
            per_unit = amount / batch
            mat_cost += per_unit * prices.get(ing, 1.0)
        # 1级时利润（管理费为0）
        gross_profit = output * product_price - output * mat_cost - wage
        if gross_profit <= 0:
            return 0, 0, 0
        # 最优等级
        n_opt = int(gross_profit / (2 * wage * mgmt_rate) - 0.5)
        if n_opt < 1:
            n_opt = 1
        # 极限利润
        limit = gross_profit * n_opt - wage * (n_opt ** 2) * mgmt_rate
        return round(limit, 0), n_opt, round(gross_profit, 2)
    else:
        # 零售建筑
        for shop, data in retail_data.items():
            if item_name in data["items"]:
                wage = data["wage"]
                # 找出该零售品对应的零售价格
                retail_price = retail_price_map.get(item_name, None)
                if retail_price is None:
                    continue
                # 指导价（进价）
                buy_price = prices.get(item_name, retail_price)
                # 零售时销
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

# 迭代寻优
best_margin = 0.20
best_diff = float('inf')
best_prices = None

for margin in [0.15, 0.18, 0.20, 0.22, 0.25]:
    prices = compute_prices(margin, retail_price_map)
    # 计算所有生产建筑和零售建筑的平均极限利润
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

# 输出最优结果
print(f"最优毛利率: {best_margin*100:.1f}%, 差异: {best_diff*100:.1f}%")
prices = best_prices

# ---------- 生成 data_output.json ----------
beijing_tz = timezone(timedelta(hours=8))
update_time = datetime.now(tz=beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

output = {
    "update_time": update_time,
    "margin": round(best_margin, 4),
    "items": [],
    "recipes": {},  # 可留空，前端不一定需要
    "retail_prices": retail_price_map
}

for item in all_items:
    price = prices.get(item, 0)
    # 判断是否为零售品
    is_retail = item in retail_price_map
    output["items"].append({
        "name": item,
        "price": price,
        "retail_price": retail_price_map.get(item, None),
        "is_retail": is_retail,
        "cat": ""  # 可后续补充分类，不影响核心
    })

# 计算所有建筑的极限利润供前端展示（可选）
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

# 继续生成 index.html 和 app.js（这里可复用以前的生成代码）
# ...（略，保持与之前相同的 HTML 模板，前端会读取 data_output.json）
