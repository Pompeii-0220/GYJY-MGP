import json
import requests
from datetime import datetime, timezone, timedelta
import copy

# ========== 你原有的1.0倍率均衡价（基石） ==========
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

# ========== 加载静态数据 ==========
with open("game_data.json", "r", encoding="utf-8") as f:
    gd = json.load(f)

prod_data = gd["production"]
retail_data = gd["retail"]
mgmt_rate = gd["management_rate"]

# ========== 抓取 API 零售价 ==========
api_url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(api_url)
resp.raise_for_status()
api_json = resp.json()
retail_rows = api_json.get("rows", [])
retail_price_map = {item["name"]: item["retailPrice"] for item in retail_rows}

# ========== 极限利润计算函数 ==========
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
            mat_cost += per_unit * prices.get(ing, 0)
        gross = output * product_price - output * mat_cost - wage
        if gross <= 0:
            return 0, 0, 0
        n_opt = int(gross / (2 * wage * mgmt_rate) - 0.5)
        if n_opt < 1: n_opt = 1
        limit = gross * n_opt - wage * (n_opt ** 2) * mgmt_rate
        return round(limit, 0), n_opt, round(gross, 2)
    # 零售建筑暂不用于寻优，直接返回0避免干扰
    return 0, 0, 0

# ========== 自动寻优新增产品均衡价 ==========
def auto_tune_prices(base_prices, prod_data, retail_price_map):
    prices = copy.deepcopy(base_prices)
    # 初始化缺失产品价格：劳动力成本 × 2（确保为正）
    for pname in prod_data:
        if pname not in prices:
            labor = prod_data[pname]["wage"] / prod_data[pname]["output"]
            prices[pname] = round(labor * 2.0, 2)

    # 确定哪些是“锚点产品”（有零售价且已存在均衡价的产品）
    anchor_products = [p for p in base_prices if p in retail_price_map]
    if not anchor_products:
        return prices  # 没有锚点，无法调优

    for iteration in range(200):  # 最多200次迭代
        # 计算所有建筑的极限利润
        profits = {}
        for pname in prod_data:
            limit, _, _ = calc_limit_profit(pname, prices)
            profits[pname] = limit

        # 计算锚点产品的平均极限利润（只取利润>0的）
        anchor_limits = [profits[p] for p in anchor_products if profits[p] > 0]
        if not anchor_limits:
            break
        target_limit = sum(anchor_limits) / len(anchor_limits)

        # 调整每个新增产品的价格
        max_adjustment = 0.0
        for pname in prod_data:
            if pname in base_prices:  # 锚点不动
                continue
            current_limit = profits.get(pname, 0)
            if current_limit <= 0:
                # 利润为0或负，大幅提价20%
                prices[pname] = round(prices[pname] * 1.2, 2)
                max_adjustment = max(max_adjustment, 0.2)
            else:
                # 计算偏差比例，并相应调整价格
                ratio = current_limit / target_limit
                if ratio > 1.15:  # 利润偏高，降价
                    factor = 1.0 / ratio
                    new_price = round(prices[pname] * factor, 2)
                elif ratio < 0.85:  # 利润偏低，提价
                    factor = 1.0 + (1.0 - ratio)
                    new_price = round(prices[pname] * factor, 2)
                else:
                    continue
                # 对于零售品，价格不能超过零售价的95%
                if pname in retail_price_map:
                    ceiling = retail_price_map[pname] * 0.95
                    new_price = min(new_price, ceiling)
                if new_price > 0:
                    prices[pname] = new_price
                    max_adjustment = max(max_adjustment, abs(new_price - prices.get(pname, 0)) / prices.get(pname, 1))

        # 收敛条件：所有价格调整幅度 < 0.5%
        if max_adjustment < 0.005:
            print(f"寻优在第{iteration+1}次迭代后收敛")
            break

    return prices

# 尝试加载已保存的完整基石价格文件，若无则自动生成
try:
    with open("static_base_prices.json", "r") as f:
        full_base_prices = json.load(f)
    print("已加载现存静态基石价格表")
except:
    print("正在自动生成新增产品的均衡价...")
    full_base_prices = auto_tune_prices(BASE_GUIDE_PRICES, prod_data, retail_price_map)
    with open("static_base_prices.json", "w") as f:
        json.dump(full_base_prices, f, indent=2)
    print("已生成并保存 static_base_prices.json")

# ========== 计算统一市场倍率 ==========
total_weight = 0.0
sum_mult = 0.0
for item in retail_rows:
    name = item.get("name")
    if name not in full_base_prices:
        continue
    sales_speed = 0
    for shop, data in retail_data.items():
        if name in data["items"]:
            sales_speed = data["items"][name]
            break
    if sales_speed > 0:
        sum_mult += item["multiplier"] * sales_speed
        total_weight += sales_speed

unified_mult = sum_mult / total_weight if total_weight > 0 else 1.0

# ========== 生成最终指导价 ==========
final_prices = {}
for name, bp in full_base_prices.items():
    final_prices[name] = round(bp * unified_mult, 2)

# ========== 输出 data_output.json ==========
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
    json.dump(output,
