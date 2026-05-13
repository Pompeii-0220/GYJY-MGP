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

# ========== 2. 抓取 API 实时零售价 ==========
api_url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(api_url, timeout=15)
resp.raise_for_status()
api_json = resp.json()
retail_rows = api_json.get("rows", [])

retail_price_map = {item["name"]: item["retailPrice"] for item in retail_rows}
print(f"API零售品数量: {len(retail_rows)}")

# ========== 3. 加权传导定价 ==========
# 从零售价出发，向上游加权迭代
prices = dict(retail_price_map)  # 终端品价格直接用 API 零售价

# 迭代计算中间品价格
changed = True
while changed:
    changed = False
    for product, info in prod_data.items():
        if product in prices:  # 已经定价（包括终端品）
            continue
        # 找到所有以本产品为原料的下游产品
        downstream_demand = []
        for down_prod, down_info in prod_data.items():
            if product in down_info["recipe"]:
                # 下游产品每小时的产量
                output = down_info["output"]
                # 下游产品配方中消耗本产品的数量（每产出1个下游产品）
                batch = down_info.get("batch", 1)
                amount_per = down_info["recipe"][product] / batch
                # 下游产品当前价格（必须已知才能参与加权）
                if down_prod in prices:
                    speed = output
                    demand = speed * amount_per
                    downstream_demand.append((demand, prices[down_prod]))

        if downstream_demand:
            total_weight = sum(d for d, _ in downstream_demand)
            weighted_sum = sum(d * p for d, p in downstream_demand)
            new_price = round(weighted_sum / total_weight, 2)
            if product not in prices or prices[product] != new_price:
                prices[product] = new_price
                changed = True

# 对于仍然没有价格的产品（未被任何下游消耗），使用劳动力成本×1.5保底
for pname in prod_data:
    if pname not in prices:
        info = prod_data[pname]
        labor = info["wage"] / info["output"]
        prices[pname] = round(labor * 1.5, 2)

print(f"加权传导定价完毕，商品数: {len(prices)}")

# ========== 4. 计算极限利润 ==========
def calc_limit_profit(item_name, prices):
    # 生产建筑
    if item_name in prod_data:
        info = prod_data[item_name]
        wage = info["wage"]
        output = info["output"]
        price = prices.get(item_name, 0)
        # 原料成本
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

    # 零售建筑
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

# ========== 5. 输出 data_output.json ==========
beijing_tz = timezone(timedelta(hours=8))
update_time = datetime.now(tz=beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

output = {
    "update_time": update_time,
    "items": [],
    "retail_prices": retail_price_map
}

all_items = set(prices.keys()) | {name for r in retail_data.values() for name in r["items"].keys()}
for item in all_items:
    output["items"].append({
        "name": item,
        "price": prices.get(item, 0),
        "retail_price": retail_price_map.get(item),
        "is_retail": item in retail_price_map
    })

building_profits = {}
for pname in prod_data:
    limit, opt = calc_limit_profit(pname, prices)
    building_profits[pname] = {"limit": limit, "opt_level": opt}
for shop, data in retail_data.items():
    for rname in data["items"]:
        if rname in retail_price_map:
            limit, opt = calc_limit_profit(rname, prices)
            building_profits[f"零售_{rname}"] = {"limit": limit, "opt_level": opt}

output["building_profits"] = building_profits

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print("✅ 加权传导指导价已生成（无价格上限限制）")
