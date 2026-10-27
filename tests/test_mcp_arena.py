"""
Тесты MCP-сервера арены: копия схемы находки совпадает с ботом,
read_doc не выпускает за белый список.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "integrations", "mcp_arena", "src"))

from ops import arena_bot
from firstagi_arena import finding

GOOD = {
    "schema": "firstagi.agent-finding/v1", "type": "replication", "title": "t", "claim": "c",
    "targets": [{"path": "p"}], "evidence": [{"source": "s"}], "confidence": 0.5,
    "agent": {"name": "a"},
}
CASES = [
    None, "{bad", "[]", json.dumps(GOOD),
    json.dumps({**GOOD, "type": "poem"}), json.dumps({**GOOD, "confidence": 2}),
    json.dumps({**GOOD, "confidence": False}), json.dumps({**GOOD, "targets": []}),
    json.dumps({**GOOD, "evidence": [{}]}), json.dumps({**GOOD, "agent": {}}),
    json.dumps({**GOOD, "schema": "v0", "title": " "}),
]


@pytest.mark.parametrize("raw", CASES)
def test_schema_copy_matches_bot(raw):
    assert finding.validate_finding(raw) == arena_bot.validate_finding(raw)


def test_schema_constants_match_bot():
    assert finding.FINDING_TYPES == arena_bot.FINDING_TYPES
    assert finding.FINDING_SCHEMA == arena_bot.FINDING_SCHEMA


class TestServerTools:
    @pytest.fixture(autouse=True)
    def _server(self, monkeypatch):
        pytest.importorskip("mcp")
        monkeypatch.setenv("FIRSTAGI_REPO", ROOT)
        from firstagi_arena import server
        self.s = server

    def test_read_doc_whitelist(self):
        assert self.s.read_doc("AGENTS.md").startswith("# AGENTS.md")
        for bad in (".secrets/keys.env.example", "../x", "docs/../core/learning.py", "core/learning.py"):
            assert self.s.read_doc(bad).startswith("Not readable")

    def test_list_challenges_from_clone(self):
        out = self.s.list_challenges()
        assert "C-01" in out and "500 pts" in out

    def test_draft_requires_valid_payload(self):
        assert self.s.draft_finding_issue("{}").startswith("Fix the payload")
        url = self.s.draft_finding_issue(json.dumps(GOOD))
        assert "template=agent_finding.yml" in url and "type=replication" in url
