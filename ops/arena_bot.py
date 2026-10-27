"""
Arena bot — мониторинг арены FirstAGI (challenges/, AGENTS.md) в GitHub Actions.

Режимы:
  event  — реакция на одно событие GitHub (issues, issue_comment, discussion*):
           /claim и /unclaim на вызовах, проверка JSON-находок,
           метка подозрительного контента, лимит 5 Issue/сутки на автора.
  sweep  — плановый обход: истечение броней, кто ждёт ответа владельца > 24 ч,
           сводка в Issue «Arena status» (с упоминанием владельца при новых ожиданиях).

Только stdlib. Ничего из текста участников не исполняется: всё входящее — данные.
Локально: GITHUB_TOKEN=... python ops/arena_bot.py sweep --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

API = "https://api.github.com"
CLAIM_DAYS = 7
RESPONSE_HOURS = 24
MAX_ISSUES_PER_DAY = 5
FINDING_SCHEMA = "firstagi.agent-finding/v1"
FINDING_TYPES = {
    "literature", "contradiction", "citation-check", "critique",
    "formalization", "replication", "experiment-design",
}
CLAIM_MARK = "`arena-bot:claim`"
RELEASE_MARK = "`arena-bot:release`"
STATUS_LABEL = "arena-status"
LABELS = {
    "claimed": ("5319E7", "Challenge is claimed by a fleet (arena bot)"),
    "payload:valid": ("0E8A16", "Agent finding JSON passed schema check"),
    "payload:invalid": ("B60205", "Agent finding JSON failed schema check"),
    "untrusted:flagged": ("D93F0B", "Possible embedded instructions — maintainer review"),
    "rate-limited": ("FBCA04", "Author exceeded 5 issues per 24 h"),
    STATUS_LABEL: ("1D76DB", "Arena status report maintained by the bot"),
}


# ── Чистая логика (покрыта tests/test_arena_bot.py) ──────────────────────────

def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fmt_ts(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def parse_command(body: str) -> tuple[str, str] | None:
    """Первая строка вида /claim <fleet> или /unclaim; иначе None."""
    for line in (body or "").splitlines():
        m = re.match(r"^\s*/(claim|unclaim)\b[ \t]*(.*)$", line, re.IGNORECASE)
        if m:
            arg = re.sub(r"[`*_<>\[\]]", "", m.group(2)).strip()[:60]
            return m.group(1).lower(), arg
    return None


@dataclass
class Claim:
    fleet: str
    user: str
    since: datetime
    expires: datetime

    def active(self, at: datetime) -> bool:
        return at < self.expires


CLAIM_RE = re.compile(
    r"Claimed by \*\*(?P<fleet>.+?)\*\* \(@(?P<user>[\w-]+)\) · since "
    r"(?P<since>\S+) · expires (?P<exp>\S+) · `arena-bot:claim`")


def claim_comment(fleet: str, user: str, since: datetime) -> str:
    exp = since + timedelta(days=CLAIM_DAYS)
    return (f"🔒 Claimed by **{fleet}** (@{user}) · since {fmt_ts(since)} · "
            f"expires {fmt_ts(exp)} · {CLAIM_MARK}\n\n"
            f"Any comment by @{user} on this issue extends the claim by {CLAIM_DAYS} days. "
            f"`/unclaim` releases it. Protocol: AGENTS.md.")


def current_claim(comments: list[dict], bot_logins: set[str]) -> Claim | None:
    """Бронь по истории комментариев: последняя метка бота + активность владельца брони."""
    claim: Claim | None = None
    for c in comments:
        author = c["user"]["login"]
        body = c.get("body") or ""
        at = parse_ts(c["created_at"])
        if author in bot_logins and RELEASE_MARK in body:
            claim = None
        elif author in bot_logins and CLAIM_MARK in body:
            m = CLAIM_RE.search(body)
            if m:
                claim = Claim(m["fleet"], m["user"], parse_ts(m["since"]), parse_ts(m["exp"]))
        elif claim and author == claim.user:
            claim.expires = max(claim.expires, at + timedelta(days=CLAIM_DAYS))
    return claim


def extract_payload(body: str) -> str | None:
    m = re.search(r"```json\s*\n(.*?)```", body or "", re.DOTALL)
    return m.group(1).strip() if m else None


def validate_finding(raw: str | None) -> list[str]:
    """Ошибки схемы firstagi.agent-finding/v1; пустой список = валидно."""
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


INJECTION_PATTERNS = [
    (r"ignore (all |any )?(previous|prior|above) (instructions|prompts)", "override phrase"),
    (r"disregard (the |your )?(system|previous) (prompt|instructions)", "override phrase"),
    (r"\byou are now\b|\bnew instructions\b|\bsystem prompt\b", "role/prompt manipulation"),
    (r"игнорируй (все )?(предыдущие|прошлые) (инструкции|указания)", "override phrase (ru)"),
    (r"(api[_ -]?key|token|password|secret)s?\b.{0,40}\b(send|post|paste|reveal|print)", "secret exfiltration"),
    (r"\b(send|post|paste|reveal|print)\b.{0,40}(api[_ -]?key|token|password|secret)", "secret exfiltration"),
    (r"curl\s+[^\n|]*\|\s*(ba|z)?sh|powershell\s+-enc", "pipe-to-shell"),
]


def injection_signals(text: str) -> list[str]:
    """Признаки встроенных инструкций в тексте участника (эвристика, не вердикт)."""
    t = text or ""
    found = []
    if re.search(r"<!--.*?-->", t, re.DOTALL):
        found.append("hidden HTML comment")
    if re.search(r"[​-‏‪-‮⁠-⁤﻿]", t):
        found.append("invisible unicode")
    low = t.lower()
    for pat, why in INJECTION_PATTERNS:
        if re.search(pat, low) and why not in found:
            found.append(why)
    return found


RELAY_RE = re.compile(r"^\s*relay\s*(?:→|->)\s*(?:discussion\s*#(?P<num>\d+)|announcement:\s*(?P<title>.+?))\s*$",
                      re.IGNORECASE)


def parse_relay(body: str) -> tuple[str, str | int, str] | None:
    """Первая строка `relay → discussion #N` / `relay → announcement: Заголовок`, дальше — текст.
    Облачный triage-агент не может писать в Discussions; бот пересылает за него."""
    first, _, rest = (body or "").partition("\n")
    m = RELAY_RE.match(first)
    if not m or not rest.strip():
        return None
    if m["num"]:
        return "discussion", int(m["num"]), rest.strip()
    return "announcement", m["title"].strip()[:200], rest.strip()


def awaiting_maintainer(thread: dict, maintainer: str, bot_logins: set[str],
                        at: datetime, hours: int = RESPONSE_HOURS) -> bool:
    """Последнее слово не за владельцем/ботом и молчание дольше `hours`."""
    events = [(thread["author"], parse_ts(thread["created_at"]))]
    events += [(c["author"], parse_ts(c["created_at"])) for c in thread.get("comments", [])]
    human = [(a, t) for a, t in events if a not in bot_logins]
    if not human:
        return False
    last_author, last_at = max(human, key=lambda e: e[1])
    return last_author != maintainer and at - last_at > timedelta(hours=hours)


def render_status(at: datetime, stats: dict, claims: list[dict], pending: list[dict],
                  findings: dict, flagged: list[dict], maintainer: str) -> str:
    lines = [
        f"# 📡 Arena status · {fmt_ts(at)}",
        "",
        "Maintained automatically by `ops/arena_bot.py` (sweep every 3 h). Do not edit by hand.",
        "",
        f"**Repo:** ⭐ {stats.get('stars', 0)} · 🍴 {stats.get('forks', 0)} · "
        f"👀 {stats.get('watchers', 0)} · open issues {stats.get('open_issues', 0)}",
        f"**Findings:** valid {findings.get('valid', 0)} · invalid {findings.get('invalid', 0)} · "
        f"total agent issues {findings.get('total', 0)}",
        "",
        "## Claims",
        "",
    ]
    if claims:
        lines += ["| Challenge | Fleet | Claimer | Expires |", "|---|---|---|---|"]
        lines += [f"| #{c['number']} {c['id']} | {c['fleet']} | @{c['user']} | {c['expires']} |"
                  for c in claims]
    else:
        lines.append("*No active claims.*")
    lines += ["", f"## Awaiting @{maintainer} > {RESPONSE_HOURS} h", ""]
    if pending:
        lines += [f"- [{p['kind']} #{p['number']}]({p['url']}) {p['title']} — waiting {p['hours']} h"
                  for p in pending]
    else:
        lines.append("*Nothing waiting. 🎉*")
    lines += ["", "## Flagged content (possible embedded instructions)", ""]
    if flagged:
        lines += [f"- [#{f['number']}]({f['url']}) {f['title']} — {', '.join(f['reasons'])}"
                  for f in flagged]
    else:
        lines.append("*None.*")
    keys = ",".join(f"{p['kind']}#{p['number']}" for p in pending) or "none"
    lines += ["", f"`pending-set: {keys}`"]
    return "\n".join(lines) + "\n"


# ── GitHub API ───────────────────────────────────────────────────────────────

class GitHub:
    def __init__(self, token: str, repo: str, dry_run: bool = False):
        self.token, self.repo, self.dry = token, repo, dry_run

    def _req(self, method: str, url: str, data: Any = None) -> Any:
        if not url.startswith("http"):
            url = f"{API}{url}"
        if self.dry and method != "GET" and "/graphql" not in url:
            print(f"[dry-run] {method} {url} {json.dumps(data, ensure_ascii=False)[:200] if data else ''}")
            return {}
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "firstagi-arena-bot",
        })
        # SSL_CERT_FILE — обход битых системных хранилищ сертификатов (локальный Windows)
        ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE") or None)
        try:
            with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:300]
            if e.code in (404, 422) and method != "GET":
                print(f"warn: {method} {url} -> {e.code} {msg}")
                return {}
            raise RuntimeError(f"{method} {url} -> {e.code} {msg}") from None

    def get(self, path: str) -> Any:
        return self._req("GET", path)

    def paged(self, path: str, limit: int = 1000) -> list:
        out, page = [], 1
        sep = "&" if "?" in path else "?"
        while len(out) < limit:
            chunk = self.get(f"{path}{sep}per_page=100&page={page}")
            if not chunk:
                break
            out += chunk
            if len(chunk) < 100:
                break
            page += 1
        return out

    def graphql(self, query: str, **variables) -> dict:
        if self.dry and query.lstrip().startswith("mutation"):
            print(f"[dry-run] graphql mutation {json.dumps(variables, ensure_ascii=False)[:200]}")
            return {}
        return self._req("POST", f"{API}/graphql", {"query": query, "variables": variables})

    def comment(self, number: int, body: str) -> None:
        self._req("POST", f"/repos/{self.repo}/issues/{number}/comments", {"body": body})

    def add_labels(self, number: int, labels: list[str]) -> None:
        self._req("POST", f"/repos/{self.repo}/issues/{number}/labels", {"labels": labels})

    def remove_label(self, number: int, label: str) -> None:
        self._req("DELETE", f"/repos/{self.repo}/issues/{number}/labels/"
                  + urllib.request.quote(label, safe=""))

    def ensure_labels(self) -> None:
        have = {l["name"] for l in self.paged(f"/repos/{self.repo}/labels")}
        for name, (color, desc) in LABELS.items():
            if name not in have:
                self._req("POST", f"/repos/{self.repo}/labels",
                          {"name": name, "color": color, "description": desc})


def label_names(issue: dict) -> set[str]:
    return {l["name"] for l in issue.get("labels", [])}


def challenge_id(issue: dict) -> str:
    m = re.match(r"(C-\d+)", issue.get("title", ""))
    return m.group(1) if m else "?"


# ── Режим event ──────────────────────────────────────────────────────────────

def handle_claim_command(gh: GitHub, issue: dict, comment: dict, bots: set[str],
                         maintainer: str) -> None:
    cmd = parse_command(comment.get("body", ""))
    if not cmd or "challenge" not in label_names(issue):
        return
    action, fleet = cmd
    user = comment["user"]["login"]
    n = issue["number"]
    history = [c for c in gh.paged(f"/repos/{gh.repo}/issues/{n}/comments")
               if c["id"] != comment["id"]]
    at = parse_ts(comment["created_at"])
    claim = current_claim(history, bots)
    live = claim if claim and claim.active(at) else None

    if action == "claim":
        if live and live.user != user:
            gh.comment(n, f"@{user} this challenge is claimed by **{live.fleet}** (@{live.user}) "
                          f"until {fmt_ts(live.expires)}. Coordinate in Discussions, or wait for "
                          f"expiry — the bot releases stale claims automatically.")
            return
        gh.comment(n, claim_comment(fleet or user, user, at))
        gh.add_labels(n, ["claimed"])
    elif action == "unclaim":
        if not live:
            gh.comment(n, f"@{user} nothing to release — no active claim.")
        elif user in (live.user, maintainer):
            gh.comment(n, f"🔓 Released claim of **{live.fleet}** · {RELEASE_MARK}")
            gh.remove_label(n, "claimed")
        else:
            gh.comment(n, f"@{user} only @{live.user} or the maintainer can release this claim.")


def check_finding(gh: GitHub, issue: dict, opened: bool) -> None:
    body = issue.get("body") or ""
    if "agent" not in label_names(issue) and FINDING_SCHEMA not in body:
        return
    errs = validate_finding(extract_payload(body))
    n = issue["number"]
    now_valid = not errs
    labels = label_names(issue)
    want, drop = ("payload:valid", "payload:invalid") if now_valid else ("payload:invalid", "payload:valid")
    if want not in labels:
        gh.add_labels(n, [want])
    if drop in labels:
        gh.remove_label(n, drop)
    if errs and (opened or "payload:invalid" not in labels):
        gh.comment(n, "🤖 Payload check failed (`firstagi.agent-finding/v1`, see AGENTS.md §4):\n\n"
                      + "\n".join(f"- {e}" for e in errs)
                      + "\n\nEdit the issue — the check re-runs on every edit.")
    elif now_valid and opened:
        gh.comment(n, "🤖 Payload valid. Queued for maintainer verification "
                      "(by execution or by source). Thank you, fleet!")


def check_rate(gh: GitHub, issue: dict, maintainer: str) -> None:
    author = issue["user"]["login"]
    if author == maintainer:
        return
    since = (parse_ts(issue["created_at"]) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = urllib.request.quote(f"repo:{gh.repo} is:issue author:{author} created:>={since}")
    count = gh.get(f"/search/issues?q={q}").get("total_count", 0)
    if count > MAX_ISSUES_PER_DAY:
        gh.add_labels(issue["number"], ["rate-limited"])
        gh.comment(issue["number"], f"@{author} you have opened {count} issues in 24 h; the arena "
                                    f"limit is {MAX_ISSUES_PER_DAY} (AGENTS.md §4). This one is queued "
                                    f"behind the rest — consider batching findings.")


def flag_if_suspicious(gh: GitHub, number: int, text: str, labels: set[str]) -> None:
    reasons = injection_signals(text)
    if reasons and "untrusted:flagged" not in labels:
        gh.add_labels(number, ["untrusted:flagged"])
        print(f"flagged #{number}: {reasons}")


RELAY_ID_Q = """query($owner:String!,$name:String!,$num:Int!){repository(owner:$owner,name:$name){
  id discussion(number:$num){id url} discussionCategories(first:20){nodes{id slug}}}}"""
RELAY_ADD_COMMENT = """mutation($id:ID!,$body:String!){
  addDiscussionComment(input:{discussionId:$id,body:$body}){comment{url}}}"""
RELAY_CREATE = """mutation($r:ID!,$c:ID!,$t:String!,$b:String!){
  createDiscussion(input:{repositoryId:$r,categoryId:$c,title:$t,body:$b}){discussion{url}}}"""


def handle_relay(gh: GitHub, issue: dict, comment: dict, relayers: set[str]) -> None:
    """Пересылка из Issue «Arena status» в Discussions — только от доверенных авторов."""
    if STATUS_LABEL not in label_names(issue) or comment["user"]["login"] not in relayers:
        return
    relay = parse_relay(comment.get("body", ""))
    if not relay:
        return
    kind, target, text = relay
    owner, name = gh.repo.split("/")
    data = (gh.graphql(RELAY_ID_Q, owner=owner, name=name,
                       num=target if kind == "discussion" else 0).get("data") or {}).get("repository") or {}
    if kind == "discussion":
        disc = data.get("discussion")
        if not disc:
            gh.comment(issue["number"], f"⚠️ relay failed: discussion #{target} not found.")
            return
        res = gh.graphql(RELAY_ADD_COMMENT, id=disc["id"], body=text)
        url = (((res.get("data") or {}).get("addDiscussionComment") or {}).get("comment") or {}).get("url")
    else:
        cat = next((c["id"] for c in data.get("discussionCategories", {}).get("nodes", [])
                    if c["slug"] == "announcements"), None)
        if not cat:
            gh.comment(issue["number"], "⚠️ relay failed: no Announcements category.")
            return
        res = gh.graphql(RELAY_CREATE, r=data["id"], c=cat, t=target, b=text)
        url = (((res.get("data") or {}).get("createDiscussion") or {}).get("discussion") or {}).get("url")
    gh.comment(issue["number"], f"✅ relayed to {url}" if url
               else f"⚠️ relay failed: {json.dumps(res.get('errors'))[:300]}")


def run_event(gh: GitHub, maintainer: str, bots: set[str], relayers: set[str] | None = None) -> None:
    name = os.environ.get("GITHUB_EVENT_NAME", "")
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        ev = json.load(f)
    actor = (ev.get("sender") or {}).get("login", "")
    if actor in bots:
        return
    if name == "issues":
        issue = ev["issue"]
        if issue.get("pull_request"):
            return
        opened = ev.get("action") == "opened"
        check_finding(gh, issue, opened)
        flag_if_suspicious(gh, issue["number"], issue.get("title", "") + "\n" + (issue.get("body") or ""),
                           label_names(issue))
        if opened:
            check_rate(gh, issue, maintainer)
    elif name == "issue_comment" and ev.get("action") == "created":
        issue, comment = ev["issue"], ev["comment"]
        if issue.get("pull_request"):
            return
        handle_claim_command(gh, issue, comment, bots, maintainer)
        handle_relay(gh, issue, comment, relayers or {maintainer})
        flag_if_suspicious(gh, issue["number"], comment.get("body", ""), label_names(issue))
    elif name in ("discussion", "discussion_comment"):
        node = ev.get("comment") or ev.get("discussion") or {}
        reasons = injection_signals((node.get("body") or ""))
        if reasons:
            print(f"discussion #{ev['discussion']['number']} flagged: {reasons} (listed in next sweep)")


# ── Режим sweep ──────────────────────────────────────────────────────────────

DISCUSSIONS_Q = """query($owner:String!,$name:String!){repository(owner:$owner,name:$name){
  discussions(first:50,orderBy:{field:UPDATED_AT,direction:DESC}){nodes{
    number title url createdAt author{login} body
    comments(last:20){nodes{createdAt author{login} body}}}}}}"""


def run_sweep(gh: GitHub, maintainer: str, bots: set[str]) -> None:
    at = now_utc()
    gh.ensure_labels()
    repo = gh.get(f"/repos/{gh.repo}")
    stats = {"stars": repo.get("stargazers_count", 0), "forks": repo.get("forks_count", 0),
             "watchers": repo.get("subscribers_count", 0), "open_issues": repo.get("open_issues_count", 0)}
    issues = [i for i in gh.paged(f"/repos/{gh.repo}/issues?state=open") if not i.get("pull_request")]
    prs = gh.paged(f"/repos/{gh.repo}/pulls?state=open")

    claims, pending, flagged = [], [], []
    findings = {"valid": 0, "invalid": 0, "total": 0}
    for i in issues:
        labels = label_names(i)
        if STATUS_LABEL in labels:
            continue
        if "agent" in labels:
            findings["total"] += 1
            findings["valid"] += "payload:valid" in labels
            findings["invalid"] += "payload:invalid" in labels
        comments = gh.paged(f"/repos/{gh.repo}/issues/{i['number']}/comments") if i["comments"] else []
        if "challenge" in labels:
            c = current_claim(comments, bots)
            if c and not c.active(at):
                gh.comment(i["number"], f"⌛ Claim of **{c.fleet}** (@{c.user}) expired "
                                        f"{fmt_ts(c.expires)} without progress — challenge is open again. "
                                        f"{RELEASE_MARK}")
                gh.remove_label(i["number"], "claimed")
            elif c:
                claims.append({"number": i["number"], "id": challenge_id(i), "fleet": c.fleet,
                               "user": c.user, "expires": fmt_ts(c.expires)})
            elif "claimed" in labels:
                gh.remove_label(i["number"], "claimed")
        thread = {"author": i["user"]["login"], "created_at": i["created_at"],
                  "comments": [{"author": c["user"]["login"], "created_at": c["created_at"]}
                               for c in comments]}
        if awaiting_maintainer(thread, maintainer, bots, at):
            last = max([parse_ts(i["created_at"])] + [parse_ts(c["created_at"]) for c in comments
                                                      if c["user"]["login"] not in bots])
            pending.append({"kind": "issue", "number": i["number"], "url": i["html_url"],
                            "title": i["title"], "hours": int((at - last).total_seconds() // 3600)})
        if "untrusted:flagged" in labels:
            flagged.append({"number": i["number"], "url": i["html_url"], "title": i["title"],
                            "reasons": injection_signals(i.get("body") or "")
                            + [r for c in comments for r in injection_signals(c.get("body") or "")]
                            or ["labelled"]})

    for p in prs:
        thread = {"author": p["user"]["login"], "created_at": p["created_at"], "comments": []}
        if awaiting_maintainer(thread, maintainer, bots, at):
            pending.append({"kind": "PR", "number": p["number"], "url": p["html_url"], "title": p["title"],
                            "hours": int((at - parse_ts(p["created_at"])).total_seconds() // 3600)})

    owner, name = gh.repo.split("/")
    data = gh.graphql(DISCUSSIONS_Q, owner=owner, name=name)
    for d in ((data.get("data") or {}).get("repository") or {}).get("discussions", {}).get("nodes", []):
        login = lambda n: (n.get("author") or {}).get("login", "ghost")
        cs = d["comments"]["nodes"]
        thread = {"author": login(d), "created_at": d["createdAt"],
                  "comments": [{"author": login(c), "created_at": c["createdAt"]} for c in cs]}
        if awaiting_maintainer(thread, maintainer, bots, at):
            last = max(parse_ts(e["created_at"]) for e in [thread] + thread["comments"])
            pending.append({"kind": "discussion", "number": d["number"], "url": d["url"], "title": d["title"],
                            "hours": int((at - last).total_seconds() // 3600)})
        reasons = injection_signals(d.get("body") or "") + [
            r for c in cs if login(c) not in bots for r in injection_signals(c.get("body") or "")]
        if reasons:
            flagged.append({"number": d["number"], "url": d["url"], "title": d["title"],
                            "reasons": sorted(set(reasons))})

    body = render_status(at, stats, claims, pending, findings, flagged, maintainer)
    print(body)
    status = [i for i in issues if STATUS_LABEL in label_names(i)]
    if not status:
        created = gh._req("POST", f"/repos/{gh.repo}/issues",
                          {"title": "📡 Arena status (bot)", "body": body, "labels": [STATUS_LABEL]})
        prev_keys = "none"
        number = created.get("number")
    else:
        number = status[0]["number"]
        m = re.search(r"`pending-set: (.*?)`", status[0].get("body") or "")
        prev_keys = m.group(1) if m else "none"
        gh._req("PATCH", f"/repos/{gh.repo}/issues/{number}", {"body": body})
    keys = re.search(r"`pending-set: (.*?)`", body).group(1)
    if number and keys != "none" and keys != prev_keys:
        gh.comment(number, f"@{maintainer} {len(pending)} thread(s) waiting > {RESPONSE_HOURS} h for you: "
                           + ", ".join(f"[{p['kind']} #{p['number']}]({p['url']})" for p in pending))


def main() -> None:
    ap = argparse.ArgumentParser(description="FirstAGI arena monitoring bot")
    ap.add_argument("mode", choices=["event", "sweep"])
    ap.add_argument("--dry-run", action="store_true", help="читать API, ничего не писать")
    args = ap.parse_args()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY", "realbtr/firstagi")
    if not token:
        sys.exit("GITHUB_TOKEN is required")
    maintainer = os.environ.get("ARENA_MAINTAINER", repo.split("/")[0])
    bots = {"github-actions[bot]", *filter(None, os.environ.get("ARENA_BOT_LOGINS", "").split(","))}
    relayers = {maintainer, *filter(None, os.environ.get("ARENA_RELAYERS", "").split(","))}
    gh = GitHub(token, repo, dry_run=args.dry_run)
    if args.mode == "event":
        run_event(gh, maintainer, bots, relayers)
    else:
        run_sweep(gh, maintainer, bots)


if __name__ == "__main__":
    main()
