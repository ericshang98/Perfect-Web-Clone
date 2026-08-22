# Perfect Web Clone

**Pixel-perfect clones of any webpage.** This repo is the measured core. The product is the [skill](skill/SKILL.md): an agent harness that turns one `clone <url>` into a full-page, scored replica.

English | [中文](README_CN.md)

A screenshot is not a clone. The skill drives the agent through capture → section plan → clean React → build → measured repair, and it will not stop after the first viewport or call a similar-looking inert widget “done.”

Say this to your coding agent:

```text
clone https://example.com
```

## The skill is the product

[`skill/SKILL.md`](skill/SKILL.md) is the harness. Same file is published as [`perfect-web-clone-skill`](https://github.com/ericshang98/perfect-web-clone-skill).

- One request authorizes the whole run
- Hands and eyes are deterministic (`pwc`) — they never call a model
- The agent authors code and repairs the worst measured section
- Done means `ready_for_user_review` or `failed_with_residuals`, with evidence
- Pixel-perfect is a gate table, not a prompt

## Install

Python 3.10+ and Node 20+.

```bash
pip install "git+https://github.com/ericshang98/Perfect-Web-Clone.git"
playwright install chromium
```

Load [`perfect-web-clone-skill`](https://github.com/ericshang98/perfect-web-clone-skill) into Claude Code, Codex, or any coding agent that can run `pwc`.

## How a clone run works

1. Capture the live URL (integrity-checked, assets localized)
2. Plan the real page sections
3. Author clean React for every section
4. Assemble and build
5. Score fingerprints, weight, and visual match
6. Repair the worst section, rebuild, re-measure
7. Hand you a local preview: `ready_for_user_review` or `failed_with_residuals`

If the page is WebGL, runtime canvas, or scroll-choreographed, that ceiling is reported up front. Content still clones; the runtime-drawn look may not.

## CLI

```bash
pwc extract https://example.com
pwc plan <source_id>
pwc assemble <source_id>
pwc build
pwc fingerprints dist/
pwc weight dist/
pwc score --ref reference.png --cand clone.png
```

Every command prints JSON. `ok` is the only pass/fail that matters.

## Layout

```text
core/          capture, section plan, gates
pwc/           CLI
skill/         the playbook
plugin/        optional coding-agent plugin
templates/     Vite + React + Tailwind shell
```

## License

MIT
