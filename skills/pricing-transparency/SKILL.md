---
name: pricing-transparency
description: Evaluate whether displayed prices expose currency, billing unit, period, quota or resource amount, validity, and applicable scope sufficiently for comparison. Use whenever a pricing-transparency CheckSpec supplies pricing-page evidence.
metadata:
  version: "1.0.0"
---

# Pricing transparency

Check whether each displayed offer can be understood and compared without inventing transaction details that do not belong on a landing page.

## Method

1. Identify the price, currency, billing period, included quota or resource, and applicable audience or scope.
2. Compare repeated plan cards for missing units or inconsistent periods.
3. Require fee breakdown, tax, discount, or effective-time detail only when the page claims a total that depends on those components.
4. Fail when a missing field could cause a materially wrong cost comparison.
5. Use `needs_verification` when decisive details are available only after selecting a plan or entering checkout.

## Output

Return the caller's exact JSON shape. Evidence must name the affected offer and missing field. For failures, cite its supplied element refs; otherwise return an empty element_refs array.
