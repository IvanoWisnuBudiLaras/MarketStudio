# Bakso Business Assistant — Documentation Starter

This folder is the product and engineering documentation baseline for an Android-first Flutter application that helps a small food seller understand inventory, HPP, profit/loss, break-even, cash flow, waste, and eventually production planning.

## Read First

1. `PRD.md` — product origin, problem, business concepts, formulas.
2. `GOALS.md` — final user outcomes and desired application flow.
3. `AGENTS.md` — instructions for AI coding agents.
4. `DESIGN.md` — technical architecture.
5. `WORKFLOW.md` — development → testing → production → maintenance process.
6. `docs/tickets/` — ordered implementation work.

## Locked vs Living Documents

### Locked product baseline
- `PRD.md`
- `GOALS.md`

These change only when the product owner changes the intended product.

### Living technical documents
- `DESIGN.md`
- `WORKFLOW.md`
- `docs/tickets/TICKET-*.md`

These may evolve during engineering as long as they continue to satisfy PRD/GOALS.

## Recommended Ticket Order

### MVP Core
1. TICKET-001 — Project Foundation
2. TICKET-002 — Money, Quantity, and Business Primitives
3. TICKET-003 — Ingredient Catalog and Purchase Batches
4. TICKET-004 — Inventory Consumption Policies
5. TICKET-005 — Recipes and HPP Engine
6. TICKET-006 — Production Flow
7. TICKET-007 — Sales and Business Day
8. TICKET-008 — Expenses, Cash Flow, and Profit
9. TICKET-009 — BEP, Margin, and Today Dashboard
10. TICKET-010 — Waste and Inventory Alerts
11. TICKET-011 — History and Analytical View

### Phase 2
12. TICKET-012 — Forecasting and Production Planning

### Production Hardening
13. TICKET-013 — Backup, Export, and Restore
14. TICKET-014 — Release Hardening and Production Gate

## AI Agent Prompt

A coding agent should be started with instructions equivalent to:

> Read `AGENTS.md`, `PRD.md`, `GOALS.md`, and `DESIGN.md`. Then implement only the requested ticket from `docs/tickets/`. Preserve the product baseline, use tests for business rules, and do not broaden scope without explicit approval.
