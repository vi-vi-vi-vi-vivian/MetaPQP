---
name: journey-cross-stage-consistency
description: Compare structured evidence from two or more cloud-product journey pages for semantic continuity. Use for Journey CheckSpecs covering product identity, commercial terms, offerings, decision guidance, action expectations, terminology, selection state, lifecycle state, and commitment policies.
metadata:
  version: "1.0.0"
---

# Journey cross-stage consistency

Compare only the pages named by each invocation and only its requested evidence facets. Treat every page as a different view of a potentially shared business object; establish that shared scope before judging a difference.

## Method

1. Match the product, offering, account or resource, region, audience, time, and stated conditions needed by the current CheckSpec.
2. Compare concrete claims from the named pages. Preserve legitimate differences caused by page purpose, detail level, lifecycle stage, or conditional scope.
3. Return `fail` only for an explicit conflict or a qualified continuity gap that could change product understanding, a purchase decision, or an operation result.
4. Return `pass` when the relevant facts can be matched without a material conflict. Different wording, layout, ordering, or omitted repetition remains a pass.
5. Return `not_applicable` when the compared pages do not contain the business facet required by the CheckSpec.
6. Return `needs_verification` when evidence exists but the objects or conditions cannot be matched confidently.

For `adjacent`, judge each named pair independently. For `anchor_to_each`, compare the anchor with the other named node. For `all_observed`, form one conclusion from the complete named node set.

## Qualified continuity gaps

Treat missing information as an issue only when the current CheckSpec explicitly protects continuity and the evidence establishes both the earlier signal and a later decision point that still needs it.

For `decision_guidance`, first bind the earlier recommendation, popularity, value, or priority cue to a specific option. Return `fail` when the next page still asks the user to compare the same option set but removes that cue without an equivalent indicator or explanation. Return `pass` when the cue is preserved, the selected option itself carries the intent forward, or the next page no longer presents a choice. Use `needs_verification` when the cue cannot be bound to an option or the option sets cannot be matched.

Do not treat card order, visual style, shorter copy, or a missing marketing badge alone as evidence. The issue is the loss of a decision aid while the same decision remains open.

## Evidence and output

Return the caller's exact JSON shape with one result per invocation. Both `pass` and `fail` need at least two concise, searchable evidence statements drawn from different pages. A failure also needs confidence of at least 0.8. Explain which statements agree or conflict and why they describe the same business object; for conflicts, also explain the user impact and give a concrete correction. Keep suggestions empty for all other statuses.

Write `reason`, `evidence`, and `suggestion` in Simplified Chinese while preserving exact product names, plan names, numbers, prices, and quoted interface text.
