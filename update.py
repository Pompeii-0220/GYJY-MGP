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

# ========== 3. 为所有产品生成1倍率基石价 ==========
prices = dict(BASE_GUIDE_PRICES)

# 电力基准
if "电力" not in prices:
    elec = prod_data["电力"]
    labor = elec["wage"] / elec["output"]
    prices["电力"] = round(labor * 1.15, 2)

# 按依赖顺序计算缺失产品的成本加成价
remaining = set(prod_data.keys()) - set(prices.keys())
while remaining:
    solved = set()
    for p in remaining:
        info = prod_data[p]
        recipe = info["recipe"]
        batch = info.get("batch", 1)
        all_known = True
        mat = 0.0
        for ing, amount in recipe.items():
            if ing not in prices:
                all_known = False
                break
            per = amount / batch
            mat += per * prices[ing]
        if all_known:
            labor = info["wage"] / info["output"]
            price = round((mat + labor) * 1.15, 2)
            # 不再用API基础价替代，完全成本加成
            prices[p] = price
            solved.add(p)
    if not solved:
        for p in remaining:
            if p not in prices:
                labor = prod_data[p]["wage"] / prod_data[p]["output"]
                prices[p] = round(labor * 2.0, 2)
        break
    remaining -= solved

# ========== 4. 统一市场倍率 ==========
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

# ========== 5. 动态指导价（加零售安全帽） ==========
final_prices = {}
for name, bp in prices.items():
    dynamic = round(bp * unified_mult, 2)
    if name in retail_price_map:
        cap = round(retail_price_map[name] * 0.98, 2)
        dynamic = min(dynamic, cap)
    final_prices[name] = dynamic

# ========== 6. 极限利润计算（可供前端扩展） ==========
def calc_limit(item_name, prices):
    if item_name in prod_data:
        info = prod_data[item_name]
        wage = info["wage"]
        output = info["output"]
        price = prices.get(item_name, 0)
        recipe = info["recipe"]
        batch = info.get("batch", 1)
        mat = 0.0
        for ing, amount in recipe.items():
            per = amount / batch
            mat += per * prices.get(ing, 0)
        gross = output * (price - mat) - wage
        if gross <= 0:
            return 0, 0
        n_opt = int(gross / (2 * wage * mgmt_rate) - 0.5)
        if n_opt < 1: n_opt = 1
        limit = gross * n_opt - wage * (n_opt ** 2) * mgmt_rate
        return round(limit, 0), n_opt

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
            if n_opt < 1: n_opt = 1
            limit = gross * n_opt - wage * (n_opt ** 2) * mgmt_rate
            return round(limit, 0), n_opt
    return 0, 0

# ========== 7. 输出 data_output.json ==========
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
        "base_price": prices.get(item, 0),  # 1.0倍率基石价
        "retail_price": retail_price_map.get(item),
        "is_retail": item in retail_price_map
    })

building_profits = {}
for p in prod_data:
    limit, opt = calc_limit(p, final_prices)
    building_profits[p] = {"limit": limit, "opt_level": opt}
for shop, data in retail_data.items():
    for rname in data["items"]:
        if rname in retail_price_map:
            limit, opt = calc_limit(rname, final_prices)
            building_profits[f"零售_{rname}"] = {"limit": limit, "opt_level": opt}

output["building_profits"] = building_profits

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"✅ 统一倍率 {unified_mult:.4f}，指导价已生成（旧均衡基石 + 全成本加成）")
