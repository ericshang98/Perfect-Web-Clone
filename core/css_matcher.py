"""CSS Matcher — Perfect Web Clone v3.

Per-section *critical CSS* extraction. The extractor captures the whole page's
CSS into ``css.json`` (every stylesheet's text, plus structured animations,
transitions and variables). The chunker, however, only carries each section's
HTML — so a per-section sub-agent never sees the ``:hover`` states, ``@keyframes``
animations, ``transition``s or ``@media`` breakpoints that make the section
*behave* like the original. It can only guess, which is why interactions come
out "approximate".

This module closes that gap deterministically (NO LLM): given the page CSS and
one section's HTML, it returns exactly the subset of rules that apply to that
section — base rules, their ``:hover``/``:focus`` variants, the ``@keyframes``
they reference, the ``@media`` rules that touch their elements, and the CSS
custom properties they use (resolved transitively). That subset is attached to
the section as ``css_rules`` and handed to the sub-agent.

Matching strategy: a CSS selector applies to a section when its *base* form
(pseudo-classes / pseudo-elements stripped) matches some element in the
section's HTML. Matching uses soupsieve via BeautifulSoup; selectors soupsieve
cannot parse fall back to a conservative class/id/tag-token presence test so we
never silently drop a rule we should have kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from bs4 import BeautifulSoup


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

@dataclass
class Rule:
    """One CSS rule: a selector list + its declaration body.

    ``media`` is the condition text of the enclosing ``@media`` (without the
    ``@media`` keyword), or ``None`` for a top-level rule. ``order`` preserves
    source order so output stays stable and cascade-faithful.
    """

    selectors: List[str]
    body: str
    order: int
    media: Optional[str] = None


@dataclass
class CssIndex:
    rules: List[Rule] = field(default_factory=list)
    keyframes: Dict[str, str] = field(default_factory=dict)
    variables: List[Dict[str, str]] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_KEYFRAMES_RE = re.compile(r"@(?:-webkit-|-moz-|-o-)?keyframes\b", re.IGNORECASE)


def _strip_comments(css: str) -> str:
    return _COMMENT.sub("", css or "")


def _split_top_level(css: str):
    """Yield top-level constructs of a CSS string as (prelude, block) pairs.

    ``prelude`` is the text before the brace (a selector list, or an at-rule
    header like ``@media ...``). ``block`` is the text inside the matching
    braces. At-rules with no block (``@import ...;``) are skipped.
    """
    i, n = 0, len(css)
    start = 0
    while i < n:
        ch = css[i]
        if ch == ";":
            # statement at-rule (e.g. @import) with no block — ignore
            start = i + 1
            i += 1
            continue
        if ch == "{":
            prelude = css[start:i].strip()
            depth = 1
            j = i + 1
            while j < n and depth:
                if css[j] == "{":
                    depth += 1
                elif css[j] == "}":
                    depth -= 1
                j += 1
            block = css[i + 1 : j - 1]
            yield prelude, block
            i = j
            start = j
            continue
        i += 1


def _add_rules(prelude: str, block: str, media: Optional[str], idx: CssIndex):
    selectors = [s.strip() for s in prelude.split(",") if s.strip()]
    if not selectors:
        return
    idx.rules.append(Rule(selectors=selectors, body=block.strip(), order=len(idx.rules), media=media))


def _parse_stylesheet(css: str, idx: CssIndex):
    css = _strip_comments(css)
    for prelude, block in _split_top_level(css):
        low = prelude.lower()
        if low.startswith("@media") or low.startswith("@supports"):
            media = prelude[prelude.find(" ") + 1 :].strip() if " " in prelude else ""
            for inner_prelude, inner_block in _split_top_level(block):
                if inner_prelude.lower().startswith("@"):
                    continue  # nested at-rules inside media are rare; skip
                _add_rules(inner_prelude, inner_block, media, idx)
        elif _KEYFRAMES_RE.match(low):
            name = prelude.split()[-1].strip()
            if name:
                idx.keyframes.setdefault(name, block.strip())
        elif low.startswith("@font-face"):
            _add_rules("@font-face", block, None, idx)
        elif low.startswith("@"):
            continue  # @charset, @namespace, @page, etc. — not section-scoped
        else:
            _add_rules(prelude, block, None, idx)


def build_index(css_json: Dict) -> CssIndex:
    """Parse ``css.json`` into an addressable :class:`CssIndex`."""
    idx = CssIndex()
    for sheet in (css_json or {}).get("stylesheets", []) or []:
        content = sheet.get("content") or ""
        if content.strip():
            _parse_stylesheet(content, idx)
    for var in (css_json or {}).get("variables", []) or []:
        name = var.get("name")
        if name:
            idx.variables.append(
                {"name": name, "value": var.get("value", ""), "scope": var.get("scope", ":root")}
            )
    return idx


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #

# Strip pseudo-classes / pseudo-elements to get a structurally matchable base.
_PSEUDO = re.compile(r"::?[A-Za-z-]+(?:\([^)]*\))?")
# Bare combinators / at-rule fragments soupsieve can't match meaningfully.
_TOKEN = re.compile(r"[.#]?[A-Za-z_][\w-]*")


def _base_selector(sel: str) -> str:
    """Drop pseudo-classes/elements, keeping structure for soupsieve."""
    return _PSEUDO.sub("", sel).strip()


def _selector_tokens(sel: str):
    """Class/id/tag tokens of a selector, for the conservative fallback test."""
    return set(_TOKEN.findall(_base_selector(sel)))


def _section_tokens(soup: BeautifulSoup):
    classes, ids, tags = set(), set(), set()
    for el in soup.find_all(True):
        tags.add(el.name)
        for c in el.get("class") or []:
            classes.add(c)
        if el.get("id"):
            ids.add(el["id"])
    return classes, ids, tags


def _selector_applies(sel: str, soup: BeautifulSoup, sec_tokens) -> bool:
    base = _base_selector(sel)
    if not base or base.startswith("@"):
        return base == "@font-face"  # always keep @font-face (font availability)
    # Primary: real structural match via soupsieve.
    try:
        if soup.select_one(base) is not None:
            return True
    except Exception:  # noqa: BLE001 — unsupported selector → fall back
        pass
    # Fallback: every class/id token in the selector is present somewhere in the
    # section (conservative; keeps a rule rather than risk dropping it).
    classes, ids, tags = sec_tokens
    toks = _selector_tokens(sel)
    if not toks:
        return False
    for t in toks:
        if t.startswith("."):
            if t[1:] not in classes:
                return False
        elif t.startswith("#"):
            if t[1:] not in ids:
                return False
        else:
            if t not in tags:
                return False
    return True


_VAR_REF = re.compile(r"var\(\s*(--[\w-]+)")
_ANIM_NAME = re.compile(r"animation(?:-name)?\s*:\s*([^;]+)", re.IGNORECASE)


def _used_keyframe_names(body: str, available) -> List[str]:
    names = []
    for m in _ANIM_NAME.finditer(body):
        for tok in re.split(r"[\s,]+", m.group(1).strip()):
            if tok in available and tok not in names:
                names.append(tok)
    return names


def _used_var_names(text: str) -> List[str]:
    return _VAR_REF.findall(text)


def _resolve_variables(seed_names, variables) -> List[Dict[str, str]]:
    """Return the variable definitions used, following ``var()`` chains."""
    by_name: Dict[str, Dict[str, str]] = {}
    for v in variables:
        by_name.setdefault(v["name"], v)
    out: List[Dict[str, str]] = []
    seen = set()
    stack = list(seed_names)
    while stack:
        name = stack.pop(0)
        if name in seen:
            continue
        seen.add(name)
        definition = by_name.get(name)
        if not definition:
            continue
        out.append(definition)
        stack.extend(_used_var_names(definition.get("value", "")))
    # Stable order: by first appearance in the variables list.
    order = {v["name"]: i for i, v in enumerate(variables)}
    out.sort(key=lambda v: order.get(v["name"], 0))
    return out


def _render_rule(rule: Rule) -> str:
    sel = ", ".join(rule.selectors)
    return f"{sel} {{ {rule.body} }}"


def match_section_css(section_html: str, index: CssIndex, max_chars: int = 30000) -> str:
    """Return the subset of ``index`` that applies to ``section_html``.

    Output layout (cascade-faithful, deterministic):
      ``:root`` used variables → base rules → ``@keyframes`` → ``@media`` rules.
    Truncated to ``max_chars`` by dropping from the least-critical end
    (``@media`` first, then keyframes), never mid-rule.
    """
    soup = BeautifulSoup(section_html or "", "lxml")
    sec_tokens = _section_tokens(soup)

    base_rules: List[Rule] = []
    media_rules: List[Rule] = []
    for rule in index.rules:
        applied = [s for s in rule.selectors if _selector_applies(s, soup, sec_tokens)]
        if not applied:
            continue
        kept = Rule(selectors=applied, body=rule.body, order=rule.order, media=rule.media)
        (media_rules if rule.media else base_rules).append(kept)

    if not base_rules and not media_rules:
        return ""

    # Keyframes referenced by any matched rule.
    used_kf: List[str] = []
    for r in base_rules + media_rules:
        for name in _used_keyframe_names(r.body, index.keyframes):
            if name not in used_kf:
                used_kf.append(name)

    # Variables referenced by any matched rule (and their var() chains).
    seed_vars: List[str] = []
    for r in base_rules + media_rules:
        for v in _used_var_names(r.body):
            if v not in seed_vars:
                seed_vars.append(v)
    used_vars = _resolve_variables(seed_vars, index.variables)

    # Assemble in cascade order.
    var_block = ""
    if used_vars:
        decls = " ".join(f"{v['name']}: {v['value']};" for v in used_vars)
        var_block = f":root {{ {decls} }}"

    base_block = "\n".join(_render_rule(r) for r in base_rules)
    kf_block = "\n".join(f"@keyframes {name} {{ {index.keyframes[name]} }}" for name in used_kf)

    media_groups: Dict[str, List[Rule]] = {}
    for r in media_rules:
        media_groups.setdefault(r.media, []).append(r)
    media_chunks = []
    for cond, rules in media_groups.items():
        inner = "\n".join(_render_rule(r) for r in rules)
        media_chunks.append(f"@media {cond} {{\n{inner}\n}}")
    media_block = "\n".join(media_chunks)

    # Budget: keep the most critical first (vars + base rules); drop @media,
    # then keyframes, from the end. Never split a rule mid-body.
    parts = [p for p in (var_block, base_block, kf_block, media_block) if p]
    css = "\n".join(parts)
    if len(css) <= max_chars:
        return css
    out, total = [], 0
    for p in parts:
        if total + len(p) + 1 > max_chars:
            break
        out.append(p)
        total += len(p) + 1
    return "\n".join(out)[:max_chars]


def attach_css_rules(sections: List[Dict], css_json: Dict, max_chars: int = 30000) -> List[Dict]:
    """Attach a ``css_rules`` string to each section, in place.

    Builds the page CSS index once, then matches each section's own ``full_html``
    against it. Sections with no matching CSS get ``""``. Returns ``sections``.
    """
    index = build_index(css_json)
    for sec in sections:
        sec["css_rules"] = match_section_css(sec.get("full_html", ""), index, max_chars=max_chars)
    return sections
