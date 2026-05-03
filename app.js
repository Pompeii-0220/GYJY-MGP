
// 全局数据
let DATA = null;
let items = [], recipes, prodSpeed, wagePerHour, category, multipliers, prices;

// 加载数据
fetch('data_output.json')
  .then(r => r.json())
  .then(json => {
    DATA = json;
    document.getElementById('update-time').innerText = json.update_time;
    items = json.items;
    recipes = json.recipes;
    prodSpeed = json.prod_speed;
    wagePerHour = json.wage_per_hour || {};
    category = json.category;
    multipliers = {};
    prices = {};
    items.forEach(it => {
      multipliers[it.name] = it.multiplier;
      prices[it.name] = it.price;
    });
    renderAll();
  });

function getInput(id) {
  return parseFloat(document.getElementById(id).value) || 0;
}

// 计算某物品1级时的毛利（管理费=0）
function calcGrossProfit(itemName) {
  const price = prices[itemName] || 0;
  const speed1 = prodSpeed[itemName] || 0;
  if (speed1 === 0) return 0;
  const prodBonus = 1 + getInput('prod-bonus')/100;
  const saleBonus = 1 + getInput('sale-bonus')/100;
  const revenue = speed1 * price * prodBonus * saleBonus;

  // 原料成本
  let materialCost = 0;
  if (recipes[itemName]) {
    for (let [mat, amt] of recipes[itemName]) {
      const matPrice = prices[mat] || 0;
      materialCost += speed1 * amt * matPrice * prodBonus;
    }
  }

  const wage1 = wagePerHour[itemName] || 0;
  return revenue - materialCost - wage1;
}

// 迭代计算最高等级
function calcMaxLevel(itemName) {
  const wage1 = wagePerHour[itemName] || 0;
  if (wage1 === 0) return 0;

  const otherLevels = getInput('other-levels');
  const otherWages = getInput('other-wages');
  const mgtReduction = getInput('mgt-reduction');

  let level = 1;
  while (level < 10000) {
    const nextLevel = level + 1;
    const totalLevels = otherLevels + nextLevel;
    const mgtRate = totalLevels * 0.0058 * (1 - mgtReduction/100);
    const mgtCostNext = wage1 * nextLevel * mgtRate + otherWages * mgtRate;

    const totalLevelsCur = otherLevels + level;
    const mgtRateCur = totalLevelsCur * 0.0058 * (1 - mgtReduction/100);
    const mgtCostCur = wage1 * level * mgtRateCur + otherWages * mgtRateCur;

    const grossNext = calcGrossProfit(itemName) * nextLevel;
    const netNext = grossNext - mgtCostNext;
    const grossCur = calcGrossProfit(itemName) * level;
    const netCur = grossCur - mgtCostCur;

    if (netNext <= netCur) break;
    level = nextLevel;
  }
  return level;
}

// 极限利润
function calcLimitProfit(itemName) {
  const maxLevel = calcMaxLevel(itemName);
  if (maxLevel === 0) return 0;
  const gross = calcGrossProfit(itemName) * maxLevel;
  const otherLevels = getInput('other-levels');
  const otherWages = getInput('other-wages');
  const mgtReduction = getInput('mgt-reduction');
  const totalLevels = otherLevels + maxLevel;
  const mgtRate = totalLevels * 0.0058 * (1 - mgtReduction/100);
  const wage1 = wagePerHour[itemName] || 0;
  const mgtCost = wage1 * maxLevel * mgtRate + otherWages * mgtRate;
  return Math.round(gross - mgtCost);
}

// 渲染表格
function renderAll() {
  const container = document.getElementById('tables-container');
  const cats = ["电力与基础资源","农场产品","牧场产品","加工中间品","中央厨房产品","时装/工业产品"];
  let html = '';
  for (const c of cats) {
    const itemsInCat = items.filter(it => category[it.name] === c);
    if (!itemsInCat.length) continue;
    html += `<div class="category"><h2>${c}</h2><table>
      <tr><th>商品</th><th>指导价</th><th>每级时利润</th><th>最高等级</th><th>极限利润</th></tr>`;
    for (const it of itemsInCat) {
      const profit = Math.round(calcGrossProfit(it.name));
      const maxLv = calcMaxLevel(it.name);
      const limitProfit = calcLimitProfit(it.name);
      html += `<tr>
        <td>${it.name}</td>
        <td class="price">${it.price} 元（倍率 ${it.multiplier.toFixed(2)}）</td>
        <td class="profit">${profit} 元/h</td>
        <td>${maxLv} 级</td>
        <td class="limit">${limitProfit} 元/h</td>
      </tr>`;
    }
    html += '</table></div>';
  }
  container.innerHTML = html;
}
