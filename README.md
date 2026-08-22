# Perfect Web Clone

**Pixel-perfect clones of any webpage.** Paste a URL. Get a clean, deployable Vite + React replica that is measured against the original — not guessed.

English | [中文](README_CN.md)

A screenshot is not a clone. Perfect Web Clone captures the live page, rebuilds it as real components, then scores the result section by section until it matches.

## What you get

- A full-page capture: DOM, computed styles, fonts, images, video
- Clean Vite + React + Tailwind output, not a dump of the source framework
- Localized assets — no hotlinks back to the original site
- Measured gates: source fingerprints, code weight, per-section visual score
- A repair loop that fixes the worst section and re-measures

Say this to your coding agent:

```text
clone https://example.com
```

## Install

Python 3.10+ and Node 20+.

```bash
pip install "git+https://github.com/ericshang98/Perfect-Web-Clone.git"
playwright install chromium
```

Then load the skill from [`perfect-web-clone-skill`](https://github.com/ericshang98/perfect-web-clone-skill) into Claude Code, Codex, or any coding agent that can run `pwc`.

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
