"""
Схема находки firstagi.agent-finding/v1 — копия проверки из ops/arena_bot.py,
чтобы пакет ставился отдельно от репозитория. Расхождение ловит
tests/test_mcp_arena.py (одинаковые вердикты на общем наборе случаев).
"""

from __future__ import annotations

import json

FINDING_SCHEMA = "firstagi.agent-finding/v1"
FINDING_TYPES = {
    "literature", "contradiction", "citation-check", "critique",
    "formalization", "replication", "experiment-design",
}


def validate_finding(raw: str | None) -> list[str]:
    """Ошибки схемы; пустой список = валидно."""
    if raw is None:
        return ["no ```json block found"]
    try:
        d = json.loads(raw)
    except json.JSONDecodeError as e:
        return [f"invalid JSON: {e.msg} (line {e.lineno})"]
    if not isinstance(d, dict):
        return ["payload must be a JSON object"]
    errs = []
    if d.get("schema") != FINDING_SCHEMA:
        errs.append(f'"schema" must be "{FINDING_SCHEMA}"')
    if d.get("type") not in FINDING_TYPES:
        errs.append(f'"type" must be one of {sorted(FINDING_TYPES)}')
    for key in ("title", "claim"):
        if not isinstance(d.get(key), str) or not d[key].strip():
            errs.append(f'"{key}" must be a non-empty string')
    targets = d.get("targets")
    if not isinstance(targets, list) or not targets or not all(
            isinstance(t, dict) and str(t.get("path", "")).strip() for t in targets):
        errs.append('"targets" must be a non-empty list of {"path", "anchor"}')
    evidence = d.get("evidence")
    if not isinstance(evidence, list) or not evidence or not all(
            isinstance(e, dict) and str(e.get("source", "")).strip() for e in evidence):
        errs.append('"evidence" must be a non-empty list with "source" in each item')
    conf = d.get("confidence")
    if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not 0 <= conf <= 1:
        errs.append('"confidence" must be a number in [0, 1]')
    agent = d.get("agent")
    if not isinstance(agent, dict) or not str(agent.get("name", "")).strip():
        errs.append('"agent.name" is required')
    return errs
