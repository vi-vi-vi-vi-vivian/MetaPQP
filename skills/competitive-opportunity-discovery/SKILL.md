---
name: competitive-opportunity-discovery
description: Identify evidence-backed, transferable product-experience opportunities from a current page and dynamically supplied reference pages.
metadata: {version: "1.0.0"}
---

# Competitive opportunity discovery

Compare comparable decision contexts only. A reference practice is useful only if it is visible in the supplied evidence, helps a user understand, evaluate, start, continue, or safely commit to the product, and can transfer without assuming the reference product's business model.

Return `fail` only when all of these are true: the reference practice is concrete; the subject has a concrete gap for the same user decision; the user benefit is explained; and exact element references exist on both sides. Return `pass` when no such opportunity is demonstrated. Do not report aesthetic preference, brand copying, feature parity, or unsupported product claims.

For every result, write a concise `issue_description`. For a `fail`, populate `subject_display` and each applicable `reference_displays` item with the exact visible content and `element_refs` that prove the comparison; populate `recommendation` with an actionable change. The report uses those fields verbatim and crops both screenshots around their element references, so never use a page-wide summary in place of located evidence.
