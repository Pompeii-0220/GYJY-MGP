import json
import requests
from datetime import datetime, timezone, timedelta
import numpy as np
from scipy.optimize import minimize

print("脚本启动...")

# ========== 1. 加载数据 ==========
with open("game_data.json", "r", encoding="utf-8") as f:
    gd = json.load(f)

prod_data = gd["production"]
retail_data = gd["retail"]
mgmt_rate = gd["management_rate"]

api_url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(api_url, timeout=15)
resp.raise_for_status()
api_json = resp.json()
retail_rows = api_json.get("rows", [])
retail_price_map = {item["name"]: item["retailPrice"] for item in retail_rows}
retail_base_price_map = {item["name"]: item["basePrice"] for item in retail_rows}

print(f"API 零售品数量: {len(retail_rows)}")

# ========== 2. 准备变量 ==========
# 所有非零售品的名字（作为优化变量）
var_names = [p for p in prod_data if p not in retail_base_price_map]
# 电力单独处理（作为锚点，不参与优化）
if "电力" in var_names:
    var_names.remove("电力")

# 初始价格：成本加成15%
def init_prices():
    p = {}
    elec = prod_data["电力"]
    labor = elec["wage"] / elec["output"]
    p["电力"] = labor * 1.15
    remaining = set(prod_data.keys()) - {"电力"}
    while remaining:
        solved = set()
        for prod in remaining:
            info = prod_data[prod]
            mat_cost = 0.0
            unknown = False
            for ing, amt in info["recipe"].items():
                per = amt / info.get("batch", 1)
                if ing not in p:
                    unknown = True
                    break
                mat_cost += per * p[ing]
            if unknown:
                continue
            labor = info["wage"] / info["output"]
            price = (mat_cost + labor) * 1.15
            if prod in retail_base_price_map:
                price = retail_base_price_map[prod] * 0.98
            p[prod] = price
            solved.add(prod)
        if not solved:
            for prod in remaining:
                if prod not in p:
                    p[prod] = prod_data[prod]["wage"] / prod_data[prod]["output"] * 2.0
            break
        remaining -= solved
    return p

# ========== 3. 目标函数 ==========
def objective(x):
    prices = init_prices()
    for name, val in zip(var_names, x):
        prices[name] = val
    # 计算所有建筑的极限利润
    limits = []
    for pname in prod_data:
        info = prod_data[pname]
        wage = info["wage"]
        output = info["output"]
        price = prices.get(pname, 1.0)
        mat = 0.0
        for ing, amt in info["recipe"].items():
            per = amt / info.get("batch", 1)
            mat += per * prices.get(ing, 1.0)
        gross = output * (price - mat) - wage
        if gross <= 0:
            continue
        n_opt = int(gross / (2 * wage * mgmt_rate) - 0.5)
        if n_opt < 1:
            n_opt = 1
        limit = gross * n_opt - wage * (n_opt ** 2) * mgmt_rate
        limits.append(limit)
    if len(limits) < 5:
        return 1e12
    mean = np.mean(limits)
    std = np.std(limits)
    cv = std / mean  # 变异系数
    return cv

# ========== 4. 约束：每个中间品价格不低于原料成本 ==========
def build_constraints():
    cons = []
    for i, name in enumerate(var_names):
        def constraint(x, i=i, name=name):
            prices = init_prices()
            for j, n in enumerate(var_names):
                prices[n] = x[j]
            # 计算原料成本
            info = prod_data[name]
            mat = 0.0
            for ing, amt in info["recipe"].items():
                per = amt / info.get("batch", 1)
                mat += per * prices.get(ing, 1.0)
            return x[i] - mat  # 价格 >= 原料成本
        cons.append({'type': 'ineq', 'fun': constraint})
    return cons

# ========== 5. 运行优化 ==========
x0 = [init_prices()[n] for n in var_names]
bounds = [(1e-3, 1e9) for _ in var_names]
constraints = build_constraints()

print("开始 scipy 优化...（可能需要1-2分钟）")
res = minimize(objective, x0, method='SLSQP', bounds=bounds, constraints=constraints,
               options={'maxiter': 500, 'ftol': 1e-6})

# ========== 6. 生成最终价格 ==========
final_base_prices = init_prices()
for name, val in zip(var_names, res.x):
    final_base_prices[name] = max(val, 1e-3)

# ========== 7. 统一市场倍率 ==========
total_w = sum_m = 0.0
for item in retail_rows:
    name = item["name"]
    if name not in final_base_prices:
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
final_prices = {n: round(bp * unified_mult, 2) for n, bp in final_base_prices.items()}

# ========== 8. 极限利润输出 ==========
def calc_limit(pname, prices):
    if pname in prod_data:
        info = prod_data[pname]
        wage = info["wage"]
        output = info["output"]
        price = prices.get(pname, 0)
        mat = 0.0
        for ing, amt in info["recipe"].items():
            per = amt / info.get("batch", 1)
            mat += per * prices.get(ing, 0)
        gross = output * (price - mat) - wage
        if gross <= 0:
            return 0, 0
        n_opt = int(gross / (2 * wage * mgmt_rate) - 0.5)
        if n_opt < 1: n_opt = 1
        limit = gross * n_opt - wage * (n_opt ** 2) * mgmt_rate
        return round(limit, 0), n_opt
    return 0, 0

# ========== 9. 输出文件 ==========
beijing = timezone(timedelta(hours=8))
update_time = datetime.now(tz=beijing).strftime("%Y-%m-%d %H:%M:%S")
output = {
    "update_time": update_time,
    "unified_multiplier": round(unified_mult, 4),
    "optimization_success": res.success,
    "final_cv": objective(res.x),
    "items": [],
    "retail_prices": retail_price_map
}
all_items = set(final_prices.keys()) | {n for r in retail_data.values() for n in r["items"]}
for item in all_items:
    output["items"].append({
        "name": item,
        "price": final_prices.get(item, 0),
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

print(f"优化完成：成功={res.success}, 最终CV={objective(res.x):.4f}, 统一倍率={unified_mult:.4f}")
