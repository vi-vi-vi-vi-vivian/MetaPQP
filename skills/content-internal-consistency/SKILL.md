---
name: content-internal-consistency
description: Compare product names, plan facts, rules, states, and commitments across a single page's body, plan cards, FAQ, notices, and product-specific footer copy. Use for internal-consistency CheckSpecs on content-rich product pages.
metadata:
  version: "1.0.0"
---

# Content internal consistency

Compare equivalent business facts within the current page. A difference is an issue only when the two statements apply to the same product, plan, audience, and condition.

## Method

1. Extract repeated claims about product identity, plan quota, price period, availability, renewal, refund, and cancellation.
2. Compare statements only after matching their business scope and conditions.
3. Treat generic footer text as evidence only when it explicitly applies to the audited product.
4. Fail when two concrete statements conflict and could change a decision or action.
5. Use `needs_verification` for hidden FAQ answers or ambiguous scope.

## Output

Return the caller's exact JSON shape. Evidence must quote both sides of a conflict. For failures, include element refs for both conflicting statements; otherwise return an empty element_refs array.
