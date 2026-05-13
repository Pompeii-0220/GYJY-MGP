import json
import requests
from datetime import datetime, timezone, timedelta
import copy

print("脚本启动...")

# ================= 可调参数 =================
RETAIL_CEILING = 0.98          # 零售品指导价上限（占API基础价的比例）
TOLERANCE = 0.15               # 利润均衡目标（变异系数 ≤ 15%）
ADJUST_STEP = 0.02             # 每次调价幅度
MAX_ITER = 500                 # 最大迭代次数

# ================= 1. 加载静态数据 =================
with open("game_data.json", "r", encoding="utf-8") as f:
    gd = json.load(f)

prod_data = gd["production"]
retail_data = gd["retail"]
mgmt_rate = gd["management_rate"]

# ================= 2. 抓取API数据 =================
api_url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(api_url, timeout=15)
resp.raise_for_status()
api_json = resp.json()
retail_rows = api_json.get("rows", [])

retail_price_map = {item["name"]: item["retailPrice"] for item in retail_rows}
retail_base_price_map = {item["name"]: item["basePrice"] for item in retail_rows}

print(f"API数据获取成功，零售品数量：{len(retail_rows)}")

# ================= 3. 辅助函数 =================
def compute_material_cost(product, prices):
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

def compute_limit_profit(product, price, prices):
    if product not in prod_data:
        return 0, 0
    info = prod_data[product]
    wage = info["wage"]
    output = info["output"]
    mat_cost = compute_material_cost(product, prices)
    gross = output * (price - mat_cost) - wage
    if gross <= 0:
        return 0, 0
    n_opt = int(gross / (2 * wage * mgmt_rate) - 0.5)
    if n_opt < 1:
        n_opt = 1
    limit = gross * n_opt - wage * (n_opt ** 2) * mgmt_rate
    return round(limit, 0), n_opt

def retail_limit_profit(item_name, prices):
    """计算零售建筑的极限利润（元/h）"""
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

# ================= 4. 初始化所有价格 =================
prices = {}
elec_info = prod_data.get("电力")
if elec_info:
    labor = elec_info["wage"] / elec_info["output"]
    prices["电力"] = round(labor * 1.15, 2)

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
            # 应用零售品上限
            if p in retail_base_price_map:
                ceiling = retail_base_price_map[p] * RETAIL_CEILING
                prices[p] = min(prices[p], ceiling)
            solved.add(p)
    if not solved:
        for p in remaining:
            if p not in prices:
                labor = prod_data[p]["wage"] / prod_data[p]["output"]
                prices[p] = round(labor * 2.0, 2)
        break
    remaining -= solved

print(f"初始价格设置完毕，商品数：{len(prices)}")

# ================= 5. 迭代均衡（生产+零售） =================
for iteration in range(MAX_ITER):
    # 收集所有生产与零售的极限利润
    all_limits = {}
    for pname in prod_data:
        limit, _ = compute_limit_profit(pname, prices[pname], prices)
        if limit > 0:
            all_limits[pname] = limit

    for rname in retail_price_map:
        limit, _ = retail_limit_profit(rname, prices)
        if limit > 0:
            all_limits[f"零售_{rname}"] = limit

    if len(all_limits) < 10:
        print("盈利建筑过少，调价空间不足，退出")
        break

    lvals = list(all_limits.values())
    mean = sum(lvals) / len(lvals)
    variance = sum((x - mean) ** 2 for x in lvals) / len(lvals)
    cv = (variance ** 0.5) / mean

    if cv < TOLERANCE:
        print(f"第{iteration+1}次迭代，变异系数={cv:.4f} 已达标")
        break

    # 寻找利润最高与最低的条目
    max_key = max(all_limits, key=all_limits.get)
    min_key = min(all_limits, key=all_limits.get)

    # 调价逻辑：压低过高利润，抬升过低利润
    if max_key.startswith("零售_"):
        rname = max_key.replace("零售_", "")
        # 零售利润过高 → 提高进货价（即生产指导价）
        if rname in prices:
            prices[rname] = round(prices[rname] * (1 + ADJUST_STEP), 2)
    else:
        # 生产利润过高 → 降低其产品价格
        prices[max_key] = round(prices[max_key] * (1 - ADJUST_STEP), 2)

    if min_key.startswith("零售_"):
        rname = min_key.replace("零售_", "")
        # 零售利润过低 → 降低进货价（让利给零售）
        if rname in prices:
            prices[rname] = round(prices[rname] * (1 - ADJUST_STEP), 2)
    else:
        # 生产利润过低 → 提高其产品价格
        prices[min_key] = round(prices[min_key] * (1 + ADJUST_STEP), 2)
        # 若已达价格上限，则转而压低该产品的原料价格（传导压力）
        if min_key in retail_base_price_map and prices[min_key] >= retail_base_price_map[min_key] * RETAIL_CEILING:
            recipe = prod_data.get(min_key, {}).get("recipe", {})
            for ing in recipe:
                prices[ing] = round(prices[ing] * (1 - ADJUST_STEP * 0.5), 2)

    # 重新施加价格下限（不低于原料成本）与上限（零售品）
    for p in list(prices.keys()):
        mat_min = compute_material_cost(p, prices)
        if prices[p] < mat_min:
            prices[p] = round(mat_min * 1.02, 2)
        if p in retail_base_price_map:
            ceiling = retail_base_price_map[p] * RETAIL_CEILING
            prices[p] = min(prices[p], ceiling)

    if iteration % 100 == 0:
        print(f"迭代 {iteration+1}, CV: {cv:.4f}, 调整: {min_key} ↔ {max_key}")

# 保存均衡价格表
static_prices = copy.deepcopy(prices)
with open("static_equilibrium_prices.json", "w", encoding="utf-8") as f:
    json.dump(static_prices, f, indent=2, ensure_ascii=False)
print("静态均衡价格表已保存")

with open("static_prices_only.json", "w", encoding="utf-8") as f:
    # 只保存商品名和对应的1.0倍率静态价
    json.dump(static_prices, f, indent=2, ensure_ascii=False)

# ================= 6. 统一市场倍率 =================
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

print(f"统一市场倍率：{unified_mult:.4f}")

# ================= 7. 输出 data_output.json =================
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
    limit, opt = compute_limit_profit(pname, final_prices[pname], final_prices)
    building_profits[pname] = {"limit": limit, "opt_level": opt}
for shop, data in retail_data.items():
    for rname in data["items"]:
        if rname in retail_price_map:
            limit, opt = retail_limit_profit(rname, final_prices)
            building_profits[f"零售_{rname}"] = {"limit": limit, "opt_level": opt}

output["building_profits"] = building_profits

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print("✅ 动态指导价与利润表已更新。")
