---
name: page-title-identity-consistency
description: Check whether the browser document title accurately identifies the product, service, or task visibly presented on the current page.
metadata:
  version: "1.0.0"
---

# Browser title and page identity consistency

Assess the browser document title (`page.title`) against the actual identity of the visible page. This rule is about the browser tab, history, bookmarks, and assistive-technology page identification; it is not a check of the audit report title.

## Method

1. Identify the current page's primary business identity from repeated, visible product/service/task text. Prefer a visible breadcrumb, primary page heading, selected product or plan name, and purchase or task heading. Do not infer identity solely from a URL, DOM class, asset path, or a footer.
2. Treat a browser title as sufficient when it identifies that primary identity directly, or when the visible evidence does not establish one clear identity.
3. Fail only when all of the following hold:
   - visible evidence establishes one clear current product, service, or task identity;
   - the browser title does not identify that identity or a recognizably equivalent parent name;
   - the title is a generic portal/console/container label or names a materially different product or service; and
   - at least two visible elements support the current identity, including one page-level heading, breadcrumb, selected option, or task label.
4. A platform name is not by itself a valid substitute for a selected product's purchase page. When the visible page heading, breadcrumb, or order summary explicitly identifies a single product or plan being bought, the title must identify that product or task too. A service statement, footer, or incidental platform reference does not establish a parent-product relationship and must not downgrade this case to `needs_verification`.
5. Return `needs_verification` only if the page has multiple equally primary products/tasks, or the visible evidence genuinely cannot establish one current identity.
6. Do not fail merely because the title is shorter, omits a plan tier, differs in punctuation/capitalization, or uses a well-known parent brand together with the current product.

## Output

For a failure, quote the observed browser title and the visible identity, cite only the element refs that establish the visible identity, and suggest a descriptive title that includes the current product/service/task. For pass or needs_verification, return an empty `element_refs` array unless a location is necessary to explain ambiguity.
