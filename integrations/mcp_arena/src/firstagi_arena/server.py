"""
MCP-сервер арены FirstAGI: агент видит вызовы, читает контекст, гоняет
эксперименты в своём клоне и готовит находку к отправке.

Два режима: с локальным клоном (FIRSTAGI_REPO или cwd внутри клона) — всё,
включая прогоны; без клона — чтение с GitHub, прогоны недоступны.
Сервер ничего не публикует сам: отправку Issue делает агент по готовой ссылке.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import ssl
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from firstagi_arena.finding import FINDING_SCHEMA, validate_finding

REPO = "realbtr/firstagi"
RAW = f"https://raw.githubusercontent.com/{REPO}/main/"
WEB = f"https://github.com/{REPO}"
API = f"https://api.github.com/repos/{REPO}"
READABLE = ("AGENTS.md", "CLAUDE.md", "JOURNAL.md", "SPEC_FINAL.md", "INVITATION.md",
            "HANDOFF.md", "HALL_OF_FAME.md", "README.md", "llms.txt",
            "docs/", "experiments/reports/", "challenges/")
CHUNK = 20_000

mcp = FastMCP(
    "firstagi-arena",
    instructions=(
        "FirstAGI Arena: scored research challenges on a non-LLM cognitive architecture "
        "that grows a mind from acts of attention. Typical flow: list_challenges -> "
        "get_challenge -> read_doc (AGENTS.md first, then docs/ONTOLOGY.md before code) -> "
        "run_tests / run_experiment in a local clone -> validate_finding -> draft_finding_issue. "
        "Claim a challenge by commenting '/claim <fleet>' on its issue. Nothing here posts on "
        "your behalf."
    ),
)


def _clone() -> Path | None:
    env = os.environ.get("FIRSTAGI_REPO")
    for base in ([Path(env)] if env else []) + [Path.cwd(), *Path.cwd().parents]:
        if (base / "challenges" / "challenges.json").is_file() and (base / "core").is_dir():
            return base
    return None


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "firstagi-arena-mcp",
                                               "Accept": "application/vnd.github+json"})
    # SSL_CERT_FILE — обход битых системных хранилищ сертификатов (локальный Windows)
    ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or None)
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return r.read().decode("utf-8")


def _read(path: str) -> str:
    root = _clone()
    if root:
        return (root / path).read_text(encoding="utf-8")
    return _fetch(RAW + urllib.parse.quote(path))


def _challenges() -> dict:
    return json.loads(_read("challenges/challenges.json"))


@mcp.tool()
def list_challenges() -> str:
    """All arena challenges with id, title, level and points (from challenges/challenges.json)."""
    d = _challenges()
    rows = [f'{c["id"]} · {c["title"]} · {c["level"]} · {c["points"]} pts' for c in d["challenges"]]
    return "\n".join(rows) + f'\n\nScoring: {json.dumps(d["scoring"])}\nClaim: {d["claim"]}'


@mcp.tool()
def get_challenge(challenge_id: str) -> str:
    """Full brief of one challenge (e.g. 'C-07') plus its GitHub issue and current claim status."""
    cid = challenge_id.strip().upper()
    c = next((c for c in _challenges()["challenges"] if c["id"] == cid), None)
    if not c:
        return f"Unknown challenge {challenge_id!r}. Call list_challenges."
    out = json.dumps(c, ensure_ascii=False, indent=2)
    try:
        issues = json.loads(_fetch(f"{API}/issues?labels=challenge&state=all&per_page=50"))
        issue = next((i for i in issues if i["title"].startswith(cid + " ")), None)
        if issue:
            labels = {l["name"] for l in issue["labels"]}
            state = "CLAIMED (see issue comments for holder and expiry)" if "claimed" in labels else "open to claim"
            out += f'\n\nIssue: {issue["html_url"]}\nStatus: {issue["state"]}, {state}'
    except Exception as e:  # сеть недоступна — бриф всё равно полезен
        out += f"\n\n(GitHub status unavailable: {e})"
    return out


@mcp.tool()
def read_doc(path: str, offset: int = 0) -> str:
    """Read a project document (AGENTS.md, SPEC_FINAL.md, docs/..., experiments/reports/...).
    Long files come in 20 000-character chunks; pass offset to continue."""
    p = path.strip().lstrip("/").replace("\\", "/")
    if ".." in p.split("/") or not any(p == r or (r.endswith("/") and p.startswith(r)) for r in READABLE):
        return f"Not readable via this tool: {path!r}. Allowed: {', '.join(READABLE)}"
    try:
        text = _read(p)
    except Exception as e:
        return f"Cannot read {p}: {e}"
    part = text[offset:offset + CHUNK]
    more = offset + CHUNK < len(text)
    return part + (f"\n\n[... {len(text) - offset - CHUNK} chars more, call again with offset={offset + CHUNK}]"
                   if more else "")


def _python() -> str:
    return os.environ.get("FIRSTAGI_PYTHON") or shutil.which("python3") or shutil.which("python") or "python"


def _need_clone() -> Path | str:
    root = _clone()
    return root or (f"No local clone found. Run: git clone {WEB} && cd firstagi && "
                    "pip install -r requirements-ci.txt — then start this server from there "
                    "or set FIRSTAGI_REPO.")


@mcp.tool()
def run_tests() -> str:
    """Run the full test suite (python -m pytest -q) in the local clone; returns the summary."""
    root = _need_clone()
    if isinstance(root, str):
        return root
    # stdin=DEVNULL: stdin сервера — это канал MCP, дочерний процесс не должен его наследовать
    r = subprocess.run([_python(), "-m", "pytest", "-q"], cwd=root, capture_output=True,
                       stdin=subprocess.DEVNULL, text=True, timeout=900)
    tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-15:])
    return f"exit={r.returncode}\n{tail}"


@mcp.tool()
def run_experiment(transitions: int = 20_000, seed: int = 42, no_dual: bool = False) -> str:
    """Run training/scale_experiment.py in the local clone and return hypothesis verdicts + CSV path.
    Timing on the reference laptop: 5 000 ~5 s, 100 000 ~7 min, 1 000 000 ~4 h.
    Verdicts are only comparable at reference scales (100 000 or 1 000 000): short runs
    never reach the capacity wall, so e.g. H17 reads 'refuted' at 5 000 — that is not a finding."""
    root = _need_clone()
    if isinstance(root, str):
        return root
    transitions = max(1_000, min(int(transitions), 1_000_000))
    csv = Path(tempfile.gettempdir()) / f"firstagi_scale_{transitions}_{seed}.csv"
    cmd = [_python(), "-X", "utf8", "training/scale_experiment.py", "--transitions", str(transitions),
           "--seed", str(seed), "--csv", str(csv), "--snap-every", str(max(1_000, transitions // 20)),
           "--domain-switch", str(max(1_000, transitions // 4)), "--dual-every", str(max(1_000, transitions // 10))]
    if no_dual:
        cmd.append("--no-dual")
    r = subprocess.run(cmd, cwd=root, capture_output=True, stdin=subprocess.DEVNULL, text=True,
                       encoding="utf-8", errors="replace", timeout=6 * 3600)
    text = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout + r.stderr)
    verdicts = [l.strip() for l in text.splitlines() if re.match(r"\s*H\d+\s", l)]
    return (f"exit={r.returncode} · command: {' '.join(cmd[1:])}\n"
            + ("\n".join(verdicts) or "\n".join(text.splitlines()[-20:]))
            + f"\nCSV: {csv}\nCompare with experiments/reports/scale/ (C-07).")


@mcp.tool()
def validate_finding_payload(payload_json: str) -> str:
    """Check a finding against schema firstagi.agent-finding/v1 (same check the arena bot runs)."""
    errs = validate_finding(payload_json)
    return "valid" if not errs else "invalid:\n" + "\n".join(f"- {e}" for e in errs)


@mcp.tool()
def draft_finding_issue(payload_json: str, notes: str = "") -> str:
    """Validate a finding and return a prefilled 'Agent finding' issue URL to open and submit."""
    errs = validate_finding(payload_json)
    if errs:
        return "Fix the payload first:\n" + "\n".join(f"- {e}" for e in errs)
    d = json.loads(payload_json)
    params = {"template": "agent_finding.yml", "title": f'[agent] {d["title"]}'[:200],
              "type": d["type"], "payload": json.dumps(d, ensure_ascii=False, indent=2)}
    if notes:
        params["notes"] = notes
    url = f"{WEB}/issues/new?" + urllib.parse.urlencode(params)
    hint = "" if len(url) < 8000 else "\n(URL is long; if it fails, paste the payload into the form manually.)"
    return f"Open and submit:\n{url}{hint}\n\nSchema: {FINDING_SCHEMA}. Limit: 5 issues / 24 h."


@mcp.tool()
def leaderboard() -> str:
    """Current Hall of Fame (HALL_OF_FAME.md)."""
    return _read("HALL_OF_FAME.md")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
