import json
import requests
import os

# 1. 读取本地数据
with open("data.json", "r", encoding="utf-8") as f:
    data = json.load(f)

guide_prices = data["guide_prices"]
recipes = data["recipes"]
prod_speed = data["production_speed"]
category = data["category"]

# 2. 从 API 获取零售品倍率
url = "http://gyjy.xmonecode.com/api/public/retail-prices"
resp = requests.get(url)
resp.raise_for_status()
retail_items = resp.json()

# 暂时用简单映射：API的 name 去掉可能存在的"出售"前缀后与表格零售品匹配
# 但你的表格零售品就叫"出售牛奶"，API里是"牛奶"，所以映射关系：
retail_multipliers = {}  # key = 表格中的零售品名称，value = multiplier
for item in retail_items:
    api_name = item["name"]
    # 直接映射：表格中零售品名称就是 "出售" + API名称
    table_retail_name = "出售" + api_name
    if table_retail_name in guide_prices:
        retail_multipliers[table_retail_name] = item["multiplier"]
    else:
        # 处理特殊情况：API有"咖啡粉" -> 表格"出售咖啡粉"，其实规则一样
        # 如果上面的直接映射不成功，尝试下面的硬编码补充
        pass

# 手动补充几个API返回但可能名字不完全对应的（比如橙汁->出售橙汁，已经覆盖）
# 如果还有漏掉的，可以在此添加

# 3. 构建消耗关系：谁消耗了谁（下游 -> 上游），用于从零售品向上游推算
# 即：对于每一对 (产品X，原料Y)，X消耗Y，X是下游，Y是上游
consumers = {}  # key = 原料Y，value = list of (下游X, 每产1个X消耗Y的数量)
for product, ingredients in recipes.items():
    for ing, amount in ingredients:
        if ing not in consumers:
            consumers[ing] = []
        consumers[ing].append((product, amount))

# 4. 计算所有物品的倍率（迭代从零售品开始，向上游传播）
# 使用拓扑排序或迭代直到稳定
multipliers = {}  # 所有物品的倍率
# 初始已知：零售品倍率
multipliers.update(retail_multipliers)

# 需要计算倍率的物料集合（所有在guide_prices中出现且不是纯零售的）
all_items = list(guide_prices.keys())
# 有些物品可能既不是零售也不被任何消耗（比如基础资源电力、水、原油等），它们的倍率无法从下游推导
# 我们将其倍率设为1.0（即不乘倍率）或你可以设定特殊规则
# 但根据你的逻辑，它们应该由它们的下游（比如电力的下游是塑料、糖等）加权得到
# 所以我们尝试迭代计算所有物品

# 迭代直到稳定
changed = True
while changed:
    changed = False
    for item in all_items:
        if item in multipliers:
            continue  # 已有倍率
        if item not in consumers:
            # 没有下游消耗它（比如基础资源如果没被任何配方消耗，则倍率设1）
            # 但根据recipes，电力被水、种子、糖等多个消耗，所以不会进入这里
            multipliers[item] = 1.0
            changed = True
            continue

        # 根据所有直接下游的倍率加权计算
        downstream = consumers[item]
        total_weight = 0.0
        weighted_mult = 0.0
        for down_prod, amount_per_prod in downstream:
            # 该下游的生产速度（每小时产量）
            speed = prod_speed.get(down_prod, 0)
            # 该下游消耗该原料的总速率 = 生产速度 * 每产1个消耗量
            consume_rate = speed * amount_per_prod
            if down_prod in multipliers:
                weighted_mult += consume_rate * multipliers[down_prod]
                total_weight += consume_rate
            # 如果下游倍率还未知，则跳过本次计算（等待下一轮迭代）
        if total_weight > 0:
            new_mult = weighted_mult / total_weight
            multipliers[item] = round(new_mult, 4)
            changed = True

# 5. 结合原始指导价计算新价格
prices = {}
for item, base_price in guide_prices.items():
    mult = multipliers.get(item, 1.0)
    prices[item] = round(base_price * mult, 2)

# 6. 生成 HTML
# 按分类组织
cat_order = [
    "电力与基础资源",
    "农场产品",
    "牧场产品",
    "加工中间品",
    "中央厨房产品",
    "时装/工业产品",
    "零售品"
]
items_by_cat = {c: [] for c in cat_order}
for item, cat in category.items():
    if cat in items_by_cat:
        items_by_cat[cat].append(item)

html = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>市场指导价</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f5f5f5; color: #1a1a1a; margin: 0; padding: 20px; }
  .container { max-width: 900px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }
  h1 { text-align: center; color: #2c3e50; margin-bottom: 10px; }
  .update-time { text-align: center; color: #888; font-size: 14px; margin-bottom: 30px; }
  .category { margin-bottom: 32px; }
  .category h2 { background: #2c3e50; color: white; padding: 10px 15px; font-size: 18px; border-radius: 6px; margin: 0 0 12px; }
  table { width: 100%; border-collapse: collapse; font-size: 15px; }
  th, td { padding: 10px 8px; text-align: left; border-bottom: 1px solid #e0e0e0; }
  th { background: #fafafa; font-weight: 600; color: #555; }
  .price { font-weight: 600; color: #e67e22; }
  .mult { color: #27ae60; font-size: 13px; margin-left: 6px; }
  .mult::before { content: "×"; }
</style>
</head>
<body>
<div class="container">
  <h1>🏭 零加成市场指导价</h1>
  <div class="update-time">更新时间：<span id="update"></span></div>
"""

# 插入更新时间脚本
html += """
<script>
  var now = new Date();
  document.getElementById('update').innerText = now.toLocaleString('zh-CN');
</script>
"""

for cat in cat_order:
    items = items_by_cat[cat]
    if not items:
        continue
    html += f'<div class="category"><h2>{cat}</h2><table><tr><th>商品</th><th>指导价</th></tr>'
    for item in items:
        price = prices.get(item, guide_prices.get(item, "?"))
        mult = multipliers.get(item, 1.0)
        mult_str = f'<span class="mult">{mult:.2f}</span>' if abs(mult - 1.0) > 0.001 else ""
        html += f'<tr><td>{item}</td><td class="price">{price} 元{mult_str}</td></tr>'
    html += '</table></div>'

html += """
</div>
</body>
</html>
"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print("更新完成，已生成 index.html")
