---
name: transition-intent-result-consistency
description: Verify that a safe page interaction delivers the result promised by its visible label and surrounding content.
metadata: {version: "1.0.0"}
---

# Interaction intent and result consistency

Evaluate each interaction independently. Fail only when the visible interaction label or nearby content promises a concrete destination, detail, preview, plan, help, or action, and the observed result clearly conflicts with that promise. A URL change alone is not proof. Pass only when the result visibly fulfils the promise. Use `needs_verification` if the resulting content cannot establish the relationship.
