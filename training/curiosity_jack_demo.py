"""Демо: CharacterCuriosityEngine на 'Дом который построил Джек'."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import CoreApplication
from curriculum.debug_session import DebugSession
from training.jack_run import VERSES
from core.curiosity import CharacterCuriosityEngine
from drivers.narrator_driver import NarratorDriver

W = "\033[0m"; BD = "\033[1m"; DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"; MG = "\033[95m"

app = CoreApplication(config={"mock_teacher": False, "feature_tolerance": 0.15})
app.startup()
session = DebugSession(app)
app.peripherals.get("text").build_vocab(VERSES)

# 200 циклов
for _ in range(200):
    session.run_attention_sentences(VERSES)

session.consolidate(n_steps=200, tolerance_factor=0.6)
session.consolidate_hierarchy(passes=3)

print(f"\n{BD}Gen: {app.system.base.size()}{W}")

engine = CharacterCuriosityEngine(app.system.base)
anchors = engine.find_anchors()
unfamiliar = engine.find_unfamiliar(anchors)
queries = engine.generate_queries(anchors, unfamiliar, max_queries=8)

print(f"\n{BD}АНКОРЫ:{W}")
for a in anchors[:10]:
    flag = f" {AM}[unfamiliar]{W}" if a.is_unfamiliar else ""
    print(f"  {GR}{a.word:<20}{W} sig={AM}{a.significance:.3f}{W}  gen={a.gen_count:>3}{flag}")

print(f"\n{BD}UNFAMILIAR:{W}")
for a in unfamiliar[:5]:
    print(f"  {MG}•{W} {a.word} — {a.gen_count} Gen")

print(f"\n{BD}ЗАПРОСЫ:{W}")
for q in queries[:6]:
    prio = {1: f"{AM}!!{W}", 2: f"{CY}!{W}", 3: f"{DM}.{W}"}.get(q["priority"], "")
    print(f"  {prio} {q['question']}")
    print(f"    {DM}{q['context'][:70]}...{W}")

narrator = NarratorDriver(app.system.base, seed=42)

print(f"\n{BD}ГЕТЕРАРХИЯ «джек»:{W}")
path = narrator.hierarchy_path("джек")
for p in path[:8]:
    indent = "  " * min(p["chain_len"], 5)
    print(f"  {indent}L{p['chain_len']:<2} sig={p['sig']:.2f}  {p['label'][:50]}")

print(f"\n{BD}ВЕТВИ «дом»:{W}")
variants = narrator.branch_variants("дом")
for v in variants[:3]:
    print(f"  {v['parent'][:40]} → {[c['label'][:25] for c in v['variants']]}")
