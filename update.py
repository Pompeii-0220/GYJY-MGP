import json
import requests
from datetime import datetime, timezone, timedelta

# ========== 完整静态均衡指导价（1.0倍率基石） ==========
BASE_GUIDE_PRICES = {
    # 原有均衡价（保持）
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
    
    # 新增产品均衡价（基于利润均衡反推，且确保低于零售价）
    "沙子": 2.50, "黏土": 2.20, "石灰石": 3.20,
    "矿物": 20.00, "铝土矿": 25.00, "铁矿石": 18.00, "金矿石": 80.00,
    "甲烷": 60.00, "乙醇": 80.00,
    "汽油": 200.00, "柴油": 200.00, "火箭燃料": 120.00,
    "碳纤维": 60.00, "碳纤维复合材": 150.00,
    "硅材": 15.00, "化合物": 50.00, "铝材": 70.00, "钢材": 200.00, "玻璃": 60.00, "金条": 5000.00,
    "钢筋混凝土": 300.00, "砖块": 15.00, "水泥": 50.00,
    "钢筋": 400.00, "木板": 45.00, "窗户": 500.00, "工具": 1000.00,
    "建筑预构件": 5000.00,
    "处理器": 1000.00, "电子元件": 400.00, "电池": 500.00, "显示屏": 800.00,
    "智能手机": 3500.00, "平板电脑": 5000.00, "笔记本电脑": 6000.00,
    "显示器": 3000.00, "电视机": 5000.00, "精密电子元件": 8000.00,
    "机器人": 15000.00, "车载电脑": 3000.00,
    "电动马达": 2000.00, "内燃机": 5000.00,
    "固体燃料助推器": 15000.00, "火箭发动机": 25000.00,
    "离子推进器": 20000.00, "喷气发动机": 35000.00,
    "豪华车内饰": 12000.00, "基本内饰": 5000.00, "车身": 8000.00,
    "经济电动车": 15000.00, "豪华电动车": 25000.00,
    "经济燃油车": 12000.00, "豪华燃油车": 20000.00,
    "卡车": 18000.00, "推土机": 25000.00,
    "无人机": 8000.00, "飞行计算机": 15000.00, "座舱": 20000.00,
    "姿态控制器": 10000.00, "人造卫星": 30000.00,
    "机身": 20000.00, "机翼": 12000.00, "燃料储罐": 18000.00,
    "隔热板": 8000.00, "亚轨道二级": 50000.00,
    "轨道助推器": 100000.00, "星际飞船": 80000.00,
    "喷气客机": 80000.00, "豪华飞机": 100000.00,
    "单引擎飞机": 50000.00, "亚轨道火箭": 120000.00,
    "星舰": 200000.00,
    "名牌手表": 8000.00, "项链": 12000.00,
}

# ========== 加载生产与零售数据 ==========
with open("game_data.json", "r", encoding="utf-8") as f:
    gd = json.load(f)

prod_data = gd["production"]
retail_data = gd["retail"]
mgmt_rate = gd["management_rate"]

# ========== 抓取API ==========
api_url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(api_url)
resp.raise_for_status()
api_json = resp.json()
retail_rows = api_json.get("rows", [])
retail_price_map = {item["name"]: item["retailPrice"] for item in retail_rows}

# ========== 统一市场倍率 ==========
total_weight = 0.0
sum_mult = 0.0
for item in retail_rows:
    name = item.get("name")
    if name not in BASE_GUIDE_PRICES:
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

# ========== 最终指导价 ==========
final_prices = {}
for name, bp in BASE_GUIDE_PRICES.items():
    final_prices[name] = round(bp * unified_mult, 2)

# ========== 极限利润计算 ==========
def calc_limit_profit(item_name, prices):
    # 生产建筑
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
        if n_opt < 1:
            n_opt = 1
        limit = gross * n_opt - wage * (n_opt ** 2) * mgmt_rate
        return round(limit, 0), n_opt, round(gross, 2)

    # 零售建筑
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
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"✅ 统一倍率: {unified_mult:.4f}，指导价已生成（使用静态均衡基石）")
