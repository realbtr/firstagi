"""
«Дом, который построил Джек» — 1000 циклов.

Стихотворение Маршака идеально для теста:
  • Рекурсивная кумулятивная структура — каждый стих наращивает цепочку.
  • Фиксированный якорь «построил джек» — должен стать сильнейшим аттрактором.
  • Повторяющиеся переходы на всех уровнях — HierarchicalConsolidator
    обязан найти мета-Gen на каждом уровне рекурсии.

Запуск: py -X utf8 training/jack_run.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.app import CoreApplication
from curriculum.debug_session import DebugSession
from core.learning import HierarchicalConsolidator

# ── Цвета ─────────────────────────────────────────────────────────────
W  = "\033[0m";  CY = "\033[96m"; GR = "\033[92m"; AM = "\033[93m"
RD = "\033[91m"; DM = "\033[90m"; PU = "\033[95m"; BL = "\033[94m"
BD = "\033[1m"

# ── Стихотворение ──────────────────────────────────────────────────────
VERSES = [
    "вот дом который построил джек",

    "вот пшеница которая в тёмном чулане хранится "
    "в доме который построил джек",

    "вот синица которая часто ворует пшеницу "
    "которая в тёмном чулане хранится "
    "в доме который построил джек",

    "вот кошка которая пугает и ловит синицу "
    "которая часто ворует пшеницу "
    "которая в тёмном чулане хранится "
    "в доме который построил джек",

    "вот пёс без хвоста который за шиворот треплет кошку "
    "которая пугает и ловит синицу "
    "которая часто ворует пшеницу "
    "которая в тёмном чулане хранится "
    "в доме который построил джек",

    "вот корова безрогая которая бодает пса без хвоста "
    "который за шиворот треплет кошку "
    "которая пугает и ловит синицу "
    "которая часто ворует пшеницу "
    "которая в тёмном чулане хранится "
    "в доме который построил джек",

    "вот старушка суровая которая доит корову безрогую "
    "которая бодает пса без хвоста "
    "который за шиворот треплет кошку "
    "которая пугает и ловит синицу "
    "которая часто ворует пшеницу "
    "которая в тёмном чулане хранится "
    "в доме который построил джек",

    "вот ленивый и толстый пастух который бранит старушку "
    "которая доит корову безрогую "
    "которая бодает пса без хвоста "
    "который за шиворот треплет кошку "
    "которая пугает и ловит синицу "
    "которая часто ворует пшеницу "
    "которая в тёмном чулане хранится "
    "в доме который построил джек",
]

N_VERSES  = len(VERSES)          # 8 стихов
ITERS     = 125                   # 125 × 8 = 1000 циклов
CONSOL_EVERY = 25                 # консолидация каждые N итераций


def hdr(t):
    print(f"\n{BD}{CY}{'═'*64}{W}\n{BD}{CY}  {t}{W}\n{BD}{CY}{'═'*64}{W}")

def bar(v, w=20):
    return "█" * int(v * w)

def snap(session, label=""):
    s = session.inspect()["stats"]
    r = session.inspect().get("resource", {})
    lbl = f"  {AM}── {label} ──{W}\n" if label else ""
    print(f"{lbl}"
          f"  {DM}Gen:{W} {BD}{s['base_size']:>5}{W}  "
          f"{DM}Признаков:{W} {BD}{s['features']:>3}{W}  "
          f"{DM}Шагов:{W} {BD}{s['steps']:>6}{W}  "
          f"{DM}Readiness:{W} {BD}{session.readiness():.3f}{W}")


def show_meta(session, n=10):
    all_gens = session.app.system.base.all()
    meta = sorted(
        [g for g in all_gens if g.label and (
            g.label.startswith("meta_") or g.label.startswith("fork_"))],
        key=lambda g: g.significance, reverse=True,
    )
    if not meta:
        print(f"  {DM}Мета-Gen: пусто{W}")
        return
    for g in meta[:n]:
        chain_len = len(g.feature_chain)
        b = bar(g.significance)
        print(f"  {GR}{g.gen_id[:8]}{W}  "
              f"sig={AM}{g.significance:.3f}{W}  "
              f"L{BD}{chain_len}{W}  "
              f"{DM}{b}{W}  "
              f"{PU}{g.label}{W}")


def do_consolidation(session, n_steps, label):
    print(f"  {DM}→ консолидация памяти ({n_steps} шагов)…{W}")
    res = session.consolidate(n_steps=n_steps, tolerance_factor=0.6)
    mr  = res["match_rate"]
    col = GR if mr > 0.5 else (AM if mr > 0.2 else DM)
    print(f"    replay  ✓{res['confirmed']}  ✗{res['refuted']}  "
          f"match={col}{mr:.2f}{W}")

    h = session.consolidate_hierarchy(passes=3)
    fc = GR if h["meta_created"] > 0 else DM
    fs = AM if h["meta_strengthened"] > 0 else DM
    print(f"    hier    forks={h['forks_found']}  "
          f"{fc}+{h['meta_created']} мета{W}  "
          f"{fs}~{h['meta_strengthened']} усилено{W}  "
          f"total={h['total_gen']}")


# ══════════════════════════════════════════════════════════════════════

def main():
    hdr("FirstAGI · «Дом который построил Джек» · 1000 циклов")

    app = CoreApplication(config={
        "mock_teacher":      False,
        "feature_tolerance": 0.15,   # тонкое разрешение — поэзия точна
    })
    app.startup()
    session = DebugSession(app)

    # Словарь по всему стихотворению (одна система координат)
    app.peripherals.get("text").build_vocab(VERSES)

    print(f"\n  {DM}Стихов:{W} {BD}{N_VERSES}{W}  "
          f"{DM}Итераций:{W} {BD}{ITERS}{W}  "
          f"{DM}Итого циклов:{W} {BD}{ITERS * N_VERSES}{W}")
    snap(session, "Старт")

    # ── 1000 циклов ────────────────────────────────────────────────────
    total_conf = total_ref = total_steps = 0

    for it in range(1, ITERS + 1):
        results = session.run_attention_sentences(VERSES)
        for sent in results:
            for s in sent:
                if s["outcome"] == "CONFIRMED":  total_conf  += 1
                elif s["outcome"] == "REFUTED":  total_ref   += 1
                total_steps += 1

        # Прогресс каждые 10 итераций
        if it % 10 == 0 or it == 1:
            cycle = it * N_VERSES
            mr    = total_conf / max(total_steps, 1)
            col   = GR if mr > 0.7 else (AM if mr > 0.4 else RD)
            st    = session.inspect()["stats"]
            print(f"  iter {BD}{it:>3}{W}/{ITERS}  "
                  f"цикл={BD}{cycle:>5}{W}  "
                  f"Gen={BD}{st['base_size']:>4}{W}  "
                  f"match={col}{mr:.3f}{W}  "
                  f"✓{total_conf}  ✗{total_ref}")

        # Консолидация каждые CONSOL_EVERY итераций
        if it % CONSOL_EVERY == 0:
            do_consolidation(session, n_steps=N_VERSES * 5, label=f"iter {it}")

    # ── Финальная консолидация ─────────────────────────────────────────
    hdr("Финальная консолидация")
    do_consolidation(session, n_steps=200, label="финал")
    focused = session.focus_weak(n=10)
    print(f"  {DM}focus_weak: {focused} записей активировано{W}")
    do_consolidation(session, n_steps=200, label="после фокуса")

    # ── Финальный срез ────────────────────────────────────────────────
    hdr("Финальный срез")
    snap(session)

    attn = session.attention_stats()
    ms   = session.memory_stats()
    hs   = session.hierarchy_stats()

    print(f"\n  {BD}Итоговые метрики:{W}")
    print(f"  Шагов внимания:      {BD}{attn['steps']}{W}")
    print(f"  Avg match rate:      {BD}{attn['avg_match_rate']:.4f}{W}")
    print(f"  Памяти записей:      {BD}{ms['entries']}{W}  "
          f"replay={DM}{ms['total_replays']}{W}")
    print(f"  Мета-Gen создано:    {BD}{hs['current_meta_count']}{W}  "
          f"avg_sig={AM}{hs['meta_sig_avg']:.3f}{W}")

    print(f"\n  {BD}Топ-12 обобщений:{W}")
    for g in session.top(12):
        b = bar(g["significance"])
        print(f"  {GR}{g['gen_id']}{W}  "
              f"sig={AM}{g['significance']:.3f}{W}  "
              f"L{g['chain_len']:>2}  "
              f"{DM}{b}{W}  "
              f"{PU}{g['label']}{W}")

    print(f"\n  {BD}Мета-Gen / fork-Gen (иерархия):{W}")
    show_meta(session, n=12)

    # Проверка: якорь «построил джек» должен быть самым сильным
    print(f"\n  {BD}Проверка предсказания:{W}")
    tests = [
        ("вот дом который построил джек",
         "якорь — должен знать"),
        ("вот синица которая часто ворует пшеницу",
         "средняя цепочка"),
        ("вот кошка которая пугает",
         "усечённая форма"),
        ("вот пёс без хвоста который за шиворот треплет кошку которая пугает",
         "длинная форма"),
        ("вот дом который построила маша",
         "аномалия — другой строитель"),
        ("построил джек",
         "только якорь"),
    ]
    for text, desc in tests:
        pred = session.predict(text)
        mr   = pred["match_rate"]
        col  = GR if mr > 0.7 else (AM if mr > 0.3 else RD)
        print(f"  {DM}«{text[:55]}»{W}")
        print(f"    {desc:<40}  match={col}{mr:.2f}{W}  "
              f"{DM}{pred['outcomes']}{W}")

    print(f"\n{DM}{'─'*64}{W}")
    print(f"{DM}Завершено. 1000 циклов.{W}\n")


if __name__ == "__main__":
    main()
