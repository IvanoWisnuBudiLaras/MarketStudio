# Product Goals

**Status:** Product Baseline — Locked  
**Version:** 1.0  
**Primary reference:** `PRD.md`

> `GOALS.md` defines the finished outcomes and user-visible capabilities of the product. It does not define Flutter architecture, database structure, state management, packages, or implementation details.

## 1. North Star Goal

The user should be able to open the application and answer, quickly and confidently:

> **“Is my business healthy today?”**

Then the product should help answer:

> **“Why?”**

and eventually:

> **“What should I consider doing next?”**

## 2. Primary Outcome

The application must transform daily selling from a habit-driven activity into a measurable business process:

`Selling → Recording → Measuring → Understanding → Planning`

without making daily operation unnecessarily complicated.

## 3. Main User Flow

The product experience follows the real business flow:

`Buy → Store → Use → Produce → Sell → Evaluate → Plan`

### Buy
The user records what was purchased and its value.

**Expected result:** the user knows what entered the business and how much money was spent.

### Store
Unused ingredients remain inventory.

**Expected result:** the user knows what stock still exists instead of assuming purchased money has disappeared.

### Use
Ingredients are consumed for production.

**Expected result:** the user knows the economic value of the ingredients actually used.

### Produce
Ingredients become finished products.

**Expected result:** the user can understand the true cost of producing what is sold.

### Sell
Finished products are sold to customers.

**Expected result:** the user sees actual quantity sold and revenue earned.

### Evaluate
The application summarizes business performance.

**Expected result:** the user sees whether the period produced profit, break-even, or loss, with a clear explanation.

### Plan
History and current inventory support the next decision.

**Expected result:** the user has a data-based basis for the next production quantity instead of relying only on intuition.

## 4. Goal — Know the Real Product Cost

The user must be able to answer:

> “How much does one finished product actually cost me to make?”

The answer should be traceable to its ingredients and relevant variable costs.

The primary user does not need to calculate the result manually.

## 5. Goal — Know Profit or Loss

At the end of a selling period, especially a day, the application must clearly show one of these states:

- profitable;
- break-even;
- loss.

It should also explain major contributing factors such as ingredient cost, operating cost, lower sales, or increased waste.

## 6. Goal — Know the Break-Even Position

The user must be able to know:

> “How many products need to be sold before the relevant costs are covered?”

The application should clearly show whether break-even has not yet been reached, has just been reached, or has been exceeded.

## 7. Goal — Understand Profit from Multiple Perspectives

The product should help the user understand:

- profit in rupiah;
- profit relative to cost;
- profit relative to sales;
- contribution available to cover fixed costs.

Technical business terms may be available in the analytical view, but the primary experience should use understandable language.

## 8. Goal — Control Inventory

The user should know:

- current stock quantity;
- current stock value;
- recent stock additions;
- stock consumed;
- stock wasted;
- stock that should be used soon;
- stock at risk of running out.

The practical benefit is **less uncertainty and lower avoidable waste**.

## 9. Goal — Reduce Food Waste

The application should make wasted ingredients and finished products visible as an economic loss.

The user should be able to identify recurring waste patterns and use those patterns to improve future purchasing or production decisions.

## 10. Goal — Separate Profit from Cash Flow

The product must help the user understand that cash remaining is not automatically profit.

The user should be able to distinguish:

- cash received;
- cash spent;
- usable inventory still owned;
- actual profit/loss for the period.

## 11. Goal — Provide a Useful Daily Summary

At the end of a normal selling day, the user should be able to see, at minimum:

- quantity sold;
- revenue;
- HPP/COGS;
- operating costs;
- profit/loss;
- break-even position;
- waste;
- remaining inventory status.

The summary should answer the health of the business without requiring the user to open detailed calculations.

## 12. Goal — Build Meaningful History

Daily records should become usable weekly and monthly history.

The user should eventually be able to observe:

- sales trends;
- revenue trends;
- profit trends;
- cost changes;
- HPP changes;
- waste changes;
- recurring busy or quiet periods.

Historical data is not merely an archive; it is input for future decisions.

## 13. Goal — Support Production Planning

After sufficient history exists, the application should help answer:

> “How much should I prepare for the next selling period?”

The recommendation should consider available history, current inventory, demand patterns, waste risk, and stockout risk.

The recommendation must be presented as an estimate, not a guarantee.

## 14. Goal — Reduce Overproduction

The user should be able to recognize when consistently producing too much is creating excess stock, tied-up capital, or waste.

The desired outcome is production closer to realistic demand.

## 15. Goal — Reduce Stockouts

The application should also make repeated shortages visible, because producing too little can lose potential sales.

The desired outcome is sufficient availability without routinely creating unnecessary excess.

## 16. Goal — Explain Important Results

Important calculations and recommendations must be explainable.

Example simple view:

> **Estimated profit today: Rp92.000**

Example analytical explanation:

> Revenue, HPP, and operating costs that produced the Rp92.000 result.

Example planning view:

> **Suggested next production: 62 bowls**

with an explanation that the suggestion was based on recent history and current stock.

No important decision should appear as an unexplained black-box number.

## 17. Goal — Simple for the Primary User

The primary user should see familiar concepts such as:

- sales;
- income;
- costs;
- profit;
- loss;
- stock;
- stock running low;
- ingredients that should be used soon;
- break-even reached.

Complex terminology must not become a barrier to normal daily use.

## 18. Goal — Deep Enough for an Analytical User

A secondary analytical view should expose:

- HPP composition;
- inventory valuation method;
- FIFO/LIFO/FEFO/Average effects;
- markup;
- margin;
- contribution margin;
- BEP;
- cash flow;
- waste;
- history;
- forecasting inputs and result explanations.

This creates two experience layers:

`Simple View + Analytical View`

## 19. Goal — Grow from Recording into Decision Support

The product should evolve through three capabilities:

### Descriptive
**What happened?**

### Diagnostic
**Why did it happen?**

### Prescriptive
**What should be considered next?**

The first useful version must already be valuable at the descriptive level. Diagnostic and prescriptive abilities grow as higher-quality history accumulates.

## 20. Example of the Desired Finished Experience

### Today
- Sold: 63 bowls
- Revenue: Rp315.000
- Production cost/HPP: Rp174.500
- Operating costs: Rp38.000
- Profit: Rp102.500
- BEP: 22 bowls
- Status: break-even exceeded

### Inventory
- Bakso: sufficient
- Fried tofu: one batch should be used first
- Lettuce: low stock
- Waste today: Rp4.500

### Next Plan
- Recent demand usually falls around 58–64 bowls
- Current stock supports approximately 55 bowls
- Additional preparation may be needed before the next selling period

The exact numbers will come from actual user data. The goal is the clarity of the experience.

## 21. Benefits the Product Must Deliver

### Clarity
The business can be understood from data instead of guesswork.

### Control
The user can see inventory, costs, waste, and sales in one connected flow.

### Efficiency
Avoidable purchasing, overproduction, and waste can be reduced.

### Business Safety
The user can see break-even and loss risk earlier.

### Planning
Historical data becomes a basis for future action.

### Learning from the Business
The user can understand why outcomes change over time.

## 22. Final Product Outcome

The finished product should make previously hidden business information **visible, understandable, and actionable**.

The user should no longer be limited to asking:

> “How much money did I bring home today?”

The product should enable:

> **“What did the business actually produce today, why, and what should guide the next decision?”**
