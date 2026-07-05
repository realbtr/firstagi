"""
training/fork_demo.py — Демо: Развилки при опровержении (RefutationFork).

Показывает:
  1. Как «Дом который построил Джек» строит дерево развилок
  2. Как Parent Gen конкурирует с дочерними
  3. Как MR растёт при повторном чтении

Запуск:
    py -X utf8 training/fork_demo.py
"""
from __future__ import annotations

import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.app import CoreApplication
from core.refutation_fork import RefutationForkEngine
from drivers.text_driver import TextDriver

# ── ANSI ──────────────────────────────────────────────────────────────
W  = "\033[0m";  BD = "\033[1m";  DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
RD = "\033[91m"; MG = "\033[95m"

def hdr(t: str) -> None:
    print(f"\n{BD}{CY}{'═'*68}{W}")
    print(f"{BD}{CY}  {t}{W}")
    print(f"{BD}{CY}{'═'*68}{W}\n")


# ══════════════════════════════════════════════════════════════════════
# Корпус: минисериалы с развилками
# ══════════════════════════════════════════════════════════════════════

# Строка 1: «дом который построил Джек»
LINE_1 = "вот дом который построил Джек"

# Строка 2: «пшеница которая в тёмном чулане хранится в доме который построил Джек»
LINE_2 = "вот пшеница которая хранится в доме"

# Строка 3: «кошка которая пугает мышь которая крадёт пшеницу»
LINE_3_A = "вот кошка которая пугает мышь"
LINE_3_B = "вот кошка которая играет с мышью"

# Строка 4: «собака которая гонится за кошкой»
LINE_4_A = "вот собака которая гонится за кошкой"
LINE_4_B = "вот собака которая дружит с кошкой"

# Строка 5: «волк который спасает зайца»
LINE_5_A = "вот волк который спасает зайца"
LINE_5_B = "вот волк который встречает зайца"

# Строка 6: «медведь который несёт мёд»
LINE_6_A = "вот медведь который несёт мёд"
LINE_6_B = "вот медведь который ищет мёд"


def build_tree_fork_demo():
    """Построение дерева развилок на кумулятивном корпусе."""

    app = CoreApplication(config={
        "mock_teacher": True,
        "feature_tolerance": 0.15,
    })
    app.startup()

    fork_engine = app.system.engine.refutation_fork
    d = TextDriver("demo")

    # ── Фаза 1: Линейное обучение (один путь) ───────────────────────
    hdr("Фаза 1: Линейное обучение (один путь)")

    lines = [LINE_1, LINE_2, LINE_3_A]
    for line in lines:
        print(f"  {BD}Рассказываем:{W} «{line}»")
        for tok in d.produce(line):
            result = app.system.process_token(tok)
        app.system.reset_context()

    base_size = len(app.system.base.all())
    fork_count = fork_engine.fork_count
    print(f"\n  Gen: {base_size}  Развилок: {fork_count}")

    # ── Фаза 2: Второй путь (создаёт развилку) ──────────────────────
    hdr("Фаза 2: Второй путь (создаёт развилку)")

    print(f"  {BD}Рассказываем:{W} «{LINE_3_B}» (отличается от «пугает мышь»)")
    print(f"  {DM}Ожидаем: REFUTED на «играет» → развилка в гетерархии{W}\n")

    for tok in d.produce(LINE_3_B):
        result = app.system.process_token(tok)
        outcome = result.outcome.name
        label = getattr(result.token, "label", "?") or "?"

        if outcome == "REFUTED":
            fork_info = ""
            if result.new_gen_id:
                # Проверяем, создана ли развилка
                new_gen = app.system.base.get(result.new_gen_id)
                if new_gen and new_gen.parent_ids:
                    parent_id = new_gen.parent_ids[0]
                    parent = app.system.base.get(parent_id)
                    if parent:
                        fork_info = (
                            f" → Fork! parent={parent_id[:8]} "
                            f"(L{len(parent.feature_chain)})"
                        )
            print(f"  {RD}REFUTED{W} «{label}»{fork_info}")
        elif outcome == "CONFIRMED":
            print(f"  {GR}CONFIRMED{W} «{label}»")
        elif outcome == "COMPLETED":
            print(f"  {AM}COMPLETED{W} «{label}»")

    app.system.reset_context()

    base_size = len(app.system.base.all())
    fork_count = fork_engine.fork_count
    print(f"\n  Gen: {base_size}  Развилок: {fork_count}")

    # ── Фаза 3: Третий путь (дополнительные развилки) ────────────────
    hdr("Фаза 3: Третий путь (ещё развилки)")

    lines_3 = [LINE_4_A, LINE_5_A, LINE_6_A]
    lines_4 = [LINE_4_B, LINE_5_B, LINE_6_B]

    print(f"  {BD}Путь A:{W}")
    for line in lines_3:
        print(f"    «{line}»")
        for tok in d.produce(line):
            result = app.system.process_token(tok)
        app.system.reset_context()

    print(f"\n  {BD}Путь B:{W}")
    for line in lines_4:
        print(f"    «{line}»")
        for tok in d.produce(line):
            result = app.system.process_token(tok)
            if result.outcome.name == "REFUTED":
                new_gen = app.system.base.get(result.new_gen_id) if result.new_gen_id else None
                fork_note = ""
                if new_gen and new_gen.parent_ids:
                    fork_note = f" → Fork!"
                print(f"      {RD}REFUTED{W}{fork_note}")
        app.system.reset_context()

    base_size = len(app.system.base.all())
    fork_count = fork_engine.fork_count
    print(f"\n  Gen: {base_size}  Развилок: {fork_count}")

    # ── Фаза 4: Анализ дерева развилок ───────────────────────────────
    hdr("Фаза 4: Анализ дерева развилок")

    all_gens = app.system.base.all()

    # Найти Gen с детьми (это узлы-развилки)
    branching_gens = [g for g in all_gens if g.child_ids]
    leaf_gens = [g for g in all_gens if not g.child_ids and g.parent_ids]
    root_gens = [g for g in all_gens if not g.parent_ids and g.child_ids]

    print(f"  {BD}Структура дерева:{W}")
    print(f"    Всего Gen:        {len(all_gens)}")
    print(f"    Корневых (root):  {len(root_gens)}")
    print(f"    Ветвящихся:       {len(branching_gens)}")
    print(f"    Листовых:         {len(leaf_gens)}")

    if branching_gens:
        print(f"\n  {BD}Узлы-развилки:{W}")
        for g in branching_gens[:10]:
            children = [app.system.base.get(cid).gen_id[:8] if app.system.base.get(cid) else "?"
                        for cid in g.child_ids[:3]]
            print(f"    {g.gen_id[:8]}  L{len(g.feature_chain)}  "
                  f"sig={g.significance:.2f}  "
                  f"→ [{', '.join(children)}]  "
                  f"{MG}{g.label}{W}")

    if leaf_gens:
        print(f"\n  {BD}Листовые Gen (конкретные варианты):{W}")
        for g in leaf_gens[:10]:
            parent = app.system.base.get(g.parent_ids[0]) if g.parent_ids else None
            parent_label = parent.label if parent else "?"
            print(f"    {g.gen_id[:8]}  L{len(g.feature_chain)}  "
                  f"sig={g.significance:.2f}  "
                  f"parent={parent_label[:30] if parent_label else '?'}  "
                  f"{MG}{g.label}{W}")

    # ── Фаза 5: Повторный прогон (MR растёт) ────────────────────────
    hdr("Фаза 5: Повторный прогон")

    test_lines = [LINE_3_A, LINE_3_B, LINE_4_A, LINE_4_B]
    for line in test_lines:
        n_confirmed = 0
        n_refuted = 0
        for tok in d.produce(line):
            result = app.system.process_token(tok)
            if result.outcome.name == "CONFIRMED":
                n_confirmed += 1
            elif result.outcome.name == "REFUTED":
                n_refuted += 1
        app.system.reset_context()

        total = n_confirmed + n_refuted
        mr = n_confirmed / total if total > 0 else 0
        color = GR if mr > 0.7 else (AM if mr > 0.5 else RD)
        print(f"  {line[:40]:<42} {color}MR={mr:.2f}{W}  "
              f"✓{n_confirmed} ✗{n_refuted}")

    # ── Итог ────────────────────────────────────────────────────────
    hdr("Итог")
    print(f"  {BD}RefutationFork:{W}")
    print(f"    Всего развилок: {fork_engine.fork_count}")
    print(f"    Отслежено признаков: {fork_engine.stats()['tracked_features']}")
    print(f"\n  {BD}Принцип:{W}")
    print(f"    REFUTED ≠ «ошибка»")
    print(f"    REFUTED = «развилка» → Parent Gen предсказывает: A или B")
    print(f"    Parent конкурирует с другими Gen на том же уровне")
    print(f"\n{DM}{'─'*68}{W}")
    print(f"{DM}Дерево развилок построено. Гетерархия растёт через бифуркации.{W}\n")


if __name__ == "__main__":
    build_tree_fork_demo()
