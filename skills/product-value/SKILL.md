---
name: product-value
description: Evaluate whether a product page clearly states its audience, problem, value, and differentiators. Use for product-value and awareness-page CheckSpecs when structured page evidence is supplied.
metadata:
  version: "1.0.0"
---

# Product value clarity

Evaluate only the supplied CheckSpec and page evidence. Treat the page as a user decision surface, not as marketing copy to rewrite wholesale.

## Method

1. Identify the intended user or situation from explicit page text.
2. Identify the problem, task, or outcome the product claims to address.
3. Locate concrete benefits or differentiators that support that claim.
4. Check whether a first-time visitor can connect audience, problem, and benefit without relying on unstated product knowledge.
5. Return `needs_verification` when evidence is truncated, hidden behind interaction, or insufficient.

Do not judge visual style, component spacing, or brand preference. Do not invent missing product facts.

## Finding threshold

Return `fail` only when the missing or contradictory value explanation could materially obstruct understanding or comparison. Give evidence using exact short phrases from the supplied page data and make the suggestion specific to the gap.

## Output

Return the exact JSON object required by the caller. Produce one result for the current CheckSpec, with status, title, reason, evidence, element_refs, confidence, and suggestion. For a failure, cite supplied element refs that locate the missing or contradictory value expression when possible.
