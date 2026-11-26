# Product Requirements Document (PRD)

**Status:** Product Baseline — Locked  
**Version:** 1.0  
**Working title:** Bakso Business Assistant  
**Related documents:** `GOALS.md`, `DESIGN.md`, `AGENTS.md`, `WORKFLOW.md`, `docs/tickets/TICKET-*.md`

> `PRD.md` defines the product context, business problem, business flow, and business calculation references. It is non-technical. Technical implementation must adapt to this document, not the reverse.

## 1. Product Origin

This product originates from a small family-run mobile food business selling bakso and related foods. The menu may include bakso, fried tofu, white tofu filled with siomay, siomay, dry fried siomay-style items, broth, marrow/fat, scallions, fried shallots, rice vermicelli, lontong, lettuce, chili sauce, tomato sauce, soy sauce, and other complements.

One known finished product is a bowl sold to customers for **Rp5.000**. The Rp5.000 value is the **selling price of the finished product**, not the raw-material cost per bowl and not the assumed cost of each individual item.

The business currently follows a natural cycle:

`Purchase → Inventory → Production → Sale → Cash Received`

However, the owner does not yet have a reliable way to determine whether the food being sold actually produces profit, how much profit is generated, what consumes that profit, and what should be prepared for the next selling period.

## 2. Core Problem

The core problem is not merely recording money received. The business lacks a consistent system to answer:

> **“Did the business actually make a profit, how much, why, and what should be done next?”**

Important distinctions:

- **Revenue is not profit.**
- **Purchasing ingredients is not automatically the HPP/COGS of that day.**
- **Cash remaining is not automatically profit.**
- **Unsold usable inventory still has economic value.**
- **Waste has economic cost.**

## 3. Derived Problems

### 3.1 Unknown product cost

A finished product is composed of multiple ingredients. Example:

`Bakso Bowl = 3 Bakso + 2 Tofu + Broth + Vermicelli + Lontong + Condiments + ...`

The true cost of a finished product cannot be known without knowing the cost of the ingredients actually consumed.

### 3.2 Ingredient prices change between purchases

The same ingredient can enter inventory in different batches at different prices. Example:

- B1 = 120 units @ Rp300
- B2 = 100 units @ Rp350
- B3 = 80 units @ Rp400

The product therefore needs a consistent inventory-costing reference.

### 3.3 Purchase time differs from usage time

Ingredients bought today may still be usable tomorrow. A purchase first becomes inventory; only consumed inventory becomes a production/sales cost.

### 3.4 Perishable inventory

Food may be used, remain in stock, become damaged, spoil, expire, or be discarded. Inventory rotation matters as much as inventory valuation.

### 3.5 Break-even position is unknown

The business needs to know the minimum sales level required to cover relevant costs for a chosen period, especially the daily selling cycle.

### 3.6 Profit and cash flow are mixed together

Buying inventory reduces cash, even when that inventory has not yet been consumed. The product must therefore show profit and cash flow as related but different concepts.

### 3.7 Production quantity relies heavily on intuition

Too much production can increase waste; too little production can produce stockouts and lost sales. Historical sales should eventually support production planning.

## 4. Product Solution

The product acts as a small-business operational and decision-support tool. It connects the real business flow:

`Purchase → Inventory → Production → Sales → Evaluation → Planning`

It must make business conditions understandable from actual recorded data, while keeping daily use simple for a non-technical food seller.

## 5. Primary Business Flow

### Purchase
The user records ingredients entering the business, including quantity, price, and relevant freshness/expiry information.

### Inventory
Unused ingredients remain inventory. The product tracks what entered, what remains, what was consumed, and what was wasted.

### Production
Ingredients are consumed according to a product composition/recipe to produce finished goods.

### Sales
Finished goods are sold at actual selling prices and quantities.

### Evaluation
The product evaluates HPP/COGS, revenue, profit, markup, margin, contribution margin, BEP, cash flow, waste, and remaining inventory.

### Planning
Once enough history exists, historical results can support demand estimation and production planning.

## 6. Inventory References

### FIFO — First In, First Out
Inventory that entered first is valued/issued first.

### LIFO — Last In, First Out
Inventory that entered last is valued/issued first.

LIFO is retained as a comparison and managerial-learning reference. It must not be represented as universally valid for statutory financial reporting.

### FEFO — First Expired, First Out
The batch with the nearest expiry or usable-until date is physically prioritized first.

FEFO is especially relevant to food because its primary purpose is reducing spoilage risk. FEFO may coexist with a separate inventory valuation method.

### Average
Inventory uses a weighted average cost based on the total inventory value divided by total inventory quantity.

## 7. Business Formula Reference

This section is the **business calculation contract**. Technical implementation may rename variables, but it must preserve the meaning of these calculations.

### 7.1 Unit Cost

`Unit Cost = Total Cost / Total Units`

Example:

`Rp200.000 / 500 bakso = Rp400 per bakso`

### 7.2 Batch Value

`Batch Value = Batch Quantity × Unit Cost`

### 7.3 Total Inventory Value

`Inventory Value = Σ(Quantity_i × UnitCost_i)`

### 7.4 Weighted Average Cost

`Average Unit Cost = Σ(Quantity_i × UnitCost_i) / Σ Quantity_i`

### 7.5 Ingredient HPP/COGS

`Ingredient HPP = Quantity Consumed × Applicable Unit Cost`

For FIFO/LIFO/FEFO, applicable cost may span multiple batches. For Average, the weighted average unit cost is applied according to the chosen averaging policy.

### 7.6 Finished Product HPP

`Product HPP = Σ(Ingredient Quantity Required × Applicable Ingredient Unit Cost) + Other Relevant Variable Production Costs`

For a bowl:

`HPP Bowl = HPP Bakso + HPP Tofu + HPP Broth + HPP Vermicelli + HPP Lontong + HPP Condiments + ...`

### 7.7 Revenue / Omzet

`Revenue = Quantity Sold × Selling Price`

### 7.8 Gross Profit

`Gross Profit = Revenue − HPP of Products Sold`

### 7.9 Net Profit

At the agreed simplified business level:

`Net Profit = Revenue − HPP − Relevant Operating Costs`

Interpretation:

- Profit > 0 → profit
- Profit = 0 → break-even
- Profit < 0 → loss

### 7.10 Markup

`Markup % = (Selling Price − HPP) / HPP × 100%`

If target profit is **40% of capital/HPP**:

`Target Selling Price = HPP × (1 + 0.40) = 1.40 × HPP`

This is a **40% markup on cost**, not a 40% profit margin on selling price.

### 7.11 Profit Margin

`Profit Margin % = Profit / Revenue × 100%`

For one unit under the simplified product-cost view:

`Unit Margin % = (Selling Price − HPP) / Selling Price × 100%`

### 7.12 Variable Cost

`Total Variable Cost = Variable Cost per Unit × Units`

### 7.13 Contribution Margin

`Contribution Margin per Unit = Selling Price − Variable Cost per Unit`

`Total Contribution Margin = Contribution Margin per Unit × Quantity Sold`

This amount first covers fixed costs; the excess contributes to profit.

### 7.14 Contribution Margin Ratio

`CMR = Contribution Margin / Selling Price`

When shown as a percentage:

`CMR % = CMR × 100%`

### 7.15 Break-Even Point — Units

For positive contribution margin:

`BEP Units = Fixed Cost / Contribution Margin per Unit`

The practical minimum sellable quantity is rounded **up** to the next whole unit.

If contribution margin is zero or negative, a finite unit BEP does not exist under the current assumptions and the product must explicitly explain this condition.

### 7.16 Break-Even Point — Revenue

For positive CMR:

`BEP Revenue = Fixed Cost / CMR`

### 7.17 Profit Function by Quantity

Let `x = quantity sold`:

`Profit(x) = Contribution Margin per Unit × x − Fixed Cost`

At break-even:

`Profit(x) = 0`

### 7.18 Target Profit Quantity

For positive contribution margin:

`Required Units = (Fixed Cost + Target Profit) / Contribution Margin per Unit`

The practical selling target is rounded **up** to a whole unit.

### 7.19 Cash Flow

`Net Cash Flow = Cash In − Cash Out`

Cash flow must not be substituted for profit.

### 7.20 Ending Inventory Quantity

`Ending Stock = Opening Stock + Stock In − Stock Used − Stock Wasted ± Other Valid Adjustments`

### 7.21 Inventory Value Reconciliation

At a simplified level:

`Opening Inventory Value + Purchases = HPP/Consumed Inventory + Ending Inventory Value + Waste Value ± Valid Adjustments`

### 7.22 Waste Cost

`Waste Value = Wasted Quantity × Applicable Unit Cost`

### 7.23 Mean

For historical demand values `D1 ... Dn`:

`Mean = ΣD_i / n`

### 7.24 Median

Median is the middle value after observations are ordered. For an even number of observations, it is the average of the two middle values.

### 7.25 Moving Average

For a window of `k` periods:

`MA_k = (D_(t−1) + D_(t−2) + ... + D_(t−k)) / k`

### 7.26 Weighted Moving Average

`WMA = Σ(w_i × D_i)`

with:

`Σw_i = 1`

More relevant observations may receive larger weights.

### 7.27 Forecast Error

Simple absolute error:

`Absolute Error = |Actual − Forecast|`

Historical error may be aggregated later to compare forecasting methods.

### 7.28 Simple Safety Stock

For a percentage-based initial model:

`Safety Stock = Forecast × Safety Percentage`

`Suggested Production = Forecast + Safety Stock`

This is an initial model, not an assertion that percentage safety stock is always optimal.

### 7.29 Overproduction

`Excess = max(Production − Demand, 0)`

### 7.30 Stockout

`Shortage = max(Demand − Production, 0)`

### 7.31 Excess/Waste Exposure

If `Cs` is the estimated economic loss per excess unit:

`Excess Cost = max(Production − Demand, 0) × Cs`

### 7.32 Lost-Sale Opportunity

If `Ck` is the economic contribution lost per unavailable unit:

`Stockout Opportunity Cost = max(Demand − Production, 0) × Ck`

These optimization-oriented formulas are advanced planning references and do not need to dominate the first version of the user experience.

## 8. Inventory Valuation vs Physical Rotation

The product must distinguish two questions:

1. **Which physical stock should be used first?**
2. **At what economic cost should consumed stock be valued?**

For food, FEFO is a strong candidate for physical stock rotation. FIFO, LIFO, or Average may be used for valuation/comparison depending on product settings and analytical goals.

Therefore:

`Stock Rotation Method ≠ Inventory Valuation Method`

The product must not silently treat them as the same concept.

## 9. Product Users

### Primary User
A small food seller who needs quick, understandable daily operations and results. This user should not be required to know accounting or mathematical terminology.

### Analytical User
A manager/family member who wants to inspect the source of calculations, compare inventory methods, understand HPP, BEP, margins, cash flow, waste, and future planning.

The product therefore supports two conceptual layers:

`Simple View + Analytical View`

## 10. Product Principles

1. **Actual data before assumptions.** Assumptions are allowed when data is unknown, but they must be identifiable and replaceable by real data later.
2. **Explainable calculations.** Important numbers must be traceable to their inputs and business rule.
3. **Simple daily operation.** Mathematical complexity belongs behind the primary interface.
4. **Purchases become inventory first.** They are not automatically treated as same-day HPP.
5. **Inventory has value.** Unused usable stock is not treated as vanished money.
6. **Waste has cost.** Spoilage and discard must be measurable.
7. **Forecasts are estimates, not facts.** Recommendations should expose their basis and uncertainty.
8. **Record → Understand → Predict.** Historical data should exist before prediction becomes a major decision feature.
9. **The product follows the real business.** It should not force a small seller into unnecessary enterprise-accounting workflows.

## 11. Initial Product Scope

The product may cover:

- ingredient/product catalog;
- purchase recording;
- inventory batches;
- stock movement;
- FIFO/LIFO/FEFO/Average references;
- recipes/compositions;
- production recording;
- sales recording;
- operating expenses;
- HPP;
- revenue;
- profit/loss;
- markup;
- margin;
- contribution margin;
- BEP;
- cash flow;
- waste;
- historical reporting;
- forecasting references;
- production planning.

The initial product is **not required** to become a full enterprise accounting suite. It does not initially require payroll, taxation, marketplace functions, payment gateway integration, multi-branch accounting, or full statutory double-entry accounting.

## 12. Product Development Direction

The product should evolve through three levels:

### Descriptive
**What happened?**

Example: revenue, HPP, profit, waste, and ending stock today.

### Diagnostic
**Why did it happen?**

Example: profit decreased because raw-material costs rose, sales fell, or waste increased.

### Prescriptive
**What should be considered next?**

Example: an explainable production recommendation derived from history and current stock.

## 13. Relationship to GOALS.md

This PRD defines the origin, problem, solution context, business concepts, and business-rule references.

`GOALS.md` derives from this PRD and defines the **finished product outcomes and user-visible capabilities**. `GOALS.md` must not become a technical architecture document.

## 14. Product Statement

The desired transformation is:

`Buy → Sell → Receive Money`

into:

`Buy → Manage → Produce → Sell → Measure → Understand → Plan`

The product succeeds when the seller can understand not only **how much money was received**, but also **what the business actually produced economically, why, and what information should guide the next decision**.
