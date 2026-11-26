# Product & Engineering Workflow

## 1. Document Authority

`PRD.md → GOALS.md → DESIGN.md → TICKET-*.md → Code → Tests`

Higher-level documents constrain lower-level work.

- `PRD.md`: why the product exists, business concepts, calculation contract.
- `GOALS.md`: what users must ultimately be able to achieve.
- `DESIGN.md`: how the system is technically structured.
- `TICKET-*.md`: bounded units of implementation work.

## 2. Product Baseline

`PRD.md` and `GOALS.md` are locked after approval.

They should change only when the intended product itself changes.

Technical difficulty is not sufficient justification for changing them.

## 3. Development Lifecycle

`Planning → Development → Testing → Production → Maintenance`

### Planning
- confirm feature fits PRD/GOALS;
- update `DESIGN.md` if architecture changes;
- create or revise a ticket;
- define acceptance criteria and test scope.

### Development
- implement the ticket in the smallest coherent increment;
- keep business logic separate from presentation;
- preserve auditability of financial/inventory data.

### Testing
- unit-test calculation rules;
- repository/database tests for persistence behavior;
- widget tests for important user interactions;
- integration tests for critical end-to-end business flows;
- run `flutter analyze` and the full test suite before release.

### Production
- produce a release build;
- smoke-test core flows using realistic sample data;
- verify database migration behavior;
- verify backup/export before schema-changing releases;
- record the release version and included tickets.

### Maintenance
- bug fixes follow the same test discipline;
- schema and calculation changes require migration and regression tests;
- monitor recurring user friction and data-quality problems;
- avoid adding features solely because they are technically interesting.

## 4. New Feature Flow After Production

`Idea → Product Fit Check → Design → Ticket → Development → Testing → Release → Maintenance`

### Product Fit Check
Ask:

1. Does the idea support an existing goal?
2. Does it change product meaning or create a new goal?
3. Is the needed data already available?
4. Can the benefit be explained to the primary user?

If the feature supports existing goals, PRD/GOALS usually remain unchanged.

If it changes product meaning, explicitly revise and re-approve the product baseline first.

## 5. Definition of Done

A ticket is complete when:

- acceptance criteria pass;
- relevant automated tests pass;
- `flutter analyze` has no ticket-introduced errors;
- calculation behavior remains explainable;
- persistence changes include migrations when required;
- primary-user wording remains understandable;
- documentation is updated where necessary.
