import json
import requests
from datetime import datetime, timezone, timedelta

# ========== 1. 加载新格式数据 ==========
with open("game_data.json", "r", encoding="utf-8") as f:
    buildings = json.load(f)

# 转换为产品维度的字典
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

# ========== 2. 零售数据（你提供的表格） ==========
retail_data = {
    "生鲜商店": {"wage": 9660, "items": {
        "苹果": 902.6, "橘子": 714.2, "葡萄": 649.9, "牛排": 246.9,
        "香肠": 784.7, "鸡蛋": 3119.5, "咖啡粉": 2214, "苹果派": 483,
        "橙汁": 120.5, "苹果汁": 233, "姜汁汽水": 79.1, "披萨": 172,
        "芝士": 705, "巧克力": 420
    }},
    "快餐店": {"wage": 41090, "items": {
        "牛奶": 2400, "面包": 720, "黄油": 660, "汉堡": 50,
        "千层面": 90, "肉丸": 84, "混合果汁": 50, "沙拉": 125,
        "咖喱角": 117
    }},
    "五金商店": {"wage": 12110, "items": {
        "砖块": 1618, "水泥": 1130, "木板": 2272, "窗户": 648,
        "工具": 806
    }},
    "时装商店": {"wage": 21770, "items": {
        "内衣": 484, "手套": 369, "裙子": 416.9, "高跟鞋": 584,
        "手袋": 341, "运动鞋": 294.3, "名牌手表": 70, "项链": 30
    }},
    "加油站": {"wage": 24150, "items": {
        "汽油": 1883, "柴油": 1812
    }},
    "电子产品商店": {"wage": 12110, "items": {
        "智能手机": 33, "平板电脑": 12, "笔记本电脑": 18, "显示器": 38,
        "电视机": 32, "无人机": 23
    }},
    "车行": {"wage": 26600, "items": {
        "经济电动车": 28, "豪华电动车": 14, "经济燃油车": 35,
        "豪华燃油车": 11, "卡车": 23
    }}
}

mgmt_rate = 0.0058

# ========== 3. 抓取 API 零售价 ==========
url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(url, timeout=15)
resp.raise_for_status()
api_json = resp.json()
retail_rows = api_json.get("rows", [])
retail_price_map = {item["name"]: item["retailPrice"] for item in retail_rows}
retail_base_price_map = {item["name"]: item["basePrice"] for item in retail_rows}

print(f"API 零售品数量: {len(retail_rows)}")

# ========== 4. 计算基石价 ==========
PROFIT_RATE = 0.15

prices = {}
elec = prod_data["电力"]
labor_elec = elec["wage"] / elec["output"]
prices["电力"] = round(labor_elec * (1 + PROFIT_RATE), 2)

remaining = set(prod_data.keys()) - {"电力"}
while remaining:
    solved = set()
    for p in remaining:
        info = prod_data[p]
        inputs = info["inputs"]
        all_known = True
        mat_cost = 0.0
        for ing, amount in inputs.items():
            if ing not in prices:
                all_known = False
                break
            mat_cost += amount * prices[ing]
        if all_known:
            labor = info["wage"] / info["output"]
            price = round((mat_cost + labor) * (1 + PROFIT_RATE), 2)
            prices[p] = price
            solved.add(p)
    if not solved:
        for p in remaining:
            if p not in prices:
                labor = prod_data[p]["wage"] / prod_data[p]["output"]
                prices[p] = round(labor * 2.0, 2)
        break
    remaining -= solved

# ========== 5. 价格保底（非零售品） ==========
for _ in range(3):
    for p in prod_data:
        if p == "电力" or p in retail_base_price_map:
            continue
        info = prod_data[p]
        mat = 0.0
        for ing, amount in info["inputs"].items():
            mat += amount * prices.get(ing, 0)
        if prices[p] < mat * 1.05:
            prices[p] = round(mat * 1.05, 2)

# ========== 6. 零售品锁定 API 基础价 ==========
for p in retail_base_price_map:
    prices[p] = retail_base_price_map[p]

# ========== 7. 统一市场倍率 ==========
total_weight = 0.0
sum_mult = 0.0
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
        sum_mult += item["multiplier"] * speed
        total_weight += speed

unified_mult = sum_mult / total_weight if total_weight > 0 else 1.0

# ========== 8. 动态指导价（安全帽 0.98） ==========
final_prices = {}
for name, bp in prices.items():
    dynamic = round(bp * unified_mult, 2)
    if name in retail_price_map:
        cap = round(retail_price_map[name] * 0.98, 2)
        dynamic = min(dynamic, cap)
    final_prices[name] = dynamic

# ========== 9. 极限利润 ==========
def calc_limit(item_name, prices, is_retail=False):
    if is_retail:
        for shop, data in retail_data.items():
            if item_name in data["items"]:
                wage = data["wage"]
                rp = retail_price_map.get(item_name, 0)
                bp = prices.get(item_name, 0)
                sales = data["items"][item_name]
                gross = sales * (rp - bp) - wage
                if gross <= 0:
                    return 0, 0, 0
                n = int(gross / (2 * wage * mgmt_rate) - 0.5)
                if n < 1: n = 1
                limit = gross * n - wage * (n ** 2) * mgmt_rate
                return round(limit, 0), n, round(gross, 2)
        return 0, 0, 0
    else:
        if item_name not in prod_data:
            return 0, 0, 0
        info = prod_data[item_name]
        wage = info["wage"]
        output = info["output"]
        price = prices.get(item_name, 0)
        mat = 0.0
        for ing, amount in info["inputs"].items():
            mat += amount * prices.get(ing, 0)
        gross = output * (price - mat) - wage
        if gross <= 0:
            return 0, 0, 0
        n = int(gross / (2 * wage * mgmt_rate) - 0.5)
        if n < 1: n = 1
        limit = gross * n - wage * (n ** 2) * mgmt_rate
        return round(limit, 0), n, round(gross, 2)

# ========== 10. 输出 ==========
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

bp = {}
for p in prod_data:
    limit, opt, _ = calc_limit(p, prices, False)
    bp[p] = {"limit": limit, "opt_level": opt}
for shop, data in retail_data.items():
    for rname in data["items"]:
        if rname in retail_price_map:
            limit, opt, _ = calc_limit(rname, prices, True)
            bp[f"零售_{rname}"] = {"limit": limit, "opt_level": opt}
output["building_profits"] = bp

with open("data_output.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"✅ 统一倍率 {unified_mult:.4f}，指导价已生成")
