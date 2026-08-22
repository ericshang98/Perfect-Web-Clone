"""Deterministic acceptance gates for Perfect Web Clone v4 (Layer 4).

Each gate is a pure-Python function that inspects the generated ``dist/`` (or a
component tree) and returns a JSON-serializable dict with an ``ok`` key plus
evidence. No gate calls an LLM and no gate is judged by vibes — they are the
hard contract that "clean + lightweight + fingerprint-free" is enforced by.
"""
