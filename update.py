import json
import requests
from datetime import datetime, timezone, timedelta

# ========== 1. 加载数据 ==========
with open("game_data.json", "r", encoding="utf-8") as f:
    buildings = json.load(f)

prod_data = {}
for b in buildings:
    bname = b["name"]
    wage = b["wage"]
    for prod in b["products"]:
        pname = prod["name"]
        prod_data[pname] = {
            "building": bname,
            "wage": wage,
            "output": prod["output"],
            "inputs": prod["inputs"]
        }

retail_data = {
    "生鲜商店": {"wage": 9660, "items": { "苹果": 902.6, "橘子": 714.2, "葡萄": 649.9, "牛排": 246.9, "香肠": 784.7, "鸡蛋": 3119.5, "咖啡粉": 2214, "苹果派": 483, "橙汁": 120.5, "苹果汁": 233, "姜汁汽水": 79.1, "披萨": 172, "芝士": 705, "巧克力": 420 }},
    "快餐店": {"wage": 41090, "items": { "牛奶": 2400, "面包": 720, "黄油": 660, "汉堡": 50, "千层面": 90, "肉丸": 84, "混合果汁": 50, "沙拉": 125, "咖喱角": 117 }},
    "五金商店": {"wage": 12110, "items": { "砖块": 1618, "水泥": 1130, "木板": 2272, "窗户": 648, "工具": 806 }},
    "时装商店": {"wage": 21770, "items": { "内衣": 484, "手套": 369, "裙子": 416.9, "高跟鞋": 584, "手袋": 341, "运动鞋": 294.3, "名牌手表": 70, "项链": 30 }},
    "加油站": {"wage": 24150, "items": { "汽油": 1883, "柴油": 1812 }},
    "电子产品商店": {"wage": 12110, "items": { "智能手机": 33, "平板电脑": 12, "笔记本电脑": 18, "显示器": 38, "电视机": 32, "无人机": 23 }},
    "车行": {"wage": 26600, "items": { "经济电动车": 28, "豪华电动车": 14, "经济燃油车": 35, "豪华燃油车": 11, "卡车": 23 }}
}

mgmt_rate = 0.0058

url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(url, timeout=15)
resp.raise_for_status()
api_json = resp.json()
retail_rows = api_json.get("rows", [])
retail_price_map = {item["name"]: item["retailPrice"] for item in retail_rows}
retail_base_price_map = {item["name"]: item["basePrice"] for item in retail_rows}

# ========== 2. 辅助函数 ==========
def material_cost(product_name, prices):
    if product_name not in prod_data: return 0.0
    total = 0.0
    for ing, amount in prod_data[product_name]["inputs"].items():
        total += amount * prices.get(ing, 0)
    return total

def limit_profit(product_name, prices, is_retail=False):
    if is_retail:
        for shop, data in retail_data.items():
            if product_name in data["items"]:
                wage = data["wage"]
                rp = retail_price_map.get(product_name, 0)
                bp = prices.get(product_name, 0)
                sales = data["items"][product_name]
                gross = sales * (rp - bp) - wage
                if gross <= 0: return 0
                n = int(gross / (2 * wage * mgmt_rate) - 0.5)
                if n < 1: n = 1
                return gross * n - wage * (n ** 2) * mgmt_rate
        return 0
    else:
        if product_name not in prod_data: return 0
        info = prod_data[product_name]
        wage = info["wage"]
        output = info["output"]
        price = prices.get(product_name, 0)
        mat = material_cost(product_name, prices)
        gross = output * (price - mat) - wage
        if gross <= 0: return 0
        n = int(gross / (2 * wage * mgmt_rate) - 0.5)
        if n < 1: n = 1
        return gross * n - wage * (n ** 2) * mgmt_rate

# ========== 3. 初始成本加成价格 ==========
prices = {}
elec = prod_data["电力"]
prices["电力"] = round((elec["wage"] / elec["output"]) * 1.15, 2)

remaining = set(prod_data.keys()) - {"电力"}
while remaining:
    solved = set()
    for p in remaining:
        info = prod_data[p]
        mat = 0.0
        known = True
        for ing, amount in info["inputs"].items():
            if ing not in prices: known = False; break
            mat += amount * prices[ing]
        if known:
            labor = info["wage"] / info["output"]
            prices[p] = round((mat + labor) * 1.15, 2)
            solved.add(p)
    if not solved:
        for p in remaining:
            if p not in prices:
                prices[p] = round(prod_data[p]["wage"] / prod_data[p]["output"] * 2.0, 2)
        break
    remaining -= solved

for p in retail_base_price_map:
    prices[p] = retail_base_price_map[p]

# ========== 4. 迭代均衡（目标CV ≤ 0.5） ==========
TOLERANCE = 0.50
print("开始迭代均衡...")
for iteration in range(200):
    prod_limits = {}
    for pname in prod_data:
        lp = limit_profit(pname, prices)
        if lp > 0: prod_limits[pname] = lp

    if len(prod_limits) < 5: break

    vals = list(prod_limits.values())
    mean = sum(vals) / len(vals)
    variance = sum((v - mean) ** 2 for v in vals) / len(vals)
    cv = (variance ** 0.5) / mean if mean > 0 else float('inf')

    if cv < TOLERANCE:
        print(f"第{iteration+1}次迭代，CV={cv:.4f}，已达目标")
        break

    max_prod = max(prod_limits, key=prod_limits.get)
    min_prod = min(prod_limits, key=prod_limits.get)

    new_max = round(prices[max_prod] * 0.98, 2)
    new_min = round(prices[min_prod] * 1.02, 2)

    prices[max_prod] = max(new_max, material_cost(max_prod, prices) * 1.01)
    if min_prod in retail_base_price_map:
        prices[min_prod] = min(new_min, retail_base_price_map[min_prod])
    else:
        prices[min_prod] = new_min

    if iteration % 50 == 0:
        print(f"迭代 {iteration+1}, CV={cv:.4f}, 调整 {max_prod}↓, {min_prod}↑")

# 最终保底
for p in prod_data:
    if p == "电力" or p in retail_base_price_map: continue
    mat = material_cost(p, prices)
    if prices[p] < mat * 1.05: prices[p] = round(mat * 1.05, 2)

# ========== 5. 统一市场倍率 ==========
total_weight = 0.0
sum_mult = 0.0
for item in retail_rows:
    name = item["name"]
    if name not in prices: continue
    speed = 0
    for shop, data in retail_data.items():
        if name in data["items"]: speed = data["items"][name]; break
    if speed > 0:
        sum_mult += item["multiplier"] * speed
        total_weight += speed

unified_mult = sum_mult / total_weight if total_weight > 0 else 1.0

final_prices = {}
for name, bp in prices.items():
    dynamic = round(bp * unified_mult, 2)
    if name in retail_price_map:
        dynamic = min(dynamic, round(retail_price_map[name] * 0.98, 2))
    final_prices[name] = dynamic

# ========== 6. 输出 ==========
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

bp_dict = {}
for p in prod_data:
    lp = limit_profit(p, prices, False)
    bp_dict[p] = {"limit": round(lp, 0), "opt_level": 0}
    info = prod_data[p]
    wage = info["wage"]; output = info["output"]
    price = prices.get(p, 0); mat = material_cost(p, prices)
    gross = output * (price - mat) - wage
    if gross > 0:
        n = int(gross / (2 * wage * mgmt_rate) - 0.5)
        if n < 1: n = 1
        bp_dict[p]["opt_level"] = n

for shop, data in retail_data.items():
    for rname in data["items"]:
        if rname in retail_price_map:
            lp = limit_profit(rname, prices, True)
            bp_dict[f"零售_{rname}"] = {"limit": round(lp, 0), "opt_level": 0}
            wage = data["wage"]; rp = retail_price_map.get(rname, 0)
            bp = prices.get(rname, 0); sales = data["items"][rname]
            gross = sales * (rp - bp) - wage
            if gross > 0:
                n = int(gross / (2 * wage * mgmt_rate) - 0.5)
                if n < 1: n = 1
                bp_dict[f"零售_{rname}"]["opt_level"] = n

output["building_profits"] = bp_dict

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"✅ 统一倍率 {unified_mult:.4f}，迭代均衡完成 (目标CV≤{TOLERANCE})")
