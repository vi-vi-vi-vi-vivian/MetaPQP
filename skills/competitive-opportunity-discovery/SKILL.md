---
name: competitive-opportunity-discovery
description: Identify evidence-backed, transferable product-experience opportunities from a current page and dynamically supplied reference pages.
metadata: {version: "1.0.0"}
---

# Competitive opportunity discovery

Compare comparable decision contexts only. A reference practice is useful only if it is visible in the supplied evidence, helps a user understand, evaluate, start, continue, or safely commit to the product, and can transfer without assuming the reference product's business model.

Return `fail` only when all of these are true: the reference practice is concrete; the subject has a concrete gap for the same user decision; the user benefit is explained; and exact element references exist on both sides. Return `pass` when no such opportunity is demonstrated. Do not report aesthetic preference, brand copying, feature parity, or unsupported product claims.

For every result, write a concise `issue_description`. For a `fail`, populate `subject_display` and each applicable `reference_displays` item with the exact visible content and `element_refs` that prove the comparison; populate `recommendation` with an actionable change. The report derives the displayed quotations directly from those element references and crops both screenshots around them. Therefore, select only elements whose text proves the claim; never use a page-wide summary, a nearby heading, or an off-canvas carousel item in place of located evidence.

## Rule-specific acceptance tests

- **最终成果是否在决策前可见**: fail only when the reference proves both a typical task or scenario and its resulting output, effect, or verifiable outcome, while the subject has only capability claims or generic applicability. A customer case is not mandatory if the subject already shows a concrete input-to-output example, result demonstration, or measurable outcome. Do not infer animation waiting time from a static screenshot or DOM text alone.
- **核心价值是否可先体验**: fail only when the reference offers a directly reachable free allowance, trial, interactive preview, or result example for the core value and the subject lacks an equivalent. Contact links, documentation, or unrelated downloads are not trials.
- **方案选择是否清晰**: apply only to a single decision area with two or more selectable offers. Fail only when the reference supplies comparable, decision-relevant dimensions that explain offer differences and the subject supplies only price or qualitative labels. Do not compare different product objects or commercial models.
- **关键决策信息是否在选择前说清**: evaluate only the same purchase, subscription, or option-selection area. Consider only information that can materially change the decision: price and billing period, included allowance, overage treatment, eligibility, cancellation, or an annual/term discount that is itself evidenced on the captured official page. Never assert that an annual discount is absent when its existence was not evidenced.
- **承诺与限制是否提前说明**: apply only where a final commitment, payment, subscription, or irreversible action is actually visible. A missing term on an introductory page is not a failure.
- **用户选择是否连续保留**: apply only with evidence of a user selection, a following step, and a visible retained or lost state. A static single page cannot prove this; return `needs_verification` or `not_applicable`.
