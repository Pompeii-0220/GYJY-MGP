import json
import requests
from datetime import datetime, timezone, timedelta

with open("game_data.json", "r", encoding="utf-8") as f:
    gd = json.load(f)

prod_data = gd["production"]
retail_data = gd["retail"]
mgmt_rate = gd["management_rate"]

url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(url, timeout=15)
resp.raise_for_status()
api_json = resp.json()
retail_rows = api_json.get("rows", [])
retail_price_map = {item["name"]: item["retailPrice"] for item in retail_rows}
retail_base_price_map = {item["name"]: item["basePrice"] for item in retail_rows}

# ========== 1. 计算基石价 ==========
PR = 0.15
prices = {}
prices["电力"] = round(prod_data["电力"]["wage"] / prod_data["电力"]["output"] * (1 + PR), 2)

remaining = set(prod_data.keys()) - {"电力"}
while remaining:
    solved = set()
    for p in remaining:
        info = prod_data[p]
        recipe = info["recipe"]
        batch = info.get("batch", 1)
        mat = 0.0
        ok = True
        for ing, amt in recipe.items():
            if ing not in prices:
                ok = False; break
            mat += (amt / batch) * prices[ing]
        if not ok: continue
        labor = info["wage"] / info["output"]
        price = round((mat + labor) * (1 + PR), 2)
        prices[p] = price
        solved.add(p)
    if not solved:
        for p in remaining:
            if p not in prices:
                prices[p] = round(prod_data[p]["wage"] / prod_data[p]["output"] * 2, 2)
        break
    remaining -= solved

# ========== 2. 价格保底（仅非零售品） ==========
for _ in range(3):
    for p in prod_data:
        if p == "电力" or p in retail_base_price_map:  # 零售品跳过保底
            continue
        info = prod_data[p]
        mat = 0.0
        for ing, amt in info["recipe"].items():
            mat += (amt / info.get("batch", 1)) * prices.get(ing, 0)
        if prices[p] < mat * 1.05:
            prices[p] = round(mat * 1.05, 2)

# ========== 3. 零售品强制锁定API基础价 ==========
for p in retail_base_price_map:
    prices[p] = retail_base_price_map[p]

# ========== 4. 统一市场倍率 ==========
tw = sw = 0.0
for r in retail_rows:
    n = r["name"]
    if n not in prices: continue
    sp = 0
    for d in retail_data.values():
        if n in d["items"]:
            sp = d["items"][n]; break
    if sp:
        sw += r["multiplier"] * sp; tw += sp
um = sw / tw if tw else 1.0

# ========== 5. 动态指导价（含安全帽0.98） ==========
final = {}
for n, bp in prices.items():
    d = round(bp * um, 2)
    if n in retail_price_map:
        d = min(d, round(retail_price_map[n] * 0.98, 2))
    final[n] = d

# ========== 6. 极限利润计算 ==========
def lim(it, prc, retail=False):
    if retail:
        for d in retail_data.values():
            if it in d["items"]:
                wage = d["wage"]
                rp = retail_price_map.get(it, 0)
                bp = prc.get(it, 0)
                sl = d["items"][it]
                gr = sl*(rp-bp) - wage
                if gr <= 0: return 0,0,0
                n = int(gr/(2*wage*mgmt_rate)-0.5)
                if n < 1: n = 1
                return round(gr*n - wage*n*n*mgmt_rate, 0), n, round(gr,2)
        return 0,0,0
    else:
        if it not in prod_data: return 0,0,0
        info = prod_data[it]
        wage = info["wage"]
        out = info["output"]
        pr = prc.get(it, 0)
        mat = 0.0
        for ing, amt in info["recipe"].items():
            mat += (amt / info.get("batch", 1)) * prc.get(ing, 0)
        gr = out*(pr - mat) - wage
        if gr <= 0: return 0,0,0
        n = int(gr/(2*wage*mgmt_rate)-0.5)
        if n < 1: n = 1
        return round(gr*n - wage*n*n*mgmt_rate, 0), n, round(gr,2)

# ========== 7. 输出 ==========
beijing = timezone(timedelta(hours=8))
out = {
    "update_time": datetime.now(tz=beijing).strftime("%Y-%m-%d %H:%M:%S"),
    "unified_multiplier": round(um, 4),
    "items": [],
    "retail_prices": retail_price_map
}
for item in set(final.keys()) | {n for d in retail_data.values() for n in d["items"]}:
    out["items"].append({
        "name": item,
        "price": final.get(item, 0),
        "base_price": prices.get(item, 0),
        "retail_price": retail_price_map.get(item),
        "is_retail": item in retail_price_map
    })
bp = {}
for p in prod_data:
    l, o, _ = lim(p, prices, False)
    bp[p] = {"limit": l, "opt_level": o}
for d in retail_data.values():
    for rn in d["items"]:
        if rn in retail_price_map:
            l, o, _ = lim(rn, prices, True)
            bp[f"零售_{rn}"] = {"limit": l, "opt_level": o}
out["building_profits"] = bp

with open("data_output.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f"统一倍率 {um:.4f}，指导价已生成")
