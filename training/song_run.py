"""
Шаг 12: Обучение через «детскую песенку».

Демонстрирует превращение Proposal-команд в вопросы:
  модель ожидает признак F → драйвер предлагает {кандидат₁, кандидат₂, ...}
  → модель выбирает → CONFIRMED/REFUTED → обновляет контекст

Запуск: py -X utf8 training/song_run.py
"""

import sys, os
from typing import List
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.app import CoreApplication
from curriculum.debug_session import DebugSession
from curriculum.song_corpus import SongCorpus, SongBlock

# ══════════════════════════════════════════════════════════════════════
# Вывод
# ══════════════════════════════════════════════════════════════════════

W   = "\033[0m"
CY  = "\033[96m"
GR  = "\033[92m"
AM  = "\033[93m"
RD  = "\033[91m"
DM  = "\033[90m"
PU  = "\033[95m"
BLD = "\033[1m"
BL  = "\033[94m"


def hdr(title: str) -> None:
    print(f"\n{BLD}{CY}{'═'*62}{W}")
    print(f"{BLD}{CY}  {title}{W}")
    print(f"{BLD}{CY}{'═'*62}{W}")


def sub(title: str) -> None:
    print(f"\n{AM}── {title} ──{W}")


def fmt_candidates(candidates: list, outcome: str) -> str:
    """Визуализировать альтернативы: [0.12★ 0.34 0.67]"""
    if not candidates:
        return f"{DM}[нет предложений]{W}"
    parts = []
    for i, d in enumerate(candidates):
        if i == 0:
            # Выбранный кандидат
            color = GR if outcome in ("CONFIRMED", "COMPLETED") else RD
            parts.append(f"{color}{d:.3f}★{W}")
        else:
            parts.append(f"{DM}{d:.3f}{W}")
    return f"[{' '.join(parts)}]"


def fmt_outcome(outcome: str) -> str:
    colors = {
        "CONFIRMED":  f"{GR}✓{W}",
        "COMPLETED":  f"{GR}✓✓{W}",
        "REFUTED":    f"{RD}✗{W}",
        "EXPLORING":  f"{AM}?{W}",
        "IDLE":       f"{DM}·{W}",
    }
    return colors.get(outcome, outcome)


def snapshot(session: DebugSession, label: str = "") -> None:
    snap = session.inspect()
    st   = snap["stats"]
    if label:
        sub(label)
    res = st.get("resource", {})
    print(f"  {DM}Gen:       {W}{BLD}{st['base_size']}{W}  "
          f"{DM}Признаков: {W}{BLD}{st['features']}{W}  "
          f"{DM}Шагов: {W}{BLD}{st['steps']}{W}")
    print(f"  {DM}Readiness: {W}{BLD}{snap['readiness']:.3f}{W}  "
          f"{DM}Ресурс: {W}{BLD}{res.get('level', 0):.2f}{W} "
          f"({DM}{res.get('mode', '?')}{W})")


def show_top(session: DebugSession, n: int = 6) -> None:
    for g in session.top(n):
        bar = "█" * int(g["significance"] * 16)
        print(f"  {GR}{g['gen_id']}{W}  "
              f"sig={AM}{g['significance']:.3f}{W}  "
              f"L{g['chain_len']}  "
              f"{DM}{bar}{W}  "
              f"{PU}{g['label']}{W}")


def show_memory(session: DebugSession) -> None:
    ms = session.memory_stats()
    if ms["entries"] == 0:
        print(f"  {DM}Память: пусто{W}")
        return
    print(f"  {DM}Память: {W}{BLD}{ms['entries']}{W} записей  "
          f"слабых={AM}{ms['weak_entries']}{W}  "
          f"avg_sig={DM}{ms['avg_sig']:.3f}{W}  "
          f"записано={DM}{ms['total_recorded']}{W}  "
          f"replay={DM}{ms['total_replays']}{W}")


def show_consolidation(
    session: DebugSession,
    n_steps: int,
    label:   str,
) -> None:
    sub(label)
    result = session.consolidate(n_steps=n_steps, tolerance_factor=0.6)
    mr    = result["match_rate"]
    color = GR if mr > 0.6 else (AM if mr > 0.3 else RD)
    ma    = result["memory_after"]
    print(f"  replay: steps={result['steps']}  "
          f"{GR}✓{result['confirmed']}{W}  "
          f"{RD}✗{result['refuted']}{W}  "
          f"match={color}{mr:.2f}{W}  "
          f"{DM}total_replay={ma['total_replays']}{W}")

    # Иерархическая консолидация — факторизация развилок
    h = session.consolidate_hierarchy(passes=3)
    fc = GR if h["meta_created"] > 0 else DM
    fs = AM if h["meta_strengthened"] > 0 else DM
    print(f"  hier:   forks={h['forks_found']}  "
          f"{fc}+{h['meta_created']} мета-Gen{W}  "
          f"{fs}~{h['meta_strengthened']} усилено{W}  "
          f"{DM}total_gen={h['total_gen']}{W}")


def run_block(
    session: DebugSession,
    corpus:  SongCorpus,
    block:   SongBlock,
    iters:   int,
    verbose: bool = False,
) -> dict:
    """
    Один блок урока (sentence-mode: контекст сбрасывается между текстами).

    verbose=True → показывать каждый шаг с кандидатами (вопросы модели).
    verbose=False → только сводка по итерации.
    """
    info = corpus.block_info()
    meta = info[block.value]
    hdr(f"БЛОК {block.value} — {meta['goal']}")

    all_outcomes: List[str] = []

    for it in range(1, iters + 1):
        texts = corpus.build_lesson(block, iterations=1)

        if verbose:
            print(f"\n  {DM}iter {it} · {len(texts)} предложений{W}")
        else:
            print(f"  {DM}iter {it}{W} ", end="")

        # Sentence-mode: контекст сбрасывается между текстами
        all_sentence_steps = session.run_attention_sentences(texts)
        non_idle: List[dict] = []
        for sent_steps in all_sentence_steps:
            non_idle.extend(s for s in sent_steps if s["outcome"] != "IDLE")

        if verbose:
            for s in non_idle:
                cands = fmt_candidates(s["candidates"], s["outcome"])
                prop  = s["proposal_feature_id"]
                prop_s = f"{prop[:8]}…" if prop else f"{DM}(нет){W}"
                print(f"    {fmt_outcome(s['outcome'])}  "
                      f"ожидал={BL}{prop_s}{W}  "
                      f"альт={cands}")
        else:
            outcomes = [s["outcome"] for s in non_idle]
            conf = outcomes.count("CONFIRMED") + outcomes.count("COMPLETED")
            ref  = outcomes.count("REFUTED")
            expl = outcomes.count("EXPLORING")
            mr   = conf / max(len(outcomes), 1)
            color = GR if mr > 0.5 else (AM if mr > 0.25 else RD)
            print(f"steps={len(non_idle):3d}  "
                  f"{GR}✓{conf}{W}  {RD}✗{ref}{W}  {AM}?{expl}{W}  "
                  f"match={color}{mr:.2f}{W}")

        all_outcomes.extend(s["outcome"] for s in non_idle)

    conf_total = all_outcomes.count("CONFIRMED") + all_outcomes.count("COMPLETED")
    total      = max(len(all_outcomes), 1)
    return {
        "block":       block.value,
        "match_rate":  round(conf_total / total, 4),
        "total_steps": len(all_outcomes),
    }


# ══════════════════════════════════════════════════════════════════════
# Главная функция
# ══════════════════════════════════════════════════════════════════════

def main() -> None:
    corpus = SongCorpus()

    app = CoreApplication(config={
        "mock_teacher":      False,
        "feature_tolerance": 0.18,
    })
    app.startup()
    session = DebugSession(app)

    # Единая система координат для всего корпуса
    all_texts = corpus.all_texts()
    app.peripherals.get("text").build_vocab(all_texts)

    hdr(f"FirstAGI · Детская песенка  ({len(all_texts)} текстов в корпусе)")
    print(f"\n  {DM}Принцип: каждый блок добавляет один новый слот.{W}")
    print(f"  {DM}Смотрим как Proposal → вопрос → ответ → контекст.{W}")
    snapshot(session, "Начальное состояние")

    results = []

    # ── БЛОК А: Якорь ─────────────────────────────────────────────────
    r = run_block(session, corpus, SongBlock.ANCHOR, iters=8)
    results.append(r)
    snapshot(session, f"После блока А  (match={r['match_rate']:.2f})")
    show_top(session, 4)
    show_memory(session)

    # ── КОНСОЛИДАЦИЯ А ────────────────────────────────────────────────
    show_consolidation(session, n_steps=30, label="консолидация А")

    # ── БЛОК Б: Чередование ───────────────────────────────────────────
    print(f"\n  {BLD}Режим VERBOSE: видим вопросы модели{W}")
    r = run_block(session, corpus, SongBlock.ALTERNATE, iters=5, verbose=True)
    results.append(r)
    snapshot(session, f"После блока Б  (match={r['match_rate']:.2f})")
    show_top(session, 4)

    # ── БЛОК В: Расширение ────────────────────────────────────────────
    r = run_block(session, corpus, SongBlock.EXPAND, iters=6)
    results.append(r)
    snapshot(session, f"После блока В  (match={r['match_rate']:.2f})")
    show_top(session, 6)
    show_memory(session)

    # ── КОНСОЛИДАЦИЯ В ────────────────────────────────────────────────
    show_consolidation(session, n_steps=60, label="консолидация В")

    # ── БЛОК Г: Дизамбигуация ─────────────────────────────────────────
    r = run_block(session, corpus, SongBlock.DISAMBIG, iters=5)
    results.append(r)
    snapshot(session, f"После блока Г  (match={r['match_rate']:.2f})")
    show_top(session, 8)
    show_memory(session)

    # ── КОНСОЛИДАЦИЯ Г (фокус на слабых) ──────────────────────────────
    focused = session.focus_weak(n=5)
    print(f"\n  {DM}focus_weak: {focused} записей получили приоритет{W}")
    show_consolidation(session, n_steps=60, label="консолидация Г + фокус")

    # ── БЛОК Д: Полная сцена ──────────────────────────────────────────
    r = run_block(session, corpus, SongBlock.FULL, iters=4)
    results.append(r)
    snapshot(session, f"После блока Д  (match={r['match_rate']:.2f})")
    show_memory(session)

    # ── ФИНАЛЬНАЯ КОНСОЛИДАЦИЯ ────────────────────────────────────────
    show_consolidation(session, n_steps=100, label="финальная консолидация")

    # ── ФИНАЛЬНЫЙ СРЕЗ ────────────────────────────────────────────────
    hdr("ФИНАЛЬНЫЙ СРЕЗ")

    snap = session.inspect()
    st   = snap["stats"]
    attn = session.attention_stats()

    print(f"\n  {BLD}Прогресс по блокам:{W}")
    block_names = {
        "А": "Якорь",
        "Б": "Чередование",
        "В": "Расширение",
        "Г": "Дизамбигуация",
        "Д": "Полная сцена",
    }
    for r in results:
        bar = "█" * int(r["match_rate"] * 20)
        color = GR if r["match_rate"] > 0.6 else (AM if r["match_rate"] > 0.3 else RD)
        name  = block_names.get(r["block"], r["block"])
        print(f"  Блок {r['block']} {name:15s}  "
              f"match={color}{r['match_rate']:.2f}{W}  "
              f"{DM}{bar}{W}")

    print(f"\n  {BLD}Итоговая статистика:{W}")
    print(f"  Gen:                {BLD}{st['base_size']}{W}")
    print(f"  Признаков:          {BLD}{st['features']}{W}")
    print(f"  Шагов движка:       {BLD}{st['steps']}{W}")
    print(f"  Readiness:          {BLD}{snap['readiness']:.3f}{W}")
    print(f"  Шагов внимания:     {BLD}{attn['steps']}{W}")
    print(f"  Avg match rate:     {BLD}{attn['avg_match_rate']:.3f}{W}")

    print(f"\n  {BLD}Топ-10 обобщений:{W}")
    show_top(session, 10)

    # Иерархия мета-Gen
    hs = session.hierarchy_stats()
    print(f"\n  {BLD}Иерархические мета-Gen:{W}")
    print(f"  создано всего={BLD}{hs['current_meta_count']}{W}  "
          f"avg_sig={AM}{hs['meta_sig_avg']:.3f}{W}")
    # Показать мета-Gen отсортированные по значимости
    all_gens = session.app.system.base.all()
    meta_gens = sorted(
        [g for g in all_gens if g.label and g.label.startswith("meta_")],
        key=lambda g: g.significance,
        reverse=True,
    )
    for g in meta_gens[:8]:
        bar = "█" * int(g.significance * 16)
        ch  = len(g.child_ids)
        print(f"  {GR}{g.gen_id[:8]}{W}  "
              f"sig={AM}{g.significance:.3f}{W}  "
              f"L{g.generalization_level}  "
              f"{DM}{bar}{W}  "
              f"ветвей={PU}{ch}{W}  "
              f"{DM}{g.label}{W}")

    # Предсказание — проверяем ситуативное понимание
    print(f"\n  {BLD}Проверка ситуативного понимания:{W}")
    tests = [
        ("кот сидит",              "базовый якорь"),
        ("кот сидит на окне",      "якорь + место"),
        ("утром кот сидит",        "время → предикат"),
        ("утром кот сидит на окне","полная сцена"),
        ("собака бежит",           "параллельный субъект"),
        ("утром собака бежит",     "полная форма — собака"),
        ("утром кот лает",         "аномалия (кот не лает)"),
    ]
    for text, desc in tests:
        pred = session.predict(text)
        mr   = pred["match_rate"]
        color = GR if mr > 0.6 else (AM if mr > 0.3 else RD)
        print(f"  {DM}«{text}»{W}")
        print(f"    {desc:30s}  match={color}{mr:.2f}{W}  "
              f"{DM}{pred['outcomes']}{W}")

    print(f"\n{DM}{'─'*62}{W}")
    print(f"{DM}Сессия завершена.{W}\n")


if __name__ == "__main__":
    main()
