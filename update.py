import json
import requests
from datetime import datetime, timezone, timedelta

print("脚本启动...")

# ========== 1. 加载数据 ==========
with open("game_data.json", "r", encoding="utf-8") as f:
    gd = json.load(f)

prod_data = gd["production"]
retail_data = gd["retail"]
mgmt_rate = gd["management_rate"]

# ========== 2. 获取 API 零售价 ==========
api_url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(api_url, timeout=15)
resp.raise_for_status()
api_json = resp.json()
retail_rows = api_json.get("rows", [])
retail_price_map = {item["name"]: item["retailPrice"] for item in retail_rows}
retail_base_price_map = {item["name"]: item["basePrice"] for item in retail_rows}

# ========== 3. 辅助函数 ==========
def compute_material_cost(product, prices):
    """给定价格字典，返回生产1个单位该产品的原料成本"""
    if product not in prod_data:
        return 0.0
    info = prod_data[product]
    recipe = info["recipe"]
    batch = info.get("batch", 1)
    cost = 0.0
    for ing, amount in recipe.items():
        per_unit = amount / batch
        cost += per_unit * prices.get(ing, 0)
    return cost

def compute_gross_profit(product, price, prices):
    """给定产品价格，计算该建筑1级时的毛利润（元/h）"""
    info = prod_data[product]
    wage = info["wage"]
    output = info["output"]
    mat_cost = compute_material_cost(product, prices)
    return output * (price - mat_cost) - wage

def compute_limit_profit(product, price, prices):
    """给定产品价格，计算最优等级和极限利润"""
    gross = compute_gross_profit(product, price, prices)
    if gross <= 0:
        return 0, 0
    n_opt = int(gross / (2 * mgmt_rate * prod_data[product]["wage"]) - 0.5)
    if n_opt < 1:
        n_opt = 1
    limit = gross * n_opt - prod_data[product]["wage"] * (n_opt ** 2) * mgmt_rate
    return round(limit, 0), n_opt

# ========== 4. 初始化价格 ==========
prices = {}
# 电力：用劳动力成本 + 15% 作为初始价
elec_info = prod_data.get("电力")
if elec_info:
    labor = elec_info["wage"] / elec_info["output"]
    prices["电力"] = round(labor * 1.15, 2)

# 其他产品：按依赖顺序，用原料成本 + 劳动力成本 + 15% 初始化
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
            prices[p] = round((mat_cost + labor) * 1.15, 2)
            solved.add(p)
    if not solved:  # 死锁保底
        for p in remaining:
            if p not in prices:
                labor = prod_data[p]["wage"] / prod_data[p]["output"]
                prices[p] = round(labor * 2.0, 2)
        break
    remaining -= solved

# 零售品价格上限约束
RETAIL_CEILING_FACTOR = 0.98  # 指导价最高可达零售基础价的98%
for item in retail_base_price_map:
    if item in prices:
        ceiling = retail_base_price_map[item] * RETAIL_CEILING_FACTOR
        prices[item] = min(prices[item], ceiling)

print(f"初始价格设置完毕，商品数: {len(prices)}")

# ========== 5. 迭代市场出清 ==========
MAX_ITER = 500
TOLERANCE = 0.15  # 变异系数低于15%即可停止
ADJUST_STEP = 0.02  # 每次调价幅度

for iteration in range(MAX_ITER):
    # 计算所有生产建筑的极限利润
    limits = {}
    for pname in prod_data:
        limit, _ = compute_limit_profit(pname, prices[pname], prices)
        if limit > 0:
            limits[pname] = limit

    if len(limits) < 5:
        print("盈利建筑过少，调价空间不足，退出")
        break

    # 计算变异系数
    lvals = list(limits.values())
    mean = sum(lvals) / len(lvals)
    variance = sum((x - mean) ** 2 for x in lvals) / len(lvals)
    cv = (variance ** 0.5) / mean

    if cv < TOLERANCE:
        print(f"第{iteration+1}次迭代，变异系数{cv:.4f} 已达标，停止迭代")
        break

    # 找出利润最高和最低的建筑
    max_prod = max(limits, key=limits.get)
    min_prod = min(limits, key=limits.get)

    # 调整对应产品的价格
    old_min_price = prices[min_prod]
    old_max_price = prices[max_prod]

    # 提高低利润产品的价格
    prices[min_prod] = round(prices[min_prod] * (1 + ADJUST_STEP), 2)
    # 降低高利润产品的价格
    prices[max_prod] = round(prices[max_prod] * (1 - ADJUST_STEP), 2)

    # 确保新价格不低于直接原料成本
    min_mat_cost = compute_material_cost(min_prod, prices)
    if prices[min_prod] < min_mat_cost:
        prices[min_prod] = round(min_mat_cost * 1.05, 2)

    # 确保零售品不超过上限（重新应用）
    if max_prod in retail_base_price_map:
        ceiling = retail_base_price_map[max_prod] * RETAIL_CEILING_FACTOR
        prices[max_prod] = min(prices[max_prod], ceiling)
    if min_prod in retail_base_price_map:
        ceiling = retail_base_price_map[min_prod] * RETAIL_CEILING_FACTOR
        prices[min_prod] = min(prices[min_prod], ceiling)

    if iteration % 50 == 0:
        print(f"迭代 {iteration+1}, CV: {cv:.4f}, 调整: {min_prod}({old_min_price}→{prices[min_prod]}), {max_prod}({old_max_price}→{prices[max_prod]})")

# ========== 6. 统一市场倍率 ==========
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

# ========== 7. 输出 ==========
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

# 计算极限利润表（生产 + 零售）
building_profits = {}
for pname in prod_data:
    limit, opt = compute_limit_profit(pname, final_prices[pname], final_prices)
    building_profits[pname] = {"limit": limit, "opt_level": opt}
for shop, data in retail_data.items():
    for rname in data["items"]:
        if rname in retail_price_map:
            wage = data["wage"]
            retail_price = retail_price_map[rname]
            buy_price = final_prices.get(rname, 0)
            sales = data["items"][rname]
            gross = sales * (retail_price - buy_price) - wage
            if gross > 0:
                n_opt = int(gross / (2 * wage * mgmt_rate) - 0.5)
                if n_opt < 1: n_opt = 1
                limit = gross * n_opt - wage * (n_opt ** 2) * mgmt_rate
                building_profits[f"零售_{rname}"] = {"limit": round(limit, 0), "opt_level": n_opt}
            else:
                building_profits[f"零售_{rname}"] = {"limit": 0, "opt_level": 0}

output["building_profits"] = building_profits

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"✅ 统一倍率 {unified_mult:.4f}，指导价已更新（迭代市场出清）")
