import json
import requests
from datetime import datetime, timezone, timedelta
import copy

# ========== 1. 你原有的1.0倍率均衡价（基石） ==========
BASE_GUIDE_PRICES = {
    "电力": 2.44, "水": 3.85, "原油": 239.26, "种子": 3.10,
    "苹果": 26.62, "可可": 21.19, "咖啡豆": 10.89, "棉花": 16.30,
    "谷物": 8.02, "葡萄": 33.46, "木材": 50.00, "橘子": 27.66,
    "甘蔗": 18.40, "蔬菜": 31.28, "鸡蛋": 14.75, "牛奶": 90.11,
    "皮革": 289, "牛": 1537, "猪": 1495, "苹果汁": 289,
    "姜汁汽水": 501.93, "橙汁": 357.89, "香肠": 174.85, "牛排": 436.07,
    "糖": 172.99, "黄油": 516.88, "芝士": 1773, "巧克力": 2270,
    "面条": 725.23, "植物油": 475.71, "披萨": 6355, "面团": 1852.15,
    "面包": 2406.61, "苹果派": 3360.27, "咖喱角": 5801, "汉堡": 21228,
    "千层面": 18936, "肉丸": 23196, "混合果汁": 22281, "沙拉": 8147,
    "酱汁": 11367, "棉布": 61.04, "裙子": 271.93, "手套": 218.74,
    "手袋": 381.34, "高跟鞋": 371.74, "运动鞋": 130.60, "内衣": 98.85,
    "塑料": 94.43, "动物饲料": 116.51, "咖啡粉": 364.97, "面粉": 187.82,
}

# ========== 2. 加载静态数据 ==========
with open("game_data.json", "r", encoding="utf-8") as f:
    gd = json.load(f)

prod_data = gd["production"]
retail_data = gd["retail"]
mgmt_rate = gd["management_rate"]

# ========== 3. 抓取 API 零售价 ==========
api_url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(api_url)
resp.raise_for_status()
api_json = resp.json()
retail_rows = api_json.get("rows", [])
retail_price_map = {item["name"]: item["retailPrice"] for item in retail_rows}

# ========== 4. 计算原料成本（基于当前价格） ==========
def calc_material_cost(product_name, prices):
    if product_name not in prod_data:
        return 0.0
    info = prod_data[product_name]
    recipe = info["recipe"]
    batch = info.get("batch", 1)
    cost = 0.0
    for ing, amount in recipe.items():
        per_unit = amount / batch
        cost += per_unit * prices.get(ing, 0)
    return cost

# ========== 5. 极限利润计算 ==========
def calc_limit_profit(item_name, prices):
    if item_name in prod_data:
        info = prod_data[item_name]
        wage = info["wage"]
        output = info["output"]
        price = prices.get(item_name, 0)
        mat_cost = calc_material_cost(item_name, prices)
        gross = output * (price - mat_cost) - wage
        if gross <= 0:
            return 0, 0, 0
        n_opt = int(gross / (2 * wage * mgmt_rate) - 0.5)
        if n_opt < 1:
            n_opt = 1
        limit = gross * n_opt - wage * (n_opt ** 2) * mgmt_rate
        return round(limit, 0), n_opt, round(gross, 2)

    for shop, data in retail_data.items():
        if item_name in data["items"]:
            wage = data["wage"]
            retail_price = retail_price_map.get(item_name)
            if not retail_price:
                continue
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

# ========== 6. 自动寻优新产品的均衡价 ==========
def auto_tune(base_prices):
    prices = copy.deepcopy(base_prices)
    # 初始化缺失产品：原料成本×1.5（保证盈利）
    for pname in prod_data:
        if pname not in prices:
            mat = calc_material_cost(pname, prices)
            if mat > 0:
                prices[pname] = round(mat * 1.5, 2)
            else:
                labor = prod_data[pname]["wage"] / prod_data[pname]["output"]
                prices[pname] = round(labor * 2.0, 2)

    # 锚点：有零售价且已存在均衡价的产品
    anchors = [p for p in base_prices if p in retail_price_map]

    for it in range(300):
        # 计算所有利润
        profits = {}
        for pname in prod_data:
            limit, _, _ = calc_limit_profit(pname, prices)
            profits[pname] = limit

        # 计算锚点平均极限利润（排除0）
        anchor_limits = [profits[p] for p in anchors if profits[p] > 0]
        if not anchor_limits:
            break
        target = sum(anchor_limits) / len(anchor_limits)

        # 调整非锚点产品价格
        max_adj = 0.0
        for pname in prod_data:
            if pname in base_prices:
                continue
            cur = profits.get(pname, 0)
            mat = calc_material_cost(pname, prices)
            # 价格下限：原料成本×1.2
            floor = mat * 1.2 if mat > 0 else 0.01

            if cur <= 0:
                # 大幅提价
                prices[pname] = round(max(prices[pname] * 1.3, floor), 2)
                max_adj = max(max_adj, 0.3)
            else:
                ratio = cur / target
                if ratio > 1.2:
                    factor = 1.0 / ratio
                    new_price = max(round(prices[pname] * factor, 2), floor)
                elif ratio < 0.8:
                    factor = 1.0 + (1.0 - ratio)
                    new_price = round(prices[pname] * factor, 2)
                else:
                    continue

                # 零售品上限
                if pname in retail_price_map:
                    ceiling = retail_price_map[pname] * 0.9
                    new_price = min(new_price, ceiling)

                prices[pname] = new_price
                max_adj = max(max_adj, abs(new_price - prices[pname]) / max(prices[pname], 0.01))

        if max_adj < 0.01:
            print(f"均衡价寻优在第{it+1}次收敛")
            break

    return prices

# 加载或生成完整基石
try:
    with open("static_base_prices.json", "r") as f:
        full_base = json.load(f)
    print("已加载 static_base_prices.json")
except:
    print("正在为新产品生成均衡价（带成本约束）...")
    full_base = auto_tune(BASE_GUIDE_PRICES)
    with open("static_base_prices.json", "w") as f:
        json.dump(full_base, f, indent=2)
    print("已保存 static_base_prices.json")

# ========== 7. 统一市场倍率 ==========
total_w = 0.0
sum_m = 0.0
for item in retail_rows:
    name = item["name"]
    if name not in full_base:
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

# ========== 8. 最终指导价 ==========
final_prices = {name: round(bp * unified_mult, 2) for name, bp in full_base.items()}

# ========== 9. 输出 data_output.json ==========
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

print(f"✅ 统一倍率 {unified_mult:.4f}，指导价已更新")
