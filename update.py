#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
静态均衡指导价计算引擎
规则：任何建筑每小时利润 = 其建造成本 × 统一资本回报率 r
通过迭代求解所有产品的均衡内部结算价（建材价格自洽）
"""

import json
import os

# ==================== 可调参数 ====================
CAPITAL_RETURN_RATE = 0.0001  # 统一小时资本回报率 (0.01%/h)
MAX_ITER = 500                # 最大迭代次数
TOLERANCE = 1e-8              # 价格收敛阈值
INITIAL_PRICE = 1.0           # 迭代前所有产品的初始猜测价

# ==================== 核心算法 ====================
def calculate_equilibrium(buildings, r=CAPITAL_RETURN_RATE):
    # 1. 收集所有产品名，初始化价格
    all_products = set()
    for b in buildings:
        for p in b["products"]:
            all_products.add(p["name"])
    prices = {p: INITIAL_PRICE for p in all_products}

    # 2. 预处理每个建筑的数据
    building_info = []
    for b in buildings:
        wage = b["wage"]
        const = b.get("construction", {})
        products = []
        for p in b["products"]:
            inputs = p.get("inputs", {})
            products.append({
                "name": p["name"],
                "output": p["output"],
                "inputs": inputs
            })
        building_info.append({
            "name": b["name"],
            "wage": wage,
            "const": const,
            "products": products
        })

    # 3. 迭代
    for iteration in range(MAX_ITER):
        new_prices = prices.copy()

        # 3.1 计算每个建筑的建造成本 C
        for bld in building_info:
            C = 0.0
            for mat, qty in bld["const"].items():
                if mat in prices:
                    C += qty * prices[mat]
            bld["C"] = C

        # 3.2 计算每个建筑的产品新价格
        for bld in building_info:
            wage = bld["wage"]
            C = bld.get("C", 0.0)
            fixed_cost = wage + C * r   # 每小时总固定成本

            total_revenue = 0.0
            total_material_cost = 0.0
            prod_data = []

            for p in bld["products"]:
                output = p["output"]
                unit_mat = 0.0
                for mat, qty in p["inputs"].items():
                    unit_mat += qty * prices[mat]
                mat_total = output * unit_mat
                revenue = output * prices[p["name"]]
                total_revenue += revenue
                total_material_cost += mat_total
                prod_data.append({
                    "name": p["name"],
                    "output": output,
                    "unit_mat": unit_mat,
                    "revenue": revenue
                })

            if total_revenue > 0:
                for pd in prod_data:
                    share = pd["revenue"] / total_revenue
                    unit_fixed = share * fixed_cost / pd["output"]
                    new_price = pd["unit_mat"] + unit_fixed
                    new_prices[pd["name"]] = new_price

        # 3.3 检查收敛
        diff = sum((new_prices[p] - prices[p])**2 for p in all_products) ** 0.5
        prices = new_prices
        if diff < TOLERANCE:
            print(f"迭代收敛于第 {iteration+1} 轮，价格差异 {diff:.12f}")
            break
    else:
        print(f"达到最大迭代次数 {MAX_ITER}，最终差异 {diff:.12f}")

    # 4. 汇总利润
    profit_summary = {}
    for bld in building_info:
        C = bld.get("C", 0.0)
        profit_summary[bld["name"]] = {
            "建造成本": round(C, 2),
            "极限时利润": round(C * r, 2)
        }

    final_prices = {k: round(v, 6) for k, v in prices.items()}
    return final_prices, profit_summary


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(script_dir, "game_data.json")
    with open(data_path, "r", encoding="utf-8") as f:
        buildings = json.load(f)

    prices, profits = calculate_equilibrium(buildings, r=CAPITAL_RETURN_RATE)

    output = {
        "meta": {
            "description": "基于等资本回报率的静态均衡指导价",
            "capital_return_rate_per_hour": CAPITAL_RETURN_RATE
        },
        "product_prices": prices,
        "building_profits": profits
    }

    output_path = os.path.join(script_dir, "data_output.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("计算完成，结果已写入 data_output.json")
    print("\n部分均衡价格：")
    for key in ["电力", "水", "钢筋混凝土", "苹果", "经济电动车"]:
        if key in prices:
            print(f"  {key}: {prices[key]}")


if __name__ == "__main__":
    main()
