
let DATA, items=[], recipes, prodSpeed, wagePerHour, category, retailPrices;

fetch('data_output.json').then(r=>r.json()).then(json=>{
    DATA = json;
    document.getElementById('update-time').innerText = json.update_time;
    items = json.items;
    recipes = json.recipes;
    prodSpeed = json.prod_speed;
    wagePerHour = json.wage_per_hour || {};
    category = json.category;
    retailPrices = json.retail_prices || {};
    renderAll();
});

function getInput(id) { return parseFloat(document.getElementById(id).value)||0; }

// 根据当前利润率计算所有物品的实时价格
function getPrices() {
    const margin = getInput('margin') / 100;  // 销售利润率
    let p = {};
    // 先复制终端品价格
    for (let name in retailPrices) {
        p[name] = retailPrices[name] * (1 - margin);
    }
    // 非终端品需要根据下游价格实时计算（这里简化：使用已有的base价格按比例缩放？）
    // 但base价格是用0利润率算的，当margin变化时，所有上游价格应该重新加权。
    // 为了简单且保证利润平衡，我们直接用利润率修改终端品价格，然后重新做一次加权。
    // 这里我们在前端重新计算所有物品价格以保持准确性。
    // 构建consumers
    let consumers = {};
    for (let prod in recipes) {
        for (let [mat, amt] of recipes[prod]) {
            if (!consumers[mat]) consumers[mat] = [];
            consumers[mat].push([prod, amt]);
        }
    }
    // 计算高度
    let height = {};
    for (let item of items) height[item.name] = (item.name in retailPrices) ? 0 : -1;
    let changed = true;
    while (changed) {
        changed = false;
        for (let prod in recipes) {
            if (height[prod] >= 0) {
                for (let [mat, amt] of recipes[prod]) {
                    if (height[mat] < height[prod] + 1) {
                        height[mat] = height[prod] + 1;
                        changed = true;
                    }
                }
            }
        }
    }
    let sorted = items.map(i=>i.name).sort((a,b)=>height[a]-height[b]);
    for (let name of sorted) {
        if (name in p) continue;
        let totalW = 0, sumWP = 0;
        if (consumers[name]) {
            for (let [down, amt] of consumers[name]) {
                let speed = prodSpeed[down] || 0;
                if (speed > 0 && down in p) {
                    let w = speed * amt;
                    sumWP += w * p[down];
                    totalW += w;
                }
            }
        }
        p[name] = totalW > 0 ? sumWP / totalW : 1.0;
    }
    return p;
}

function calcGrossProfit(itemName, prices) {
    const speed = prodSpeed[itemName] || 0;
    if (!speed) return 0;
    const prodBonus = 1 + getInput('prod-bonus')/100;
    const saleBonus = 1 + getInput('sale-bonus')/100;
    const retailPrice = retailPrices[itemName];
    const price = prices[itemName];
    const revenue = speed * (retailPrice ? retailPrice : price) * (itemName.startsWith("出售") ? saleBonus : 1) * prodBonus;
    let matCost = 0;
    if (recipes[itemName]) {
        for (let [mat, amt] of recipes[itemName]) {
            matCost += speed * amt * (prices[mat] || 0) * prodBonus;
        }
    }
    const wage = wagePerHour[itemName] || 0;
    return revenue - matCost - wage;
}

function calcMaxLevel(itemName, prices) {
    const wage = wagePerHour[itemName] || 0;
    if (!wage) return 0;
    const otherLv = getInput('other-levels');
    const otherWage = getInput('other-wages');
    const reduce = getInput('mgt-reduction')/100;
    let lv = 1;
    while (lv < 5000) {
        const next = lv+1;
        const totalNext = otherLv + next;
        const mgrNext = totalNext * 0.0058 * (1-reduce);
        const costNext = wage * next * mgrNext + otherWage * mgrNext;
        const grossNext = calcGrossProfit(itemName, prices) * next;
        const netNext = grossNext - costNext;
        const totalCur = otherLv + lv;
        const mgrCur = totalCur * 0.0058 * (1-reduce);
        const costCur = wage * lv * mgrCur + otherWage * mgrCur;
        const grossCur = calcGrossProfit(itemName, prices) * lv;
        const netCur = grossCur - costCur;
        if (netNext <= netCur) break;
        lv = next;
    }
    return lv;
}

function calcLimitProfit(itemName, prices) {
    const maxLv = calcMaxLevel(itemName, prices);
    if (!maxLv) return 0;
    const wage = wagePerHour[itemName]||0;
    const otherLv = getInput('other-levels');
    const otherWage = getInput('other-wages');
    const reduce = getInput('mgt-reduction')/100;
    const total = otherLv + maxLv;
    const mgr = total * 0.0058 * (1-reduce);
    const cost = wage * maxLv * mgr + otherWage * mgr;
    return Math.round(calcGrossProfit(itemName, prices) * maxLv - cost);
}

function renderAll() {
    const prices = getPrices();
    const cats = ["电力与基础资源","农场产品","牧场产品","加工中间品","中央厨房产品","时装/工业产品"];
    let html = '';
    for (let c of cats) {
        const list = items.filter(i=>category[i.name]===c);
        if (!list.length) continue;
        html += `<div class="category"><h2>${c}</h2><table>
          <tr><th>商品</th><th>指导价</th><th>每级时利润</th><th>最高等级</th><th>极限利润</th></tr>`;
        for (let it of list) {
            const gp = calcGrossProfit(it.name, prices);
            const maxLv = calcMaxLevel(it.name, prices);
            const limit = calcLimitProfit(it.name, prices);
            html += `<tr>
              <td>${it.name}</td>
              <td>${prices[it.name].toFixed(2)} 元</td>
              <td>${Math.round(gp)} 元/h</td>
              <td>${maxLv} 级</td>
              <td class="limit">${limit} 元/h</td>
            </tr>`;
        }
        html += '</table></div>';
    }
    document.getElementById('tables-container').innerHTML = html;
}
