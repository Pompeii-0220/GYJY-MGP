#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
静态均衡指导价计算引擎
核心规则：任何建筑每小时利润 = 其建造成本 × 统一资本回报率 r
通过迭代求解所有产品的均衡内部结算价（包括建材自身价格自洽）
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
    """
    输入: buildings 列表，每个元素为 dict，格式:
        {
            "name": "农场",
            "wage": 7280,
            "construction": {"钢筋混凝土": 48, ...},  # 可选，缺失或为空则建造成本为0
            "products": [
                {
                    "name": "苹果",
                    "output": 2022,
                    "inputs": {"水": 3, "种子": 1}
                },
                ...
            ]
        }
    输出: (均衡价格字典, 各建筑极限利润字典)
    """
    # 1. 收集所有产品名，初始化价格
    all_products = set()
    for b in buildings:
        for p in b["products"]:
            all_products.add(p["name"])
    prices = {p: INITIAL_PRICE for p in all_products}

    # 2. 预处理每个建筑的产品数据（避免循环中重复解析）
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

    # 3. 迭代求解
    for iteration in range(MAX_ITER):
        new_prices = prices.copy()

        # 3.1 根据当前价格计算每个建筑的建造成本 C
        for bld in building_info:
            C = 0.0
            for mat, qty in bld["const"].items():
                if mat in prices:
                    C += qty * prices[mat]
                else:
                    # 如果建材名未出现在产品列表中（不应该），忽略
                    pass
            bld["C"] = C

        # 3.2 遍历每个建筑，计算其产品的“新价格”
        for bld in building_info:
            wage = bld["wage"]
            C = bld.get("C", 0.0)
            fixed_cost = wage + C * r   # 该建筑每小时应得的总收入（工资+资本回报）

            # 计算该建筑的总产值和总原料成本（用上轮价格），为分摊做准备
            total_revenue = 0.0
            total_material_cost = 0.0
            prod_data = []

            for p in bld["products"]:
                output = p["output"]
                # 单位原料成本
                unit_mat = 0.0
                for mat, qty in p["inputs"].items():
                    unit_mat += qty * prices[mat]
                mat_total = output * unit_mat
                revenue = output * prices[p["name"]]   # 用旧价格算产值
                total_revenue += revenue
                total_material_cost += mat_total
                prod_data.append({
                    "name": p["name"],
                    "output": output,
                    "unit_mat": unit_mat,
                    "revenue": revenue
                })

            # 分摊固定成本到各个产品（按产值比例）
            if total_revenue > 0:
                for pd in prod_data:
                    share = pd["revenue"] / total_revenue
                    unit_fixed = share * fixed_cost / pd["output"]
                    new_price = pd["unit_mat"] + unit_fixed
                    new_prices[pd["name"]] = new_price
            else:
                # 如果总产值为0（极特殊情况，所有产品价格均为0），跳过
                pass

        # 3.3 检查收敛：新旧价格的总平方差
        diff = 0.0
        for p in all_products:
            diff += (new_prices[p] - prices[p]) ** 2
        diff = diff ** 0.5
        prices = new_prices

        if diff < TOLERANCE:
            print(f"迭代收敛于第 {iteration+1} 轮，价格差异 {diff:.12f}")
            break
    else:
        print(f"达到最大迭代次数 {MAX_ITER}，最终差异 {diff:.12f}")

    # 4. 汇总各建筑极限利润
    profit_summary = {}
    for bld in building_info:
        C = bld.get("C", 0.0)
        profit_per_hour = C * r
        profit_summary[bld["name"]] = {
            "建造成本": round(C, 2),
            "极限时利润": round(profit_per_hour, 2)
        }

    # 价格保留两位小数便于展示
    final_prices = {k: round(v, 2) for k, v in prices.items()}

    return final_prices, profit_summary


# ==================== 主程序 ====================
def main():
    # 读取建筑数据
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(script_dir, "game_data.json")
    with open(data_path, "r", encoding="utf-8") as f:
        buildings = json.load(f)

    # 计算均衡价格
    prices, profits = calculate_equilibrium(buildings, r=CAPITAL_RETURN_RATE)

    # 组装输出结果
    output = {
        "meta": {
            "description": "基于等资本回报率的静态均衡指导价",
            "capital_return_rate_per_hour": CAPITAL_RETURN_RATE,
            "note": "所有建筑每小时利润 = 建造成本 × 资本回报率"
        },
        "product_prices": prices,
        "building_profits": profits
    }

    # 写出 JSON
    output_path = os.path.join(script_dir, "data_output.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("计算完成，结果已写入 data_output.json")
    # 打印几个关键产品价格供快速查看
    print("\n部分均衡价格：")
    for key in ["电力", "水", "钢筋混凝土", "苹果", "经济电动车"]:
        if key in prices:
            print(f"  {key}: {prices[key]}")


if __name__ == "__main__":
    main()
