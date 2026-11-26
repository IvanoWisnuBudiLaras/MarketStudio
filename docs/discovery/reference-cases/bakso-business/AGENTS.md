# Agent Instructions

This repository is an AI-assisted Flutter project for a small food-business decision-support application.

## Mandatory Reading Order

Before proposing or implementing a feature, read:

1. `PRD.md` — product origin, business problem, and calculation contract.
2. `GOALS.md` — finished user outcomes and product behavior.
3. `DESIGN.md` — technical architecture and implementation constraints.
4. The relevant `docs/tickets/TICKET-*.md` file.

## Product Baseline

`PRD.md` and `GOALS.md` are **locked product baseline documents**.

Do not modify them merely to simplify implementation.

A change to either document is allowed only when the product owner explicitly changes the product meaning, requirement, or desired outcome.

If implementation conflicts with PRD/GOALS, implementation must change unless the product owner approves a product-baseline change.

## Technical Documents

`DESIGN.md` and `docs/tickets/TICKET-*.md` may evolve as implementation knowledge improves, provided they continue to satisfy `PRD.md` and `GOALS.md`.

## Core Business Flow

`Purchase → Inventory → Production → Sales → Evaluation → Planning`

## Core Engineering Rules

- Android-first Flutter application.
- Offline-first for core business operations.
- Material Design 3 for UI foundations.
- Money is represented as integer rupiah values; do not use binary floating point for stored monetary amounts.
- Quantity precision must be explicit per ingredient/unit.
- Purchases create inventory; they are not automatically same-day HPP.
- Inventory movements must be auditable.
- Inventory physical rotation and inventory valuation are separate concepts.
- Important business calculations must be deterministic and explainable.
- Forecasts and recommendations must expose their basis and must not be presented as certainty.
- Prefer the simplest implementation that preserves the domain rules.
- Business rules must be testable independently from UI.

## Development Discipline

For every ticket:

1. Read its PRD/GOALS references.
2. Write or update automated tests for business behavior first when practical.
3. Implement the smallest coherent change.
4. Run static analysis and relevant tests.
5. Verify behavior against acceptance criteria.
6. Do not silently broaden scope.

## UI Language

The primary user experience uses simple business language. Analytical terminology belongs in analytical/detail views.

Do not expose implementation terminology to the primary user.
