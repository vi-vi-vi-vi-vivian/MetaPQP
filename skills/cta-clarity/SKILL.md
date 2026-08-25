---
name: cta-clarity
description: Evaluate whether a page CTA communicates the action, object, and expected destination. Use for CTA wording and CTA-to-destination CheckSpecs when element and surrounding-page evidence is supplied.
metadata:
  version: "1.0.0"
---

# CTA clarity

Evaluate the current CheckSpec using only supplied CTA elements, surrounding content, page context, and destination evidence when available.

## Method

1. Identify the CTA's action, object, and expected next state.
2. Use nearby headings or card labels when they clearly supply the missing object.
3. Distinguish a vague label from a misleading destination; the latter is more severe.
4. When destination evidence is required but absent, return `needs_verification` instead of guessing.
5. Ignore button color, shape, spacing, and other visual-style preferences.

Generic labels such as “了解更多” are not automatically failures. Judge whether the surrounding context makes the destination unambiguous.

## Output

Return the exact JSON object required by the caller. Produce one result for the current CheckSpec, with status, title, reason, evidence, element_refs, confidence, and suggestion. For a failure, cite only supplied element refs that locate the problematic CTA.
