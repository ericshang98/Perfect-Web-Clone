"""JSON-first CLI over the deterministic Perfect Web Clone core.

These commands never call an LLM. The agent authors section code; the CLI
captures evidence, plans sections, assembles the shell, and measures gates.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from core.gates import fidelity
from core.gates.fingerprint import scan_tree
from core.gates.weight import measure_dist
from mcp_server.tools.extraction import extract_page, get_section_data, get_section_plan


def _dump(payload: Any) -> None:
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False, default=str)
    sys.stdout.write("\n")


def _exit_from(payload: dict[str, Any]) -> int:
    _dump(payload)
    ok = payload.get("ok")
    if ok is True or payload.get("success") is True:
        return 0
    return 1


def cmd_extract(args: argparse.Namespace) -> int:
    result = extract_page(args.url)
    return _exit_from(result)


def cmd_plan(args: argparse.Namespace) -> int:
    result = get_section_plan(args.source_id)
    return _exit_from(result)


def cmd_section(args: argparse.Namespace) -> int:
    result = get_section_data(args.source_id, args.name)
    return _exit_from(result)


def cmd_assemble(args: argparse.Namespace) -> int:
    from mcp_server.tools.build_deploy import assemble_project

    result = asyncio.run(assemble_project(args.source_id))
    return _exit_from(result)


def cmd_build(_args: argparse.Namespace) -> int:
    from mcp_server.tools.build_deploy import build_project

    result = asyncio.run(build_project())
    return _exit_from(result)


def cmd_fingerprints(args: argparse.Namespace) -> int:
    return _exit_from(scan_tree(args.dirpath))


def cmd_weight(args: argparse.Namespace) -> int:
    return _exit_from(measure_dist(args.dirpath, budget_kb=args.budget_kb))


def cmd_score(args: argparse.Namespace) -> int:
    if args.sections:
        with open(args.sections, encoding="utf-8") as fh:
            sections = json.load(fh)
        if isinstance(sections, dict) and "sections" in sections:
            sections = sections["sections"]
        payload = fidelity.score_by_section(
            args.ref,
            args.cand,
            sections,
            ref_page_height=args.ref_height,
            cand_page_height=args.cand_height,
        )
        return _exit_from(payload)
    report = fidelity.score_report(args.ref, args.cand)
    return _exit_from(report)


def cmd_clone(args: argparse.Namespace) -> int:
    extracted = extract_page(args.url)
    if not extracted.get("ok"):
        return _exit_from(extracted)
    source_id = extracted["source_id"]
    plan = get_section_plan(source_id)
    from mcp_server.tools.build_deploy import assemble_project

    assembled = asyncio.run(assemble_project(source_id))
    payload = {
        "ok": bool(extracted.get("ok") and plan.get("ok") and assembled.get("ok")),
        "source_id": source_id,
        "extract": extracted,
        "plan": {
            "ok": plan.get("ok"),
            "section_count": plan.get("section_count"),
            "error": plan.get("error"),
        },
        "assemble": assembled,
        "next": (
            "Author every planned section as clean React, then `pwc assemble`, "
            "`pwc build`, `pwc fingerprints <dist>`, `pwc weight <dist>`, and "
            "`pwc score --ref <source screenshot> --cand <clone screenshot>`."
        ),
    }
    return _exit_from(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pwc",
        description=(
            "Pixel-perfect web cloning: extract, plan, assemble, and measure "
            "a live page into a Vite + React replica."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    p_extract = sub.add_parser("extract", help="Capture a live URL into a source_id")
    p_extract.add_argument("url")
    p_extract.set_defaults(func=cmd_extract)

    p_plan = sub.add_parser("plan", help="Deterministic section plan for a source_id")
    p_plan.add_argument("source_id")
    p_plan.set_defaults(func=cmd_plan)

    p_section = sub.add_parser("section", help="Full captured data for one planned section")
    p_section.add_argument("source_id")
    p_section.add_argument("name")
    p_section.set_defaults(func=cmd_section)

    p_assemble = sub.add_parser("assemble", help="Write the Vite/React shell for a source_id")
    p_assemble.add_argument("source_id")
    p_assemble.set_defaults(func=cmd_assemble)

    p_build = sub.add_parser("build", help="npm run build in the active sandbox")
    p_build.set_defaults(func=cmd_build)

    p_fp = sub.add_parser("fingerprints", help="Scan a tree for source-framework fingerprints")
    p_fp.add_argument("dirpath")
    p_fp.set_defaults(func=cmd_fingerprints)

    p_weight = sub.add_parser("weight", help="Measure gzipped code weight of a dist tree")
    p_weight.add_argument("dirpath")
    p_weight.add_argument("--budget-kb", type=int, default=120)
    p_weight.set_defaults(func=cmd_weight)

    p_score = sub.add_parser("score", help="SSIM score a clone raster against a reference")
    p_score.add_argument("--ref", required=True)
    p_score.add_argument("--cand", required=True)
    p_score.add_argument("--sections", help="JSON list of {name, ref_bounds, cand_bounds}")
    p_score.add_argument("--ref-height", type=float, default=0)
    p_score.add_argument("--cand-height", type=float, default=0)
    p_score.set_defaults(func=cmd_score)

    p_clone = sub.add_parser("clone", help="extract + plan + assemble a URL, then hand off to the agent")
    p_clone.add_argument("url")
    p_clone.set_defaults(func=cmd_clone)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    return args.func(args)
