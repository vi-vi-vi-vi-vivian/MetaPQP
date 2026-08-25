---
name: copy-quality
description: Inspect supplied webpage copy for concrete Chinese typos, missing or duplicated words, obvious grammar defects, and punctuation mistakes. Use whenever a copy-quality CheckSpec supplies visible text and element-level evidence.
metadata:
  version: "1.1.0"
---

# Copy quality

Inspect the supplied Chinese visible copy character by character. Report objective language defects that an operator can accept without debating style. Product names, abbreviations, deliberate fragments, concise labels, and grammatically valid but less idiomatic wording pass.

## Method

1. Find exact phrases containing a provable typo, accidental duplicated word, missing word that breaks grammar, definite grammatical contradiction, or clearly incorrect punctuation.
2. Verify each candidate from its surrounding sentence; do not infer errors from a truncated fragment.
3. Apply a strict acceptance test: the original must be objectively wrong, not merely less natural, less polished, or different from an editor's preferred phrasing.
4. Return `pass` for optional additions such as changing “适用文件处理” to “适用于文件处理”, synonym substitutions, tone changes, sentence polishing, and marketing optimization.
5. Return `fail` only when the exact defect and a necessary correction can both be stated with high confidence.
6. Return `needs_verification` when surrounding text is truncated or the term may be a product-specific proper noun.

## Output

Return the caller's exact JSON shape. Evidence must quote the objectively faulty phrase and its necessary correction. A stylistic alternative is not evidence. For failures, include the supplied `element_ref` values that contain the faulty copy; otherwise return `element_refs: []`.
