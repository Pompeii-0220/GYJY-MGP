import json
import requests
from datetime import datetime, timezone, timedelta

print("脚本启动...")

# ========== 1. 加载静态数据库 ==========
with open("game_data.json", "r", encoding="utf-8") as f:
    gd = json.load(f)

prod_data = gd["production"]
retail_data = gd["retail"]
mgmt_rate = gd["management_rate"]

# ========== 2. 抓取 API 数据 ==========
api_url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(api_url, timeout=15)
resp.raise_for_status()
api_json = resp.json()
retail_rows = api_json.get("rows", [])

retail_price_map = {item["name"]: item["retailPrice"] for item in retail_rows}
base_price_map = {item["name"]: item["basePrice"] for item in retail_rows}

print(f"API零售品数量: {len(retail_rows)}")

# ========== 3. 生成静态基石价（成本加成，一次性） ==========
FIXED_PROFIT_RATE = 0.15  # 15%基础利润率

prices = {}
# 电力基准：劳动力成本 + 15%利润
elec_info = prod_data.get("电力")
if elec_info:
    labor = elec_info["wage"] / elec_info["output"]
    prices["电力"] = round(labor * (1 + FIXED_PROFIT_RATE), 2)

# 其他产品按依赖顺序逐层计算
remaining = set(prod_data.keys()) - {"电力"}
while remaining:
    solved = set()
    for p in remaining:
        info = prod_data[p]
        recipe = info["recipe"]
        batch = info.get("batch", 1)
        all_known = True
        mat_cost = 0.0
        for ing, amount in recipe.items():
            if ing not in prices:
                all_known = False
                break
            per_unit = amount / batch
            mat_cost += per_unit * prices[ing]
        if all_known:
            labor = info["wage"] / info["output"]
            # 成本加成定价
            price = round((mat_cost + labor) * (1 + FIXED_PROFIT_RATE), 2)
            # 如果是零售品：使用Excel基础零售价作为基石价（不在这里设天花板）
            # 终端品的基石价直接用Excel的基础价
            if p in base_price_map:
                prices[p] = base_price_map[p]  # 直接用Excel基础价
            else:
                prices[p] = price
            solved.add(p)

    if not solved:
        for p in remaining:
            if p not in prices:
                labor = prod_data[p]["wage"] / prod_data[p]["output"]
                prices[p] = round(labor * 2.0, 2)
        break
    remaining -= solved

print(f"静态基石价生成完毕，商品数: {len(prices)}")

# ========== 4. 计算统一市场倍率 ==========
total_w = 0.0
sum_m = 0.0
for item in retail_rows:
    name = item["name"]
    if name not in prices:
        continue
    speed = 0
    for shop, data in retail_data.items():
        if name in data["items"]:
            speed = data["items"][name]
            break
    if speed > 0:
        sum_m += item["multiplier"] * speed
        total_w += speed

unified_mult = sum_m / total_w if total_w > 0 else 1.0
final_prices = {name: round(bp * unified_mult, 2) for name, bp in prices.items()}

print(f"统一市场倍率: {unified_mult:.4f}")

# ========== 5. 极限利润计算 ==========
def calc_limit_profit(item_name, prices):
    if item_name in prod_data:
        info = prod_data[item_name]
        wage = info["wage"]
        output = info["output"]
        price = prices.get(item_name, 0)
        recipe = info["recipe"]
        batch = info.get("batch", 1)
        mat_cost = 0.0
        for ing, amount in recipe.items():
            per_unit = amount / batch
            mat_cost += per_unit * prices.get(ing, 0)
        gross = output * (price - mat_cost) - wage
        if gross <= 0:
            return 0, 0
        n_opt = int(gross / (2 * wage * mgmt_rate) - 0.5)
        if n_opt < 1:
            n_opt = 1
        limit = gross * n_opt - wage * (n_opt ** 2) * mgmt_rate
        return round(limit, 0), n_opt

    for shop, data in retail_data.items():
        if item_name in data["items"]:
            wage = data["wage"]
            retail_price = retail_price_map.get(item_name, 0)
            buy_price = prices.get(item_name, 0)
            sales = data["items"][item_name]
            gross = sales * (retail_price - buy_price) - wage
            if gross <= 0:
                return 0, 0
            n_opt = int(gross / (2 * wage * mgmt_rate) - 0.5)
            if n_opt < 1:
                n_opt = 1
            limit = gross * n_opt - wage * (n_opt ** 2) * mgmt_rate
            return round(limit, 0), n_opt
    return 0, 0

# ========== 6. 输出 data_output.json ==========
beijing_tz = timezone(timedelta(hours=8))
update_time = datetime.now(tz=beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

output = {
    "update_time": update_time,
    "unified_multiplier": round(unified_mult, 4),
    "items": [],
    "retail_prices": retail_price_map
}

all_items = set(final_prices.keys()) | {name for r in retail_data.values() for name in r["items"].keys()}
for item in all_items:
    output["items"].append({
        "name": item,
        "price": final_prices.get(item, 0),
        "retail_price": retail_price_map.get(item),
        "is_retail": item in retail_price_map
    })

building_profits = {}
for pname in prod_data:
    limit, opt = calc_limit_profit(pname, final_prices)
    building_profits[pname] = {"limit": limit, "opt_level": opt}
for shop, data in retail_data.items():
    for rname in data["items"]:
        if rname in retail_price_map:
            limit, opt = calc_limit_profit(rname, final_prices)
            building_profits[f"零售_{rname}"] = {"limit": limit, "opt_level": opt}

output["building_profits"] = building_profits

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print("✅ 指导价已生成（静态基石×统一倍率）")
