---
name: perfect-web-clone
description: >-
  Reproduce a live website from its URL as a clean, deployable Vite + React
  project by running the complete agent-driven Perfect Web Clone harness:
  capture source evidence, plan the full page, author every section, implement
  common interactions, build, compare, repair, and hand the measured result to
  the user for review. Use whenever the user asks an agent to clone, copy,
  reproduce, replicate, rebuild, or 复刻 a website or web page, including a
  minimal request containing only an action and URL. The user gives one natural
  language instruction; the current agent runs the internal multi-step loop
  through the deterministic pwc hands and eyes.
---

# Perfect Web Clone

Pixel-perfect cloning is this skill. The current agent is the harness runtime.
`pwc` is the deterministic hands and eyes: it captures, persists, builds,
renders, replays, and measures. It never calls another model. You understand
the evidence, author code, and choose targeted repairs.

A single natural-language request such as “复刻 https://example.com” authorizes
the entire local reproduction workflow. Treat it as one user operation even
though the harness performs many internal tool calls and repair iterations.

Do not ask for routine confirmation when the request contains a usable URL.
Infer that a full-page clone is the default.
Continue across phases without returning control merely to announce progress or
request ordinary implementation choices. Ask only when a missing fact would
materially change scope, when credentials or new authority are required, or when
the user must resolve an external blocker.

Deployment is never implicit. Produce a local build and review URL by default;
deploy only when the user explicitly asks.

Use one owning agent for the whole page so global visual context survives across
sections. Do not delegate unless the user explicitly asks.

## Non-negotiable execution contract

1. Run capture, planning, authoring, build, verification, repair, and handoff as
   one continuous task.
2. Inspect every `ok` or `success` flag and its error evidence. Never invent a
   tool result.
3. Preserve immutable raw evidence separately from normalized evidence. Refuse
   to plan from an incomplete capture.
4. Reproduce every planned top-level section and every independently required
   critical region. Do not stop after the viewport or after a visually dominant
   subset.
5. Implement and replay every required common interaction: carousel, menu, tabs,
   accordion/details, and other contracts discovered during capture.
   A visually similar but inert control fails.
6. Run gates in dependency order. A downstream score cannot override an
   upstream structural or behavioral failure.
7. Repair the smallest owning component identified by evidence, rebuild, and
   re-run all affected gates.
8. Never hide, waive silently, or average away a red gate.
   A missing critical region cannot be offset by aggregate visual similarity.
9. End only in `ready_for_user_review` or `failed_with_residuals`.
   Only the user can accept the result.

Read [references/harness-contract.md](references/harness-contract.md) before
starting a new run or resuming one. It defines the progress ledger, terminal
states, evidence vocabulary, and exact stop rules.

Install the measured core if `pwc` is missing:

```bash
pip install "git+https://github.com/ericshang98/Perfect-Web-Clone.git"
playwright install chromium
```

Every `pwc` command prints JSON. `ok: false` is a stop-and-fix signal.

## Continuous workflow

### 1. Resolve and resume

- Extract the target URL from the request. If none is present and it cannot be
  recovered from the current browser/task context, ask for it.
- Check the active sandbox for `.pwc/run.json`. Resume rather than restart when
  its URL matches and its status is non-terminal. Start a fresh run when the URL
  differs.
- Record the current phase and evidence after every successful phase and after
  every failure. The ledger is an audit trail, not a substitute for tool output.

### 2. Capture trustworthy source evidence

```bash
pwc extract <url>
```

- Require `ok: true` and
  `summary.capture_integrity.status == "passed"`.
- Record `source_id`; use the same value for all later commands.
- Surface `capture_residuals` and the `site_classification` ceiling. If the page
  relies on WebGL, runtime canvas drawing, or scroll choreography that cannot be
  captured faithfully, continue only within the measured ceiling and keep it as
  a residual.
- Stop with `failed_with_residuals` if source integrity remains red after the
  extractor's retry budget. Never generate from guessed or partial content.
- Immediately inspect the capture inventory (screenshots, breakpoints, discovered
  interactions) in the source directory so breakpoint, state, and interaction
  expectations exist before code generation. Record them in `.pwc/run.json`.

### 3. Plan the complete page

```bash
pwc plan <source_id>
```

- Use the ordered real `#main` children as section and repair units.
- Treat every `required_structure` entry as a hard anchor, even when nested
  inside a large parent section.
- Review page geometry and source screenshots before authoring. Confirm that the
  plan spans the captured document height and contains the prominent regions
  visible in the raw evidence.
- Record all planned section ids in `.pwc/run.json`.

### 4. Create the shell and author every section

```bash
pwc assemble <source_id>
```

Missing section files are expected on this first call. Assembly initializes
`.pwc/run.json`; read, update, and rewrite that ledger as the agent advances.

For each planned section, in order:

1. `pwc section <source_id> <section_name>`
2. Author clean semantic JSX and scoped local styles from the section evidence.
3. Write only its namespaced component files under
   `src/components/sections/<namespace>/`.
4. Mark the section complete in `.pwc/run.json`.

Maintain whole-page layout tokens across sections. Reuse localized assets from
the capture. Never ship source-framework markup, source-specific class
fingerprints, hotlinked media, or an image snapshot in place of real content.
Use real text, images, links, video, and controls.

Apply these authoring requirements:

- Preserve sticky behavior and avoid clipping sticky ancestors.
- Reconstruct footer columns from source layout geometry.
- Render review widgets from captured review data.
- Emit functional localized video elements.
- Reveal recoverable lazy content instead of preserving an accidental empty
  capture state.
- Attach `data-pwc-critical="<anchor>"` to each required structural region.
- Keep the assembly-owned `data-pwc-section` wrapper for every section.

For each interaction contract:

- Implement its state transition and visible controlled surface.
- Attach `data-pwc-interaction="<contract id>"` to the control.
- Attach `data-pwc-controlled="<contract id>"` to the controlled surface where
  applicable.
- Support repeated activation where the source does, such as next/previous
  carousel steps and open/close menu or accordion behavior.

An unresolved asset, region, or behavior becomes an explicit residual.

### 5. Build before judging fidelity

```bash
pwc assemble <source_id>
pwc build
```

- Require no `missing_section_files`.
- Require `success: true` plus a produced `dist/`.
- On failure, read the build JSON, repair the owning component, and rebuild.

Never run acceptance scoring against a broken or stale build.

### 6. Verify in gate order

Start a local preview of `dist/` and retain its URL for user review. Verify at
the captured breakpoints and observable states.

Run:

1. Source integrity from extraction.
2. Critical structure: every planned section and `data-pwc-critical` anchor exists.
3. Required interaction replay in the preview (carousel, menu, tabs, accordion).
   Static look-alikes fail.
4. `pwc fingerprints <dist_dir>`
5. `pwc weight <dist_dir>`
6. Screenshot the clone and
   `pwc score --ref <source.png> --cand <clone.png>`
   Use `--sections` with per-section bounds when heights differ.
7. Compare to a same-source baseline when one exists.

Do not treat one aggregate SSIM number as acceptance. Structure, interaction,
and each required breakpoint/state remain individually visible in the result.

### 7. Repair automatically

While a required gate is red and budget remains:

1. Select the earliest failed hard gate; within it select the worst measured
   section or state.
2. Map its evidence to the owning component using section bounds, interaction
   ids, screenshot diffs, and diagnostic output.
3. Read the current component and `pwc section <source_id> <name>`.
4. Make one evidence-based repair to that component or shared token when the
   evidence proves the error is global.
5. Rebuild and replay every affected structural, behavioral, and visual gate.
6. Update `.pwc/run.json` with the attempt, measurement delta, and evidence
   paths.

Use at most five repair attempts per breakpoint × state. Stop early after one
non-improving retry followed by a second attempt that also fails to improve the
same metric. Preserve the best measured candidate; do not leave a regression as
the final artifact.

### 8. Hand off honestly

Set `ready_for_user_review` only when:

- capture integrity passed;
- all planned sections and critical anchors exist materially;
- all required common interactions replay successfully;
- the production build passed;
- fingerprints and required budgets passed;
- required visual breakpoint/state gates passed; and
- every claimed result has an evidence path or tool output.

Otherwise set `failed_with_residuals` and list every residual with its gate,
section/state, expected value, measured value, evidence, attempts, and reason for
stopping.

Return the local review URL, source project path, `dist/` path, evidence/report
paths, gate summary, and residuals. Say “ready for your review,” never “accepted”
or “pixel-perfect.” The user's visual and functional review is the final
decision.

## Tool map

| Purpose | `pwc` command |
|---|---|
| Capture | `pwc extract <url>` |
| Plan | `pwc plan <source_id>` |
| One section's evidence | `pwc section <source_id> <name>` |
| Shell | `pwc assemble <source_id>` |
| Build | `pwc build` |
| Fingerprints | `pwc fingerprints <dist>` |
| Weight | `pwc weight <dist>` |
| Visual score | `pwc score --ref <png> --cand <png>` |

Authoring writes `src/components/sections/<namespace>/` in the assembled
project. Preview is a local server on `dist/`. Interaction replay is done in
that preview; a visually similar but inert control fails.

Deterministic codegen (`html_to_jsx`) is a starting point, not the default path
for client-quality work.
