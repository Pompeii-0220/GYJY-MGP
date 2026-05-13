import json
import requests
from datetime import datetime, timezone, timedelta

# ========== 旧产业链均衡价（1.0倍率基石） ==========
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
    """计算1个单位产品的原料成本"""
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
    """计算生产建筑或零售建筑的1级时利润、最优等级、极限利润"""
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
prices = dict(BASE_GUIDE_PRICES)

# 对缺失产品先用零售基础价填充（如果有），否则用成本加成估计
for p in prod_data:
    if p not in prices:
        if p in retail_base_price_map:
            prices[p] = retail_base_price_map[p]
        else:
            # 成本加成临时估计
            labor = prod_data[p]["wage"] / prod_data[p]["output"]
            prices[p] = round(labor * 2.0, 2)

# ========== 5. 迭代均衡基石价 ==========
print("开始迭代均衡基石价...")
for iteration in range(50):
    changed = False
    for pname in prod_data:
        if pname in BASE_GUIDE_PRICES:  # 旧产品不动
            continue
        # 只有同时有生产和零售的产品才需要平衡
        is_retail = pname in retail_base_price_map
        if not is_retail:
            continue  # 纯中间品不直接零售，不需要平衡销售端

        # 读取当前价格
        current_price = prices[pname]

        # 计算当前状态下生产和零售的极限利润差
        prod_limit, _, _ = calc_limit_profit(pname, prices, is_retail=False)
        retail_limit, _, _ = calc_limit_profit(pname, prices, is_retail=True)

        if prod_limit == 0 and retail_limit == 0:
            continue  # 两者均无利润，调整无效，跳过

        # 二分法调整基石价，使得生产与零售极限利润差接近0
        lo = max(calc_material_cost(pname, prices) * 1.01, 0.01)  # 不低于原料成本
        hi = retail_base_price_map.get(pname, current_price * 2)  # 不高于零售基础价
        if hi <= lo:
            continue

        best_price = current_price
        best_diff = abs(prod_limit - retail_limit)

        for _ in range(20):
            mid = (lo + hi) / 2
            temp_prices = prices.copy()
            temp_prices[pname] = mid
            p_lim, _, _ = calc_limit_profit(pname, temp_prices, is_retail=False)
            r_lim, _, _ = calc_limit_profit(pname, temp_prices, is_retail=True)

            if p_lim == 0 and r_lim == 0:
                break
            diff = abs(p_lim - r_lim)
            if diff < best_diff:
                best_diff = diff
                best_price = mid

            # 如果生产利润 > 零售利润，说明价格偏高（生产赚得多），应降价
            if p_lim > r_lim:
                hi = mid
            else:
                lo = mid

        new_price = round(best_price, 2)
        if new_price != current_price:
            prices[pname] = new_price
            changed = True

    if not changed:
        print(f"  迭代第{iteration+1}次收敛，停止")
        break

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

# ========== 7. 动态指导价（加零售安全帽） ==========
final_prices = {}
for name, bp in prices.items():
    dynamic = round(bp * unified_mult, 2)
    if name in retail_price_map:
        cap = round(retail_price_map[name] * 0.98, 2)
        dynamic = min(dynamic, cap)
    final_prices[name] = dynamic

# ========== 8. 输出 data_output.json ==========
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
    limit, opt, _ = calc_limit_profit(p, prices, is_retail=False)
    building_profits[p] = {"limit": limit, "opt_level": opt}
for shop, data in retail_data.items():
    for rname in data["items"]:
        if rname in retail_price_map:
            limit, opt, _ = calc_limit_profit(rname, prices, is_retail=True)
            building_profits[f"零售_{rname}"] = {"limit": limit, "opt_level": opt}

output["building_profits"] = building_profits

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"✅ 均衡基石价生成完毕，统一倍率 {unified_mult:.4f}")
