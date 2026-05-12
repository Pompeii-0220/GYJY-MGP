import json
import requests
from datetime import datetime, timezone, timedelta

# ========== 1. 加载静态数据库 ==========
with open("game_data.json", "r", encoding="utf-8") as f:
    gd = json.load(f)

prod_data = gd["production"]
retail_data = gd["retail"]
mgmt_rate = gd["management_rate"]

# ========== 2. 抓取 API 零售基础价 ==========
api_url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(api_url)
resp.raise_for_status()
api_json = resp.json()
retail_rows = api_json.get("rows", [])
retail_base_price_map = {item["name"]: item["basePrice"] for item in retail_rows}
retail_price_map = {item["name"]: item["retailPrice"] for item in retail_rows}

# ========== 3. 计算所有中间品的均衡指导价 ==========
# 3.1 基准利润率与风险溢价系数
BASE_PROFIT_RATE = 0.15  # 15%基础利润率

# 3.2 计算每个产品的“原料种类数”和“建造成本分”
def count_ingredients(product_name):
    if product_name not in prod_data:
        return 0
    return len(prod_data[product_name]["recipe"])

# 3.3 基于原料种类和建造成本计算最终利润率
def get_profit_rate(product_name, base_prices):
    ingredients_count = count_ingredients(product_name)
    # 风险溢价：原料种类越多，溢价越高
    if ingredients_count <= 1:
        risk_bonus = 0.00
    elif ingredients_count <= 2:
        risk_bonus = 0.03
    elif ingredients_count <= 3:
        risk_bonus = 0.06
    else:
        risk_bonus = 0.09

    # 建造成本溢价：建筑本身造价越高，风险越大，利润率应该更高
    # 这部分的计算会放在指导价计算完成后，对生产该产品的建筑的极限利润进行加成。
    # 在定价步骤，我们只使用【基础利润率 + 原料风险溢价】
    return BASE_PROFIT_RATE + risk_bonus

# 3.4 成本加成计算所有生产品指导价
def compute_base_prices():
    prices = {}
    # 电力生产成本
    elec_info = prod_data.get("电力")
    if elec_info:
        labor = elec_info["wage"] / elec_info["output"]
        prices["电力"] = round(labor * (1 + get_profit_rate("电力", prices)), 2)

    # 按依赖顺序逐层计算，直到全部算出
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
                profit_rate = get_profit_rate(p, prices)
                price = round((mat_cost + labor) * (1 + profit_rate), 2)
                # 零售品价格上限
                if p in retail_base_price_map:
                    ceiling = retail_base_price_map[p] * 0.9
                    price = min(price, ceiling)
                prices[p] = price
                solved.add(p)
        if not solved:
            # 有循环依赖或未知原料，强制用劳动力成本*2保底
            for p in remaining:
                if p not in prices:
                    info = prod_data[p]
                    labor = info["wage"] / info["output"]
                    prices[p] = round(labor * 2.0, 2)
            break
        remaining -= solved
    return prices

# 生成1.0倍率下的静态均衡指导价
full_base_prices = compute_base_prices()

# ========== 4. 计算统一市场倍率 ==========
total_w = 0.0
sum_m = 0.0
for item in retail_rows:
    name = item["name"]
    if name not in full_base_prices:
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

# ========== 5. 最终指导价（动态） ==========
final_prices = {name: round(bp * unified_mult, 2) for name, bp in full_base_prices.items()}

# ========== 6. 极限利润计算 ==========
def calc_limit_profit(item_name, prices, is_retail=False):
    if item_name in prod_data and not is_retail:
        info = prod_data[item_name]
        wage = info["wage"]
        output = info["output"]
        price = prices.get(item_name, 0)
        # 计算原料成本
        recipe = info["recipe"]
        batch = info.get("batch", 1)
        mat_cost = 0.0
        for ing, amount in recipe.items():
            per_unit = amount / batch
            mat_cost += per_unit * prices.get(ing, 0)
        gross = output * (price - mat_cost) - wage
        if gross <= 0:
            return 0, 0, 0
        n_opt = int(gross / (2 * wage * mgmt_rate) - 0.5)
        if n_opt < 1: n_opt = 1
        limit = gross * n_opt - wage * (n_opt ** 2) * mgmt_rate
        return round(limit, 0), n_opt, round(gross, 2)

    # 零售建筑
    for shop, data in retail_data.items():
        if item_name in data["items"]:
            wage = data["wage"]
            retail_price = retail_price_map.get(item_name)
            if not retail_price: continue
            buy_price = prices.get(item_name, 0)
            sales = data["items"][item_name]
            gross = sales * (retail_price - buy_price) - wage
            if gross <= 0: return 0, 0, 0
            n_opt = int(gross / (2 * wage * mgmt_rate) - 0.5)
            if n_opt < 1: n_opt = 1
            limit = gross * n_opt - wage * (n_opt ** 2) * mgmt_rate
            # 零售端额外加成5%
            limit = round(limit * 1.05, 0)
            return round(limit, 0), n_opt, round(gross, 2)
    return 0, 0, 0

# ========== 7. 输出 data_output.json ==========
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
            limit, opt, gross = calc_limit_profit(rname, final_prices, is_retail=True)
            building_profits[f"零售_{rname}"] = {"limit": limit, "opt_level": opt, "gross": gross}

output["building_profits"] = building_profits

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"✅ 统一倍率 {unified_mult:.4f}，指导价已更新（分层利润率模型）")
