import json
import requests
from datetime import datetime, timezone, timedelta

# ========== 1. 加载数据 ==========
with open("game_data.json", "r", encoding="utf-8") as f:
    gd = json.load(f)

prod_data = gd["production"]
retail_data = gd["retail"]
mgmt_rate = gd["management_rate"]

# ========== 2. API 零售价 ==========
url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(url, timeout=15)
resp.raise_for_status()
api_json = resp.json()
retail_rows = api_json.get("rows", [])
retail_price_map = {item["name"]: item["retailPrice"] for item in retail_rows}
retail_base_price_map = {item["name"]: item["basePrice"] for item in retail_rows}

# ========== 3. 辅助函数 ==========
def calc_material_cost(product_name, prices):
    if product_name not in prod_data:
        return 0.0
    info = prod_data[product_name]
    recipe = info["recipe"]
    batch = info.get("batch", 1)
    cost = 0.0
    for ing, amount in recipe.items():
        per_unit = amount / batch
        cost += per_unit * prices.get(ing, 1e-6)
    return cost

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
                if n_opt < 1: n_opt = 1
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
        mat_cost = calc_material_cost(item_name, prices)
        gross = output * (price - mat_cost) - wage
        if gross <= 0:
            return 0, 0, 0
        n_opt = int(gross / (2 * wage * mgmt_rate) - 0.5)
        if n_opt < 1: n_opt = 1
        limit = gross * n_opt - wage * (n_opt ** 2) * mgmt_rate
        return round(limit, 0), n_opt, round(gross, 2)

# ========== 4. 初始化所有价格 ==========
prices = {}
# 电力：劳动力成本 + 15%
elec = prod_data["电力"]
labor_elec = elec["wage"] / elec["output"]
prices["电力"] = round(labor_elec * 1.15, 2)

# 其他产品：有API基础价的用基础价，没有的用劳动力成本×2作初始估计
for p in prod_data:
    if p == "电力":
        continue
    if p in retail_base_price_map:
        prices[p] = retail_base_price_map[p]
    else:
        labor = prod_data[p]["wage"] / prod_data[p]["output"]
        prices[p] = round(labor * 2.0, 2)

# ========== 5. 二分法调整终端品基石价 ==========
print("开始二分法均衡...")
for iteration in range(50):
    changed = False
    for pname in prod_data:
        # 只调整有零售价的终端品
        if pname not in retail_base_price_map:
            continue

        current_price = prices[pname]
        lo = max(calc_material_cost(pname, prices) * 1.01, 0.01)
        hi = retail_base_price_map.get(pname, current_price * 2)
        if hi <= lo:
            continue

        best_price = current_price
        best_diff = float('inf')
        for _ in range(20):
            mid = (lo + hi) / 2
            temp = prices.copy()
            temp[pname] = mid
            p_lim, _, _ = calc_limit_profit(pname, temp, False)
            r_lim, _, _ = calc_limit_profit(pname, temp, True)
            if p_lim == 0 and r_lim == 0:
                break
            diff = abs(p_lim - r_lim)
            if diff < best_diff:
                best_diff = diff
                best_price = mid
            if p_lim > r_lim:
                hi = mid
            else:
                lo = mid

        new_price = round(best_price, 2)
        if new_price != current_price:
            prices[pname] = new_price
            changed = True
    if not changed:
        print(f"  第{iteration+1}次收敛")
        break

# ========== 6. 价格保底（加强版） ==========
print("执行价格保底...")
for _ in range(5):
    for pname in prod_data:
        if pname == "电力":
            continue
        min_price = calc_material_cost(pname, prices) * 1.05  # 原料成本 + 5%
        if prices.get(pname, 0) < min_price:
            prices[pname] = round(min_price, 2)

# ========== 7. 统一市场倍率 ==========
total_w = sum_m = 0.0
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

# ========== 8. 动态指导价（零售安全帽） ==========
final_prices = {}
for name, bp in prices.items():
    dynamic = round(bp * unified_mult, 2)
    if name in retail_price_map:
        cap = round(retail_price_map[name] * 0.98, 2)
        dynamic = min(dynamic, cap)
    final_prices[name] = dynamic

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
for p in prod_data:
    limit, opt, _ = calc_limit_profit(p, prices, False)
    building_profits[p] = {"limit": limit, "opt_level": opt}
for shop, data in retail_data.items():
    for rname in data["items"]:
        if rname in retail_price_map:
            limit, opt, _ = calc_limit_profit(rname, prices, True)
            building_profits[f"零售_{rname}"] = {"limit": limit, "opt_level": opt}

output["building_profits"] = building_profits

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"✅ 统一倍率 {unified_mult:.4f}，指导价已更新")
