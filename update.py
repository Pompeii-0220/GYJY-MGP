import json
import requests
from datetime import datetime, timezone, timedelta
import copy

# ========== 1. 加载静态数据库 ==========
with open("game_data.json", "r", encoding="utf-8") as f:
    gd = json.load(f)

prod_data = gd["production"]
retail_data = gd["retail"]
mgmt_rate = gd["management_rate"]

# ========== 2. 抓取 API 实时数据 ==========
api_url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(api_url)
resp.raise_for_status()
api_json = resp.json()
retail_rows = api_json.get("rows", [])
retail_price_map = {item["name"]: item["retailPrice"] for item in retail_rows}
retail_base_price_map = {item["name"]: item["basePrice"] for item in retail_rows}

# ========== 3. 核心计算函数 ==========
def compute_prices(profit_rate, complexity_bonus=0.0):
    """
    根据给定参数，成本加成计算所有非零售品的均衡价。
    profit_rate: 基础利润率
    complexity_bonus: 每个额外原料的利润率加成
    """
    prices = {}
    # 电力基准价：劳动力成本 * (1 + 利润率)
    elec_info = prod_data.get("电力")
    if elec_info:
        labor = elec_info["wage"] / elec_info["output"]
        prices["电力"] = round(labor * (1 + profit_rate), 2)

    # 按依赖顺序逐层求解
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
                # 计算该产品的专用利润率（基础 + 复杂度加成）
                num_ingredients = len(recipe)
                effective_rate = profit_rate + complexity_bonus * max(0, num_ingredients - 1)
                price = round((mat_cost + labor) * (1 + effective_rate), 2)
                # 零售品价格上限设定为 API 基础价的 95%
                if p in retail_base_price_map:
                    ceiling = retail_base_price_map[p] * 0.95
                    price = min(price, ceiling)
                prices[p] = price
                solved.add(p)
        if not solved:
            # 出现死锁（通常为循环依赖），使用劳动力成本*2作为保底
            for p in remaining:
                if p not in prices:
                    labor = prod_data[p]["wage"] / prod_data[p]["output"]
                    prices[p] = round(labor * 2.0, 2)
            break
        remaining -= solved
    return prices

def calc_limit_profit(item_name, prices):
    """计算单个建筑在给定价格下的极限利润（元/h）"""
    # 生产建筑
    if item_name in prod_data:
        info = prod_data[item_name]
        wage = info["wage"]
        output = info["output"]
        price = prices.get(item_name, 0)
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
        if n_opt < 1:
            n_opt = 1
        limit = gross * n_opt - wage * (n_opt ** 2) * mgmt_rate
        return round(limit, 0), n_opt, round(gross, 2)

    # 零售建筑（用于后续展示，不参与优化目标）
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

# ========== 4. 优化器 ==========
def evaluate_params(profit_rate, complexity_bonus):
    """计算给定参数下的极限利润变异系数"""
    prices = compute_prices(profit_rate, complexity_bonus)
    limits = []
    for pname in prod_data:
        limit, _, _ = calc_limit_profit(pname, prices)
        if limit > 0:
            limits.append(limit)
    if len(limits) < 3:
        return float('inf')
    mean = sum(limits) / len(limits)
    if mean == 0:
        return float('inf')
    variance = sum((x - mean) ** 2 for x in limits) / len(limits)
    cv = (variance ** 0.5) / mean  # 变异系数
    return cv

def find_optimal_params():
    """网格搜索 + 局部爬山寻找最优利润率和复杂度加成"""
    best_cv = float('inf')
    best_profit = 0.15
    best_bonus = 0.0

    # 网格搜索范围：基础利润率10%~30%，复杂度加成0~15%
    for pr in [0.10, 0.12, 0.15, 0.18, 0.20, 0.22, 0.25, 0.28, 0.30]:
        for cb in [0.0, 0.02, 0.05, 0.08, 0.10, 0.12, 0.15]:
            cv = evaluate_params(pr, cb)
            if cv < best_cv:
                best_cv = cv
                best_profit = pr
                best_bonus = cb

    # 局部爬山微调
    step = 0.01
    for _ in range(10):
        improved = False
        for d_pr in [-step, 0, step]:
            for d_cb in [-step, 0, step]:
                if d_pr == 0 and d_cb == 0:
                    continue
                new_pr = max(0.05, min(0.40, best_profit + d_pr))
                new_cb = max(0.0, min(0.20, best_bonus + d_cb))
                cv = evaluate_params(new_pr, new_cb)
                if cv < best_cv:
                    best_cv = cv
                    best_profit = new_pr
                    best_bonus = new_cb
                    improved = True
        if not improved:
            break

    return best_profit, best_bonus, best_cv

# 尝试加载上一次保存的最优参数，若无则重新寻优
try:
    with open("optimal_params.json", "r") as f:
        opt = json.load(f)
        best_profit = opt["profit_rate"]
        best_bonus = opt["complexity_bonus"]
        print(f"使用已保存的最优参数：利润率{best_profit*100:.1f}%，复杂度加成{best_bonus*100:.1f}%")
except:
    print("正在优化均衡参数...（可能需要十几秒）")
    best_profit, best_bonus, best_cv = find_optimal_params()
    with open("optimal_params.json", "w") as f:
        json.dump({"profit_rate": best_profit, "complexity_bonus": best_bonus}, f)
    print(f"优化完成：利润率{best_profit*100:.1f}%，复杂度加成{best_bonus*100:.1f}%，变异系数{best_cv:.4f}")

# ========== 5. 生成均衡指导价 ==========
base_prices = compute_prices(best_profit, best_bonus)

# ========== 6. 统一市场倍率 ==========
total_w = 0.0
sum_m = 0.0
for item in retail_rows:
    name = item["name"]
    if name not in base_prices:
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
final_prices = {name: round(bp * unified_mult, 2) for name, bp in base_prices.items()}

# ========== 7. 输出结果 ==========
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

print(f"✅ 统一倍率 {unified_mult:.4f}，指导价已更新（优化利润模型）")
