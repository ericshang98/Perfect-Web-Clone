---
name: perfect-web-clone
description: >-
  Reproduce a live website from its URL as a clean, deployable Vite + React
  project: capture source evidence, plan the full page, author every section,
  build, compare, repair, and hand the measured result to the user for review.
  Use when the user asks to clone, copy, reproduce, replicate, rebuild, or 复刻
  a website, including a request that is only an action and a URL.
---

# Perfect Web Clone

## Operating model

The current coding agent is the runtime. `pwc` is the deterministic hands and
eyes. It never calls a model. You understand the evidence, author code, and
repair the worst section.

One request such as `clone https://example.com` authorizes the whole local
reproduction. Do not stop between phases to announce progress. Ask only when a
missing fact would change scope.

Deployment is never implicit. Produce a local build and a review URL. Deploy
only when the user asks.

Use one owning agent for the whole page. Do not delegate unless the user asks.

## Non-negotiable contract

1. Capture, plan, author, build, verify, repair, and hand off as one task.
2. Inspect every `ok` flag. Never invent a tool result.
3. Refuse to plan from an incomplete capture.
4. Reproduce every planned section. Do not stop after the viewport.
5. Implement required common interactions. A similar but inert control fails.
6. Run gates in order. A downstream score cannot override an upstream failure.
7. Repair the smallest owning component, rebuild, re-run affected gates.
8. Never hide a red gate. A missing region cannot be offset by average SSIM.
9. End only in `ready_for_user_review` or `failed_with_residuals`.

Read [references/harness-contract.md](references/harness-contract.md) before a
new or resumed run.

## Tools

Prefer the `pwc_*` tools when they exist. Otherwise run the same commands:

```bash
pwc extract <url>
pwc plan <source_id>
pwc assemble <source_id>
pwc build
pwc fingerprints <dist_dir>
pwc weight <dist_dir>
pwc score --ref <reference.png> --cand <clone.png>
```

Every command prints JSON. `ok: false` is a stop-and-fix signal.

## Workflow

### 1. Capture

`pwc extract <url>`

- Require `ok: true` and `summary.capture_integrity.status == "passed"`.
- Record `source_id`.
- Surface `capture_residuals` and `site_classification`. If the page is WebGL,
  runtime canvas, or scroll choreography, continue only inside that ceiling and
  keep it as a residual.
- Stop with `failed_with_residuals` if integrity stays red.

### 2. Plan

`pwc plan <source_id>`

- Use the ordered sections as repair units.
- Confirm the plan covers the captured page, not only the first screen.

### 3. Assemble shell, then author every section

`pwc assemble <source_id>` once. Missing section files are expected.

For each planned section:

1. Read its captured html, geometry, css_rules, text, and local asset paths.
2. Author clean semantic JSX + local styles that match the captured geometry.
3. Write only `src/components/sections/<namespace>/`.
4. Reuse localized `/assets/...` paths. Never hotlink the origin. Never ship
   source-framework class fingerprints.

Then `pwc assemble <source_id>` again. Require no `missing_section_files`.

### 4. Build

`pwc build`. Require success and a `dist/`.

### 5. Verify in order

1. Capture integrity (from extract).
2. `pwc fingerprints <dist>`
3. `pwc weight <dist>`
4. Screenshot the clone at the captured breakpoints.
5. `pwc score --ref <source screenshot> --cand <clone screenshot>`
   Use `--sections` with per-section bounds when heights differ.

Do not treat one aggregate SSIM number as acceptance.

### 6. Repair

While a required gate is red and budget remains:

1. Take the earliest failed hard gate; inside it take the worst section.
2. Repair that component from evidence.
3. Rebuild and re-run affected gates.
4. Cap: five attempts per breakpoint × state. Stop after two non-improving tries.

### 7. Hand off

`ready_for_user_review` only when capture, structure, build, fingerprints,
weight, and required visual states passed, each with evidence.

Otherwise `failed_with_residuals` with every residual listed.

Return the local review URL. Say "ready for your review." Never say
"pixel-perfect" or "accepted."
