---
name: terminology-clarity
description: Evaluate whether webpage terminology, abbreviations, billing nouns, and lifecycle states are understandable in their decision context. Use whenever a terminology-clarity CheckSpec supplies page copy and element evidence.
metadata:
  version: "1.0.0"
---

# Terminology clarity

Judge whether a target user can understand a term's meaning and consequence from nearby page evidence.

## Method

1. Identify unexplained abbreviations, specialist nouns, billing units, and lifecycle states that affect comparison or action.
2. Check nearby headings, labels, FAQ text, and examples before concluding that an explanation is missing.
3. Do not require explanations for widely understood interface terms or product names.
4. Fail only when ambiguity can materially change selection, cost understanding, or the expected next action.
5. Use `needs_verification` when the definition may exist behind an unopened control.

## Output

Return the caller's exact JSON shape. Quote the ambiguous term and missing decision context. For failures, include the supplied element refs containing the term; otherwise return an empty element_refs array.
