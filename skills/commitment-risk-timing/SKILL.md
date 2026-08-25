---
name: commitment-risk-timing
description: Evaluate whether subscription renewal, automatic charging, cancellation, refund, expiry, and irreversible commitment risks are disclosed before a purchase decision. Use whenever a purchase-entry CheckSpec supplies CTA and surrounding-page evidence.
metadata:
  version: "1.1.0"
---

# Commitment risk timing

Judge whether material commitment disclosures are visible on the current purchase page. A single-page audit establishes current-page disclosure only; downstream timing across checkout belongs to journey consistency checks.

## Method

1. Identify purchase or subscription CTAs and the plans they act on.
2. Identify renewal, charging, cancellation, refund, expiry, and irreversible-action statements.
3. Match each explicit commitment with the material terms that apply to it. Treat a visible disclosure anywhere on the same page as disclosed; DOM order relative to the CTA does not determine failure.
4. Return `pass` when the current page visibly states the applicable material restriction, including when the statement is below or beside the CTA.
5. Return `fail` only when the evidence proves this page contains the final irreversible submission action and omits a material term known from the supplied evidence.
6. Return `needs_verification` when the current page omits a relevant term but an uninspected order-confirmation or payment step may disclose it.

## Output

Return the caller's exact JSON shape. Evidence must quote the commitment and the matching disclosure, or identify the missing term without inventing product policy. For failures, include refs for the final submission control and relevant decision area; otherwise return an empty element_refs array.
