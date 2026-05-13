import json
import requests
from datetime import datetime, timezone, timedelta

# ========== 1. 加载静态数据库 ==========
with open("game_data.json", "r", encoding="utf-8") as f:
    gd = json.load(f)

prod_data = gd["production"]
retail_data = gd["retail"]
mgmt_rate = gd["management_rate"]

# ========== 2. 抓取 API 零售价 ==========
url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(url, timeout=15)
resp.raise_for_status()
api_json = resp.json()
retail_rows = api_json.get("rows", [])
retail_price_map = {item["name"]: item["retailPrice"] for item in retail_rows}
retail_base_price_map = {item["name"]: item["basePrice"] for item in retail_rows}

# ========== 3. 计算基石价 ==========
PROFIT_RATE = 0.15  # 15%基础利润率

prices = {}
# 电力：劳动力成本 + 利润
elec_info = prod_data["电力"]
labor_elec = elec_info["wage"] / elec_info["output"]
prices["电力"] = round(labor_elec * (1 + PROFIT_RATE), 2)

# 按依赖顺序逐层计算其他产品
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
            price = round((mat_cost + labor) * (1 + PROFIT_RATE), 2)
            prices[p] = price
            solved.add(p)
    if not solved:
        # 死锁保底：用劳动力成本×2
        for p in remaining:
            if p not in prices:
                labor = prod_data[p]["wage"] / prod_data[p]["output"]
                prices[p] = round(labor * 2.0, 2)
        break
    remaining -= solved

# ========== 4. 价格保底（仅非零售品） ==========
for _ in range(3):
    for p in prod_data:
        if p == "电力" or p in retail_base_price_map:
            continue  # 零售品不参与保底
        info = prod_data[p]
        mat = 0.0
        recipe = info["recipe"]
        batch = info.get("batch", 1)
        for ing, amount in recipe.items():
            per_unit = amount / batch
            mat += per_unit * prices.get(ing, 0)
        if prices[p] < mat * 1.05:
            prices[p] = round(mat * 1.05, 2)

# ========== 5. 零售品强制锁定 API 基础价 ==========
for p in retail_base_price_map:
    prices[p] = retail_base_price_map[p]

# ========== 6. 统一市场倍率 ==========
total_weight = 0.0
sum_mult = 0.0
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
        sum_mult += item["multiplier"] * speed
        total_weight += speed

unified_mult = sum_mult / total_weight if total_weight > 0 else 1.0

# ========== 7. 动态指导价（含安全帽 0.98） ==========
final_prices = {}
for name, bp in prices.items():
    dynamic = round(bp * unified_mult, 2)
    if name in retail_price_map:
        cap = round(retail_price_map[name] * 0.98, 2)
        dynamic = min(dynamic, cap)
    final_prices[name] = dynamic

# ========== 8. 极限利润计算（保留，供分析） ==========
def calc_limit_profit(item_name, prices, is_retail=False):
    if is_retail:
        for shop, data in retail_data.items():
            if item_name in data["items"]:
                wage = data["wage"]
                retail_price = retail_price_map.get(item_name, 0)
                buy_price = prices.get(item_name, 0)
                sales = data["items"][item_name]
                gross = sales * (retail_price - buy_price) - wage
                if gross <= 0:
                    return 0, 0, 0
                n_opt = int(gross / (2 * wage * mgmt_rate) - 0.5)
                if n_opt < 1:
                    n_opt = 1
                limit = gross * n_opt - wage * (n_opt ** 2) * mgmt_rate
                return round(limit, 0), n_opt, round(gross, 2)
        return 0, 0, 0
    else:
        if item_name not in prod_data:
            return 0, 0, 0
        info = prod_data[item_name]
        wage = info["wage"]
        output = info["output"]
        price = prices.get(item_name, 0)
        mat = 0.0
        recipe = info["recipe"]
        batch = info.get("batch", 1)
        for ing, amount in recipe.items():
            per_unit = amount / batch
            mat += per_unit * prices.get(ing, 0)
        gross = output * (price - mat) - wage
        if gross <= 0:
            return 0, 0, 0
        n_opt = int(gross / (2 * wage * mgmt_rate) - 0.5)
        if n_opt < 1:
            n_opt = 1
        limit = gross * n_opt - wage * (n_opt ** 2) * mgmt_rate
        return round(limit, 0), n_opt, round(gross, 2)

# ========== 9. 输出 data_output.json ==========
beijing_tz = timezone(timedelta(hours=8))
update_time = datetime.now(tz=beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

output = {
    "update_time": update_time,
    "unified_multiplier": round(unified_mult, 4),
    "items": [],
    "retail_prices": retail_price_map
}

all_items = set(final_prices.keys()) | {name for r in retail_data.values() for name in r["items"]}
for item in all_items:
    output["items"].append({
        "name": item,
        "price": final_prices.get(item, 0),
        "base_price": prices.get(item, 0),
        "retail_price": retail_price_map.get(item),
        "is_retail": item in retail_price_map
    })

building_profits = {}
for pname in prod_data:
    limit, opt, _ = calc_limit_profit(pname, prices, False)
    building_profits[pname] = {"limit": limit, "opt_level": opt}
for shop, data in retail_data.items():
    for rname in data["items"]:
        if rname in retail_price_map:
            limit, opt, _ = calc_limit_profit(rname, prices, True)
            building_profits[f"零售_{rname}"] = {"limit": limit, "opt_level": opt}

output["building_profits"] = building_profits

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"✅ 统一倍率 {unified_mult:.4f}，指导价已生成")
