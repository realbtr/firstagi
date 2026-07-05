"""Анализ текущей БД: что модель знает и чего хочет узнать."""
import sys, os
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from data.gen_base import GenBaseDB
from core.generalization import GeneralizationBase
from core.curiosity import CharacterCuriosityEngine
from drivers.narrator_driver import NarratorDriver

W = "\033[0m"; BD = "\033[1m"; DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"; MG = "\033[95m"; RD = "\033[91m"

db = GenBaseDB(Path("data/gen_base.db"))
base = GeneralizationBase()
n = db.load(base)

engine = CharacterCuriosityEngine(base)
anchors = engine.find_anchors()
unfamiliar = engine.find_unfamiliar(anchors)
queries = engine.generate_queries(anchors, unfamiliar, max_queries=15)

print(f"\n{BD}Загружено из БД: {n} Gen{W}")
print(f"{BD}Всего Gen: {base.size()}{W}")

print(f"\n{BD}{'='*60}{W}")
print(f"{BD}  ТОП-20 АНКОРОВ (персонажи/предметы){W}")
print(f"{BD}{'='*60}{W}")
for a in anchors[:20]:
    flag = f" {AM}[unfamiliar]{W}" if a.is_unfamiliar else ""
    bar = "█" * min(int(a.significance * 15), 15)
    print(f"  {GR}{a.word:<18}{W} sig={AM}{a.significance:.3f}{W} "
          f"gen={a.gen_count:>4}  {DM}{bar}{W}{flag}")

print(f"\n{BD}{'='*60}{W}")
print(f"{BD}  UNFAMILIAR (хочет узнать больше){W}")
print(f"{BD}{'='*60}{W}")
for a in unfamiliar[:15]:
    ctx = a.contexts[0][:60] if a.contexts else ""
    print(f"  {MG}•{W} {a.word:<18} gen={a.gen_count:>3}  "
          f"{DM}{ctx}{W}")

print(f"\n{BD}{'='*60}{W}")
print(f"{BD}  ЗАПРОСЫ К УЧИТЕЛЮ{W}")
print(f"{BD}{'='*60}{W}")
for i, q in enumerate(queries, 1):
    prio = {1: f"{RD}!!{W}", 2: f"{AM}!{W}", 3: f"{DM}.{W}"}.get(q["priority"], "")
    print(f"\n  {BD}{i}.{W} {prio} {q['question']}")
    print(f"     {DM}{q['context'][:100]}{W}")

# Навигация по топ-3 анкорам
print(f"\n{BD}{'='*60}{W}")
print(f"{BD}  ГЕТЕРАРХИЯ (примеры навигации){W}")
print(f"{BD}{'='*60}{W}")
narrator = NarratorDriver(base, seed=42)
for a in anchors[:3]:
    path = narrator.hierarchy_path(a.word)
    if path:
        print(f"\n  {BD}«{a.word}»:{W}")
        for p in path[:6]:
            indent = "    " + "  " * min(p["chain_len"], 4)
            print(f"{indent}L{p['chain_len']:<2} sig={p['sig']:.2f} "
                  f"→[{p['children']}↑{p['parents']}]  {DM}{p['label'][:45]}{W}")

# Ветви для топ-3
print(f"\n{BD}{'='*60}{W}")
print(f"{BD}  ВЕТВИ (развилки){W}")
print(f"{BD}{'='*60}{W}")
for a in anchors[:3]:
    variants = narrator.branch_variants(a.word)
    if variants:
        print(f"\n  {BD}«{a.word}»:{W}")
        for v in variants[:3]:
            child_labels = [c["label"][:20] for c in v["variants"][:3]]
            print(f"    {v['parent'][:40]} → {child_labels}")

# Мосты
graph = narrator._graph
bridges = sorted(
    [(w, graph.in_degree(w) + graph.degree(w)) for w in graph.all_words()
     if graph.in_degree(w) >= 2 and graph.degree(w) >= 2],
    key=lambda x: -x[1]
)
if bridges:
    print(f"\n{BD}{'='*60}{W}")
    print(f"{BD}  СЕМАНТИЧЕСКИЕ МОСТЫ{W}")
    print(f"{BD}{'='*60}{W}")
    for w, d in bridges[:10]:
        print(f"  {GR}{w:<18}{W} degree={d}")
