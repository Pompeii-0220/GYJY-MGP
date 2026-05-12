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

# 建立零售品名称 -> 零售价、倍率 映射
retail_price_map = {}
retail_mult_map = {}
for item in retail_rows:
    name = item["name"]
    retail_price_map[name] = item["retailPrice"]
    retail_mult_map[name] = item["multiplier"]

# ---------- 工具函数：计算所有生产品的1.0倍率均衡指导价 ----------
def compute_base_prices(prod_data, profit_rate=0.15):
    """基于成本加成，递归计算所有产品的均衡指导价 (倍率=1.0)"""
    prices = {}
    # 按依赖顺序处理（重复直到全部算出）
    products_needed = set(prod_data.keys())
    while products_needed:
        solved_this_round = set()
        for product in products_needed:
            info = prod_data[product]
            recipe = info["recipe"]
            batch = info.get("batch", 1)
            mat_cost = 0.0
            all_known = True
            for ing, amount in recipe.items():
                per_unit = amount / batch
                if ing not in prices:   # 原料尚未计算
                    all_known = False
                    break
                mat_cost += per_unit * prices[ing]
            if all_known:
                labor = info["wage"] / info["output"]
                prices[product] = round((mat_cost + labor) * (1 + profit_rate), 2)
                solved_this_round.add(product)
        if not solved_this_round:
            # 死锁（理论上不应发生，除非配方循环引用），用劳动力成本×2保底
            for product in products_needed:
                info = prod_data[product]
                labor = info["wage"] / info["output"]
                prices[product] = round(labor * 2.0, 2)
            break
        products_needed -= solved_this_round
    return prices

# 计算基础指导价（利润率15%）
BASE_PROFIT_RATE = 0.15
base_prices = compute_base_prices(prod_data, BASE_PROFIT_RATE)

# ---------- 计算统一市场倍率 ----------
total_weight = 0.0
sum_mult = 0.0
for item in retail_rows:
    name = item.get("name", "")
    if name not in base_prices:
        continue
    # 查找销售速度
    sales_speed = 0
    for shop, data in retail_data.items():
        if name in data["items"]:
            sales_speed = data["items"][name]
            break
    if sales_speed > 0:
        mult = item["multiplier"]
        sum_mult += mult * sales_speed
        total_weight += sales_speed

if total_weight > 0:
    unified_mult = sum_mult / total_weight
else:
    unified_mult = 1.0

# ---------- 生成最终指导价 = 基础价 × 统一倍率 ----------
final_prices = {}
for name, bp in base_prices.items():
    final_prices[name] = round(bp * unified_mult, 2)

# 补全零售数据中可能存在但不在生产表中的物品（极少情况）
for shop, data in retail_data.items():
    for rname in data["items"]:
        if rname not in final_prices:
            final_prices[rname] = round(base_prices.get(rname, 0) * unified_mult, 2)

# ---------- 极限利润计算 ----------
def calc_limit_profit(item_name, prices):
    # 生产建筑
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
            mat_cost += per_unit * prices.get(ing, 0)
        gross = output * product_price - output * mat_cost - wage
        if gross <= 0:
            return 0, 0, 0
        n_opt = int(gross / (2 * wage * mgmt_rate) - 0.5)
        if n_opt < 1:
            n_opt = 1
        limit = gross * n_opt - wage * (n_opt ** 2) * mgmt_rate
        return round(limit, 0), n_opt, round(gross, 2)

    # 零售建筑
    for shop, data in retail_data.items():
        if item_name in data["items"]:
            wage = data["wage"]
            retail_price = retail_price_map.get(item_name)
            if not retail_price:
                return 0, 0, 0
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

# ---------- 输出 data_output.json ----------
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
    limit, opt, gross = calc_limit_profit(pname, final_prices)
    building_profits[pname] = {"limit": limit, "opt_level": opt, "gross": gross}
for shop, data in retail_data.items():
    for rname in data["items"]:
        if rname in retail_price_map:
            limit, opt, gross = calc_limit_profit(rname, final_prices)
            building_profits[f"零售_{rname}"] = {"limit": limit, "opt_level": opt, "gross": gross}

output["building_profits"] = building_profits

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"✅ 统一倍率 {unified_mult:.4f}，基础利润率 {BASE_PROFIT_RATE*100:.0f}%，指导价已生成")
