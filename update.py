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

# 建立零售品名称 -> 零售价、基础价 映射
retail_price_map = {}
base_price_map = {}
for item in retail_rows:
    name = item["name"]
    retail_price_map[name] = item["retailPrice"]
    base_price_map[name] = item["basePrice"]

# ---------- 计算指导价（统一倍率，不迭代） ----------
FIXED_MARGIN = 0.20  # 固定20%毛利率

prices = {}

# 1. 零售品：指导价 = API零售价 × 0.8（给零售建筑留20%利润空间）
for name, retail_price in retail_price_map.items():
    prices[name] = round(retail_price * (1 - FIXED_MARGIN), 2)

# 2. 非零售品：使用API基础价（basePrice）
#    如果API中没有该商品的基础价，则用劳动力成本 × 1.5 作为保底
for product, info in prod_data.items():
    if product in prices:
        continue  # 已经在零售品中处理过
    if product in base_price_map:
        prices[product] = round(base_price_map[product] * 1.0, 2)  # 直接使用API基础价
    else:
        # 保底价格：劳动力成本 × 1.5
        labor_cost = info["wage"] / info["output"]
        prices[product] = round(labor_cost * 1.5, 2)

# ---------- 极限利润计算 ----------
def calc_limit_profit(item_name, prices):
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

# ---------- 输出文件 ----------
beijing_tz = timezone(timedelta(hours=8))
update_time = datetime.now(tz=beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

output = {
    "update_time": update_time,
    "margin": FIXED_MARGIN,
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
    limit, opt, gross = calc_limit_profit(pname, prices)
    building_profits[pname] = {"limit": limit, "opt_level": opt, "gross": gross}
for shop, data in retail_data.items():
    for rname in data["items"]:
        if rname in retail_price_map:
            limit, opt, gross = calc_limit_profit(rname, prices)
            building_profits[f"零售_{rname}"] = {"limit": limit, "opt_level": opt, "gross": gross}

output["building_profits"] = building_profits

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print("✅ data_output.json 已生成（统一倍率模式）")
