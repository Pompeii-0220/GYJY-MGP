
let DATA, items=[], recipes, prodSpeed, wagePerHour, category, prices;

fetch('data_output.json').then(r=>r.json()).then(json=>{
    DATA = json;
    document.getElementById('update-time').innerText = json.update_time;
    items = json.items;
    recipes = json.recipes;
    prodSpeed = json.prod_speed;
    wagePerHour = json.wage_per_hour || {};
    category = json.category;
    prices = {};
    items.forEach(it => prices[it.name] = it.price);
    renderAll();
});

function getInput(id) { return parseFloat(document.getElementById(id).value)||0; }

function calcGrossProfit(itemName) {
    const speed = prodSpeed[itemName] || 0;
    if (!speed) return 0;
    const prodBonus = 1 + getInput('prod-bonus')/100;
    const saleBonus = 1 + getInput('sale-bonus')/100;
    const price = prices[itemName] || 0;
    const revenue = speed * price * (itemName.startsWith("出售") ? saleBonus : 1) * prodBonus;
    let matCost = 0;
    if (recipes[itemName]) {
        for (let [mat, amt] of recipes[itemName]) {
            matCost += speed * amt * (prices[mat]||0) * prodBonus;
        }
    }
    const wage = wagePerHour[itemName] || 0;
    return revenue - matCost - wage;
}

function calcMaxLevel(itemName) {
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
        const grossNext = calcGrossProfit(itemName) * next;
        const netNext = grossNext - costNext;

        const totalCur = otherLv + lv;
        const mgrCur = totalCur * 0.0058 * (1-reduce);
        const costCur = wage * lv * mgrCur + otherWage * mgrCur;
        const grossCur = calcGrossProfit(itemName) * lv;
        const netCur = grossCur - costCur;

        if (netNext <= netCur) break;
        lv = next;
    }
    return lv;
}

function calcLimitProfit(itemName) {
    const maxLv = calcMaxLevel(itemName);
    if (!maxLv) return 0;
    const wage = wagePerHour[itemName]||0;
    const otherLv = getInput('other-levels');
    const otherWage = getInput('other-wages');
    const reduce = getInput('mgt-reduction')/100;
    const total = otherLv + maxLv;
    const mgr = total * 0.0058 * (1-reduce);
    const cost = wage * maxLv * mgr + otherWage * mgr;
    return Math.round(calcGrossProfit(itemName) * maxLv - cost);
}

function renderAll() {
    const cats = ["电力与基础资源","农场产品","牧场产品","加工中间品","中央厨房产品","时装/工业产品"];
    let html = '';
    for (let c of cats) {
        const list = items.filter(i=>category[i.name]===c);
        if (!list.length) continue;
        html += `<div class="category"><h2>${c}</h2><table>
          <tr><th>商品</th><th>指导价</th><th>每级时利润</th><th>最高等级</th><th>极限利润</th></tr>`;
        for (let it of list) {
            const gp = calcGrossProfit(it.name);
            const maxLv = calcMaxLevel(it.name);
            const limit = calcLimitProfit(it.name);
            html += `<tr>
              <td>${it.name}</td>
              <td>${it.price.toFixed(2)} 元</td>
              <td>${Math.round(gp)} 元/h</td>
              <td>${maxLv} 级</td>
              <td class="limit">${limit} 元/h</td>
            </tr>`;
        }
        html += '</table></div>';
    }
    document.getElementById('tables-container').innerHTML = html;
}
