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

retail_price_map = {item["name"]: item["retailPrice"] for item in retail_rows}

# ---------- 计算指导价 ----------
def compute_prices(margin, retail_price_map):
    prices = {}

    # 电力基础价
    elec_info = prod_data.get("电力")
    if elec_info:
        labor_e = elec_info["wage"] / elec_info["output"]
        prices["电力"] = round(labor_e * 1.15, 2)

    # 零售品进价
    for prod_name, retail_price in retail_price_map.items():
        prices[prod_name] = round(retail_price * (1 - margin), 2)

    # 保底成本加成价格（解决0元问题）
    products_to_solve = set(prod_data.keys()) - set(prices.keys())
    while products_to_solve:
        solved = set()
        for product in products_to_solve:
            info = prod_data[product]
            recipe = info["recipe"]
            batch = info.get("batch", 1)
            mat_cost = 0.0
            all_known = True
            for ing, amount in recipe.items():
                per_unit = amount / batch
                if ing not in prices:
                    all_known = False
                    break
                mat_cost += per_unit * prices[ing]
            if all_known:
                labor = info["wage"] / info["output"]
                prices[product] = round((mat_cost + labor) * 1.15, 2)
                solved.add(product)
        if not solved:
            # 死锁时用劳动力成本强行赋值
            for prod in products_to_solve:
                info = prod_data[prod]
                prices[prod] = round((info["wage"] / info["output"]) * 1.5, 2)
            break
        products_to_solve -= solved

    # 加权修正（用下游需求拉动）
    changed = True
    while changed:
        changed = False
        for product in prod_data:
            if product in retail_price_map:  # 零售品不变
                continue
            recipe = prod_data[product]["recipe"]
            batch = prod_data[product].get("batch", 1)
            downstream = []
            for down_prod, down_info in prod_data.items():
                if product in down_info["recipe"]:
                    d_amount = down_info["recipe"][product] / down_info.get("batch", 1)
                    speed = down_info["output"]
                    demand = speed * d_amount
                    dp = prices.get(down_prod, 0)
                    downstream.append((demand, dp))
            if downstream:
                tw = sum(d for d, _ in downstream)
                sp = sum(d * p for d, p in downstream)
                new_p = round(sp / tw, 2)
                if new_p != prices.get(product, 0):
                    prices[product] = new_p
                    changed = True
    return prices

# ---------- 极限利润计算 ----------
def calc_limit_profit(item_name, margin, prices):
    if item_name in prod_data:
        info = prod_data[item_name]
        wage = info["wage"]
        output = info["output"]
        product_price = prices.get(item_name, 0)
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

    for shop, data in retail_data.items():
        if item_name in data["items"]:
            wage = data["wage"]
            retail_price = retail_price_map.get(item_name)
            if not retail_price:
                continue
            buy_price = prices.get(item_name, retail_price)
            sales = data["items"][item_name]
            gross_profit = sales * (retail_price - buy_price) - wage
            if gross_profit <= 0:
                return 0, 0, 0
            n_opt = int(gross_profit / (2 * wage * mgmt_rate) - 0.5)
            if n_opt < 1:
                n_opt = 1
            limit = gross_profit * n_opt - wage * (n_opt ** 2) * mgmt_rate
            return round(limit, 0), n_opt, round(gross_profit, 2)
    return 0, 0, 0

# ---------- 寻优毛利率 ----------
best_margin = 0.20
best_diff = float('inf')
best_prices = None

for margin in [0.15, 0.18, 0.20, 0.22, 0.25]:
    prices = compute_prices(margin, retail_price_map)
    prod_profits, retail_profits = [], []
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
    if prod_profits and retail_profits:
        avg_p = sum(prod_profits) / len(prod_profits)
        avg_r = sum(retail_profits) / len(retail_profits)
        diff = abs(avg_p - avg_r) / ((avg_p + avg_r) / 2)
        if diff < best_diff:
            best_diff = diff
            best_margin = margin
            best_prices = prices

print(f"最优毛利率: {best_margin*100:.1f}%，差异: {best_diff*100:.1f}%")
if best_prices is None:
    print("警告：未找到任何正利润建筑，使用默认毛利率20%")
    prices = compute_prices(0.20, retail_price_map)
else:
    prices = best_prices

# ---------- 输出文件 ----------
beijing_tz = timezone(timedelta(hours=8))
update_time = datetime.now(tz=beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

output = {
    "update_time": update_time,
    "margin": round(best_margin, 4),
    "items": [],
    "retail_prices": retail_price_map
}

all_items = set(prod_data.keys()) | {name for r in retail_data.values() for name in r["items"].keys()}
for item in all_items:
    output["items"].append({
        "name": item,
        "price": prices.get(item, 0),
        "retail_price": retail_price_map.get(item),
        "is_retail": item in retail_price_map
    })

building_profits = {}
for pname in prod_data:
    limit, opt, gross = calc_limit_profit(pname, best_margin, prices)
    building_profits[pname] = {"limit": limit, "opt_level": opt, "gross": gross}
for shop, data in retail_data.items():
    for rname in data["items"]:
        if rname in retail_price_map:
            limit, opt, gross = calc_limit_profit(rname, best_margin, prices)
            building_profits[f"零售_{rname}"] = {"limit": limit, "opt_level": opt, "gross": gross}

output["building_profits"] = building_profits

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

# index.html 已单独提供，这里不再重复生成
