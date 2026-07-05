"""
Демо: SmartTextDriver в активном режиме — что модель ожидает и что удивляет.

Сценарий:
  1. Обучение на 5 ситуациях через TextDriver (baseline).
  2. Прогон тех же текстов через SmartTextDriver:
       • без кандидатов (passive): probe stats = структурный сюрприз
       • с кандидатами из базы Gen (active): насколько Gen-знание сокращает пробы
  3. Новые ситуации:
       • карта слов (тепловая карта: много проб = сюрприз)
       • корреляция probe count ↔ StepOutcome (CONFIRMED / REFUTED)
       • ContextQuery / GAP — с аннотацией «структурного сюрприза»
  4. Топ Gen из SmartTextDriver vs TextDriver:
       • как обогащённые метки (|p=N|role=theme/rheme) влияют на выявленные паттерны

Запуск:
    py -X utf8 training/smart_driver_demo.py
    py -X utf8 training/smart_driver_demo.py --passes 10 --verbose
    py -X utf8 training/smart_driver_demo.py --test всё
"""

from __future__ import annotations

import sys, os, argparse, math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.app import CoreApplication
from core.algorithm import StepOutcome
from drivers.text_driver import TextDriver
from drivers.smart_text_driver import SmartTextDriver, CandidateSet, ProbeStats
from training.serial_corpus import SITUATION_FAMILIES

TRAIN_SITUATIONS = ["встреча", "угощение", "игра", "помощь", "праздник"]
TEST_SITUATIONS  = ["опасность", "поиск", "спор", "потеря", "возвращение"]

# ── ANSI ──────────────────────────────────────────────────────────────────────
W  = "\033[0m";  BD = "\033[1m";  DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
RD = "\033[91m"; MG = "\033[95m"; BL = "\033[94m"

OUTCOME_COLOR = {
    StepOutcome.CONFIRMED     : GR,
    StepOutcome.COMPLETED     : GR + BD,
    StepOutcome.REFUTED       : RD,
    StepOutcome.EXPLORING     : AM,
    StepOutcome.CYCLE_AVOIDED : DM,
}
OUTCOME_SYM = {
    StepOutcome.CONFIRMED     : "✓",
    StepOutcome.COMPLETED     : "★",
    StepOutcome.REFUTED       : "✗",
    StepOutcome.EXPLORING     : "?",
    StepOutcome.CYCLE_AVOIDED : "~",
}

def hdr(t: str) -> None:
    print(f"\n{BD}{CY}{'═'*70}{W}")
    print(f"{BD}{CY}  {t}{W}")
    print(f"{BD}{CY}{'═'*70}{W}\n")

def sub(t: str) -> None:
    print(f"\n{BD}{BL}  ── {t} ──{W}\n")

def bar(value: float, maxv: float = 5.0, width: int = 8) -> str:
    """Текстовый бар: value/maxv × width блоков."""
    blocks = int(round(value / maxv * width)) if maxv > 0 else 0
    return "█" * blocks + "░" * (width - blocks)


# ══════════════════════════════════════════════════════════════════════════════
# Структуры для хранения результатов
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class WordRecord:
    """Запись о слове в тексте: структурный и семантический сюрприз."""
    word: str
    outcome: str
    probe_count: int            # число символьных проб
    was_predicted: bool         # было ли в кандидатах от Gen-базы
    role: str                   # theme / rheme
    entropy_saved: float


@dataclass
class TextRecord:
    """Результат прогона одного текста."""
    text: str
    situation: str
    words: List[WordRecord]

    @property
    def match_rate(self) -> float:
        conf = sum(1 for w in self.words
                   if w.outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED))
        return conf / len(self.words) if self.words else 0.0

    @property
    def avg_probes(self) -> float:
        return sum(w.probe_count for w in self.words) / len(self.words) if self.words else 0.0

    @property
    def predicted_rate(self) -> float:
        return sum(1 for w in self.words if w.was_predicted) / len(self.words) if self.words else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Шаг 1: Обучение (TextDriver, как baseline)
# ══════════════════════════════════════════════════════════════════════════════

def train_baseline(app, texts: List[str], n_passes: int = 10) -> None:
    """Обучение через обычный TextDriver."""
    drv = TextDriver("train_td")
    for p in range(1, n_passes + 1):
        n_new = 0
        for t in texts:
            for tok in drv.produce(t):
                r = app.system.process_token(tok)
                if r.new_gen_id:
                    n_new += 1
            app.system.reset_context()
        if p in (1, n_passes // 2, n_passes):
            bs = len(app.system.base.all())
            print(f"  Pass {p:2d}: base={bs:4d}  n_new={n_new}")


# ══════════════════════════════════════════════════════════════════════════════
# Получение кандидатов из Gen-базы
# ══════════════════════════════════════════════════════════════════════════════

def get_gen_vocab(app, max_chain: int = 2) -> List[str]:
    """
    Извлечь словарь из базы Gen:
    берём labels всех Gen с chain_len ≤ max_chain (LONG_TERM + MEDIUM низкие).
    Это «слова, которые модель знает».
    """
    labels = []
    for g in app.system.base.all():
        if len(g.feature_chain) <= max_chain and g.label:
            # label может быть составным: «кот·сидит» → берём последний токен
            parts = g.label.split("·")
            word = parts[-1].strip()
            # Убрать метаданные SmartTextDriver если они там есть
            if "|" in word:
                word = word.split("|")[0]
            if word:
                labels.append(word)
    return list(set(labels))


def get_active_context_labels(app) -> List[str]:
    """
    Извлечь labels Gen, которые сейчас активны в контексте.
    Это «чего система ждёт прямо сейчас».
    """
    labels = []
    for gen_id in app.system.engine.context.active_gen_ids():
        gen = app.system.base.get(gen_id)
        if gen and gen.label:
            parts = gen.label.split("·")
            word = parts[-1].strip()
            if "|" in word:
                word = word.split("|")[0]
            if word:
                labels.append(word)
    return list(set(labels))


# ══════════════════════════════════════════════════════════════════════════════
# Шаг 2: Прогон через SmartTextDriver в активном режиме
# ══════════════════════════════════════════════════════════════════════════════

def run_smart(
    app,
    text: str,
    situation: str,
    gen_vocab: List[str],
    verbose: bool = False,
) -> TextRecord:
    """
    Прогнать текст через SmartTextDriver.

    Для каждого слова:
      - кандидаты = gen_vocab (слова из Gen-базы) + активный контекст
      - probe_count = сколько символьных проверок нужно
      - outcome = CONFIRMED/REFUTED/... от Gen-системы
    """
    drv = SmartTextDriver("smart_active", min_entropy=0.5, max_probes=5)
    drv.build_vocab([text] + [t for ts in SITUATION_FAMILIES.values() for t in ts])

    words_raw = text.lower().split()
    words_raw = [w for w in words_raw if w]

    word_records: List[WordRecord] = []

    app.system.reset_context()

    # Проходим попарно: (w_i, w_{i+1}) = один токен
    import re as _re
    import uuid, math as _m
    from core.feature import Feature, RegionCharacteristics
    from core.generalization import PeripheralToken
    from drivers.text_driver import _build_vocab, _word_to_region

    tokenized = [w for w in _re.split(r"[\s,.\-!?;:\"'()]+", text.lower()) if w]
    if len(tokenized) < 2:
        return TextRecord(text=text, situation=situation, words=[])

    # Перестраиваем vocab на всём тексте
    from drivers.text_driver import _build_vocab
    vocab_all = _build_vocab(tokenized)

    # ThemeRheme на всём тексте
    from drivers.smart_text_driver import ThemeRhemeRouter
    router = ThemeRhemeRouter(vocab_all)
    tr_labels = {lbl.word: lbl.role for lbl in router.label_sequence(tokenized)}

    from drivers.smart_text_driver import EntropyMinimizer, CandidateSet
    minimizer = EntropyMinimizer(min_entropy_threshold=0.5, max_probes=5)

    for i in range(len(tokenized) - 1):
        w1, w2 = tokenized[i], tokenized[i + 1]

        # Кандидаты: gen_vocab + активный контекст прямо сейчас
        active_labels = get_active_context_labels(app)
        combined = list(set(gen_vocab + active_labels))
        candidates = CandidateSet(combined)

        # Структурный сюрприз: сколько символьных проб нужно для w2
        probe_stats = minimizer.probe_word(w2, candidates)

        # Генерируем токен (то же, что TextDriver)
        vi1 = vocab_all.get(w1, 0.5)
        vi2 = vocab_all.get(w2, 0.5)
        src = _word_to_region(w1, vi1)
        tgt = _word_to_region(w2, vi2)
        direction = (vi2 - vi1) * _m.pi

        feat = Feature.from_regions(
            feature_id=str(uuid.uuid4()),
            direction=direction,
            distance=1.0,
            source=src,
            target=tgt,
        )
        role = tr_labels.get(w2, "rheme")
        label = f"{w2}|p={probe_stats.probes_used}|h={probe_stats.entropy_saved:.1f}|role={role}"

        token = PeripheralToken.new(
            driver_id="smart_active",
            data=feat,
            label=label,
        )

        # Прогоняем через Gen-систему
        result = app.system.process_token(token)

        wr = WordRecord(
            word=w2,
            outcome=result.outcome,
            probe_count=probe_stats.probes_used,
            was_predicted=probe_stats.was_predicted,
            role=role,
            entropy_saved=probe_stats.entropy_saved,
        )
        word_records.append(wr)

        if verbose:
            oc = result.outcome
            col = OUTCOME_COLOR.get(oc, W)
            sym = OUTCOME_SYM.get(oc, "?")
            pred_sym = GR + "P" + W if wr.was_predicted else DM + "·" + W
            print(
                f"    {col}{sym}{W} {pred_sym} "
                f"[{role[:2]}] «{w2:<12}»  "
                f"probes={probe_stats.probes_used}  "
                f"outcome={oc}"
            )

    return TextRecord(text=text, situation=situation, words=word_records)


# ══════════════════════════════════════════════════════════════════════════════
# Шаг 3: Визуализация
# ══════════════════════════════════════════════════════════════════════════════

def print_word_heatmap(record: TextRecord, max_words: int = 40) -> None:
    """
    Тепловая карта слов: probe_count + outcome + role.

    Легенда:
        [probes]  ✓=CONFIRMED  ✗=REFUTED  ?=EXPLORING  ++=rheme
    """
    print(f"  {DM}«{record.text[:70]}»{W}")
    parts = []
    for wr in record.words[:max_words]:
        col = OUTCOME_COLOR.get(wr.outcome, W)
        sym = OUTCOME_SYM.get(wr.outcome, "?")
        role_mark = "++" if wr.role == "rheme" else ".."
        pred_mark = GR + "»" + W if wr.was_predicted else " "
        p = wr.probe_count
        # Яркость символа = число проб
        probe_color = (RD if p >= 4 else AM if p >= 2 else GR) if p > 0 else DM
        parts.append(
            f"{pred_mark}{probe_color}{p}{W}"
            f"{col}{sym}{W}"
            f"{role_mark}«{wr.word[:8]}»"
        )
    print("  " + "  ".join(parts))


def print_correlation_table(records: List[TextRecord]) -> None:
    """
    Таблица корреляции: outcome × avg_probe_count.

    Если структурный и семантический сюрприз коррелируют →
    SmartTextDriver и Gen-система согласуются.
    """
    from collections import defaultdict
    stats: Dict[str, List[int]] = defaultdict(list)
    for rec in records:
        for wr in rec.words:
            stats[wr.outcome].append(wr.probe_count)

    print(f"  {'Outcome':<14} {'Кол-во':>8} {'Avg probes':>11} {'Bar':>12}  {'Интерпретация'}")
    print(f"  {'─'*14} {'─'*8} {'─'*11} {'─'*12}  {'─'*25}")

    order = [StepOutcome.CONFIRMED, StepOutcome.COMPLETED,
             StepOutcome.REFUTED, StepOutcome.EXPLORING, StepOutcome.CYCLE_AVOIDED]
    all_avgs = []
    for oc in order:
        if oc not in stats:
            continue
        counts = stats[oc]
        avg = sum(counts) / len(counts)
        all_avgs.append(avg)
        col = OUTCOME_COLOR.get(oc, W)
        sym = OUTCOME_SYM.get(oc, "?")
        b = bar(avg, maxv=5.0)
        interp = {
            StepOutcome.CONFIRMED     : "ожидаемо → мало проб?",
            StepOutcome.COMPLETED     : "завершено → мало проб?",
            StepOutcome.REFUTED       : "сюрприз  → много проб?",
            StepOutcome.EXPLORING     : "неизвестно → много проб?",
            StepOutcome.CYCLE_AVOIDED : "цикл пропущен",
        }.get(oc, "")
        print(f"  {col}{sym} {oc:<12}{W}  {len(counts):>8}  {avg:>10.2f}  {b}  {DM}{interp}{W}")

    if len(all_avgs) >= 2:
        conf_avg = (stats.get(StepOutcome.CONFIRMED, [0])
                    + stats.get(StepOutcome.COMPLETED, [0]))
        refu_avg = stats.get(StepOutcome.REFUTED, [0]) + stats.get(StepOutcome.EXPLORING, [0])
        conf_m = sum(conf_avg) / len(conf_avg) if conf_avg else 0
        refu_m = sum(refu_avg) / len(refu_avg) if refu_avg else 0
        delta = refu_m - conf_m
        sig = "↑ KOРРЕЛЯЦИЯ подтверждена" if delta > 0.3 else "~ нет выраженной корреляции"
        col = GR if delta > 0.3 else AM
        print(f"\n  {col}Δ(REFUTED − CONFIRMED) = {delta:+.2f}  {sig}{W}")


def print_theme_rheme_stats(records: List[TextRecord]) -> None:
    """
    Тема vs Рема: где больше сюрпризов?

    Гипотеза: рема несёт новую информацию → больше REFUTED + больше проб.
    """
    theme_outcomes: Dict[str, int] = defaultdict(int)
    rheme_outcomes: Dict[str, int] = defaultdict(int)
    theme_probes, rheme_probes = [], []

    for rec in records:
        for wr in rec.words:
            if wr.role == "theme":
                theme_outcomes[wr.outcome] += 1
                theme_probes.append(wr.probe_count)
            else:
                rheme_outcomes[wr.outcome] += 1
                rheme_probes.append(wr.probe_count)

    def rate(d: Dict, key: str) -> float:
        total = sum(d.values())
        return d.get(key, 0) / total if total else 0.0

    def avg(lst: List[int]) -> float:
        return sum(lst) / len(lst) if lst else 0.0

    th_mr = rate(theme_outcomes, StepOutcome.CONFIRMED) + rate(theme_outcomes, StepOutcome.COMPLETED)
    rh_mr = rate(rheme_outcomes, StepOutcome.CONFIRMED) + rate(rheme_outcomes, StepOutcome.COMPLETED)
    th_rf = rate(theme_outcomes, StepOutcome.REFUTED)
    rh_rf = rate(rheme_outcomes, StepOutcome.REFUTED)

    print(f"  {'Роль':<10} {'Слов':>6} {'MR':>7} {'REFUTED%':>10} {'Avg probes':>11} {'Bar'}")
    print(f"  {'─'*10} {'─'*6} {'─'*7} {'─'*10} {'─'*11} {'─'*8}")
    print(
        f"  {'Тема':<10} {sum(theme_outcomes.values()):>6}  "
        f"{th_mr:>6.3f}  {th_rf:>9.3f}  {avg(theme_probes):>10.2f}  {bar(avg(theme_probes))}"
    )
    print(
        f"  {'Рема':<10} {sum(rheme_outcomes.values()):>6}  "
        f"{rh_mr:>6.3f}  {rh_rf:>9.3f}  {avg(rheme_probes):>10.2f}  {bar(avg(rheme_probes))}"
    )

    if rh_rf > th_rf + 0.05:
        print(f"\n  {GR}Гипотеза подтверждена: рема REFUTED чаще ({rh_rf:.1%} > {th_rf:.1%}){W}")
    else:
        print(f"\n  {AM}Гипотеза не подтверждена: REFUTED одинаков для темы/ремы{W}")

    if avg(rheme_probes) > avg(theme_probes) + 0.3:
        print(f"  {GR}Рема требует больше символьных проб ({avg(rheme_probes):.2f} > {avg(theme_probes):.2f}){W}")
    else:
        print(f"  {AM}Число проб для темы/ремы схожее{W}")


def print_top_surprises(records: List[TextRecord], n: int = 10) -> None:
    """
    Топ-N слов по «суммарному сюрпризу»:
    score = probe_count × (1 if REFUTED else 0.5)
    """
    all_words: List[WordRecord] = [wr for rec in records for wr in rec.words]
    scored = sorted(
        all_words,
        key=lambda w: w.probe_count * (1.5 if w.outcome == StepOutcome.REFUTED else
                                       0.5 if w.outcome in (StepOutcome.CONFIRMED,
                                                            StepOutcome.COMPLETED)
                                       else 1.0),
        reverse=True,
    )
    print(f"  {'Слово':<16} {'Role':<7} {'Probes':>7} {'Outcome':<12} {'Predicted':>10}")
    print(f"  {'─'*16} {'─'*7} {'─'*7} {'─'*12} {'─'*10}")
    seen = set()
    count = 0
    for wr in scored:
        if wr.word in seen:
            continue
        seen.add(wr.word)
        col = OUTCOME_COLOR.get(wr.outcome, W)
        sym = OUTCOME_SYM.get(wr.outcome, "?")
        pred = GR + "да" + W if wr.was_predicted else DM + "нет" + W
        print(
            f"  {wr.word:<16} {wr.role:<7}  "
            f"{wr.probe_count:>6}  "
            f"{col}{sym} {wr.outcome:<10}{W}  {pred}"
        )
        count += 1
        if count >= n:
            break


def print_smart_gen_stats(app) -> None:
    """
    Показать Gen, сформированные SmartTextDriver (label содержит |p= или |role=).
    Сравнить с TextDriver Gen (label = просто слово).
    """
    all_gen = app.system.base.all()
    smart_gen = [g for g in all_gen if g.label and "|role=" in g.label]
    text_gen  = [g for g in all_gen if g.label and "|role=" not in g.label]

    print(f"  Всего Gen в базе:       {len(all_gen):5d}")
    print(f"  TextDriver Gen:         {len(text_gen):5d}  (label = слово)")
    print(f"  SmartTextDriver Gen:    {len(smart_gen):5d}  (label = слово|p=N|role=...)")

    if smart_gen:
        by_role: Dict[str, List] = defaultdict(list)
        for g in smart_gen:
            label = g.label or ""
            role = "rheme" if "role=rheme" in label else "theme"
            by_role[role].append(g)

        print()
        print(f"  {'Роль':<10} {'Gen':>6} {'Avg sig':>9} {'Avg chain':>10}")
        print(f"  {'─'*10} {'─'*6} {'─'*9} {'─'*10}")
        for role, gens in by_role.items():
            avg_sig   = sum(g.significance for g in gens) / len(gens)
            avg_chain = sum(len(g.feature_chain) for g in gens) / len(gens)
            print(f"  {role:<10}  {len(gens):>5}  {avg_sig:>8.3f}  {avg_chain:>9.2f}")

        print()
        sub("Топ-5 SmartTextDriver Gen по значимости")
        top_smart = sorted(smart_gen, key=lambda g: g.significance, reverse=True)[:5]
        for g in top_smart:
            print(f"    sig={g.significance:.3f}  chain={len(g.feature_chain):2d}  «{g.label}»")

    if text_gen:
        print()
        sub("Топ-5 TextDriver Gen по значимости")
        top_text = sorted(text_gen, key=lambda g: g.significance, reverse=True)[:5]
        for g in top_text:
            print(f"    sig={g.significance:.3f}  chain={len(g.feature_chain):2d}  «{g.label}»")


# ══════════════════════════════════════════════════════════════════════════════
# Главная функция
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="SmartTextDriver активный режим — карта сюрпризов"
    )
    parser.add_argument("--passes",   type=int,   default=10)
    parser.add_argument("--tol",      type=float, default=0.15)
    parser.add_argument("--verbose",  action="store_true")
    parser.add_argument("--heatmap",  action="store_true",
                        help="Показать тепловую карту каждого текста")
    args = parser.parse_args()

    # ── 1. Обучение ────────────────────────────────────────────────────────
    hdr("Шаг 1: Обучение (TextDriver) на 5 ситуациях")

    app = CoreApplication(config={
        "mock_teacher": False,
        "feature_tolerance": args.tol,
    })
    app.startup()

    train_texts = [t for sit in TRAIN_SITUATIONS for t in SITUATION_FAMILIES[sit]]
    print(f"  Текстов: {len(train_texts)}  ({len(TRAIN_SITUATIONS)} ситуаций)\n")
    train_baseline(app, train_texts, n_passes=args.passes)

    base_size = len(app.system.base.all())
    print(f"\n  База после обучения: {base_size} Gen")

    # ── 2. Словарь из Gen-базы ────────────────────────────────────────────
    gen_vocab = get_gen_vocab(app, max_chain=2)
    print(f"  Gen-словарь (chain≤2): {len(gen_vocab)} слов")
    print(f"  Пример кандидатов: {gen_vocab[:10]}\n")

    # ── 3. Контроль: знакомые ситуации ───────────────────────────────────
    hdr("Шаг 2: Контроль — SmartTextDriver на знакомых ситуациях")

    train_records: List[TextRecord] = []
    for sit in TRAIN_SITUATIONS[:2]:
        sub(sit)
        for text in SITUATION_FAMILIES[sit][:3]:
            rec = run_smart(app, text, sit, gen_vocab, verbose=args.verbose)
            train_records.append(rec)
            mr = rec.match_rate
            ap = rec.avg_probes
            pr = rec.predicted_rate
            col = GR if mr >= 0.8 else AM if mr >= 0.5 else RD
            print(
                f"  {col}MR={mr:.3f}{W}  "
                f"avg_probes={ap:.2f}  "
                f"predicted={pr:.0%}  "
                f"«{text[:50]}»"
            )
            if args.heatmap:
                print_word_heatmap(rec)
                print()

    # ── 4. Тест: новые ситуации ───────────────────────────────────────────
    hdr("Шаг 3: SmartTextDriver на НОВЫХ ситуациях")
    print(f"  Ситуации: {', '.join(TEST_SITUATIONS)}\n")

    test_records: List[TextRecord] = []
    sit_records: Dict[str, List[TextRecord]] = defaultdict(list)

    for sit in TEST_SITUATIONS:
        sub(sit)
        for text in SITUATION_FAMILIES[sit]:
            rec = run_smart(app, text, sit, gen_vocab, verbose=args.verbose)
            test_records.append(rec)
            sit_records[sit].append(rec)
            mr = rec.match_rate
            ap = rec.avg_probes
            pr = rec.predicted_rate
            col = GR if mr >= 0.7 else AM if mr >= 0.4 else RD
            n_gap = sum(1 for w in rec.words if w.outcome in
                        (StepOutcome.REFUTED, StepOutcome.EXPLORING, StepOutcome.CYCLE_AVOIDED))
            print(
                f"  {col}MR={mr:.3f}{W}  "
                f"probes={ap:.2f}  "
                f"predicted={pr:.0%}  "
                f"surprises={n_gap}  "
                f"«{text[:45]}»"
            )
            if args.heatmap:
                print_word_heatmap(rec)
                print()

    # ── 5. Корреляция probe count ↔ outcome ──────────────────────────────
    hdr("Шаг 4: Корреляция — структурный сюрприз ↔ семантический сюрприз")
    print(f"  Структурный сюрприз = много символьных проб (EntropyMinimizer)")
    print(f"  Семантический сюрприз = REFUTED / EXPLORING (Gen-система)\n")
    print_correlation_table(test_records)

    # ── 6. Тема/Рема ─────────────────────────────────────────────────────
    hdr("Шаг 5: Тема vs Рема — где концентрируются сюрпризы?")
    print(f"  Гипотеза Фирбаса: рема = носитель новой информации → больше REFUTED\n")
    print_theme_rheme_stats(test_records)

    # ── 7. Топ-сюрпризы ──────────────────────────────────────────────────
    hdr("Шаг 6: Топ-10 самых удивительных слов (структурный + семантический)")
    print_top_surprises(test_records, n=10)

    # ── 8. Ситуационная сводка ────────────────────────────────────────────
    hdr("Шаг 7: Сводка по ситуациям")
    print(
        f"  {'Ситуация':<14} {'Текстов':>7} {'MR avg':>8} "
        f"{'Probes avg':>11} {'Predicted%':>11} {'Surprises':>10}"
    )
    print(f"  {'─'*14} {'─'*7} {'─'*8} {'─'*11} {'─'*11} {'─'*10}")
    for sit in TEST_SITUATIONS:
        recs = sit_records[sit]
        if not recs:
            continue
        mr_avg    = sum(r.match_rate for r in recs) / len(recs)
        pr_avg    = sum(r.avg_probes for r in recs) / len(recs)
        pred_avg  = sum(r.predicted_rate for r in recs) / len(recs)
        n_surp    = sum(
            sum(1 for w in r.words
                if w.outcome in (StepOutcome.REFUTED, StepOutcome.EXPLORING,
                                 StepOutcome.CYCLE_AVOIDED))
            for r in recs
        )
        col = GR if mr_avg >= 0.7 else AM if mr_avg >= 0.5 else RD
        print(
            f"  {sit:<14}  {len(recs):>6}  "
            f"{col}{mr_avg:>7.3f}{W}  "
            f"{pr_avg:>10.2f}  {pred_avg:>10.1%}  {n_surp:>10}"
        )

    # ── 9. Gen от SmartTextDriver ─────────────────────────────────────────
    hdr("Шаг 8: Что нового создал SmartTextDriver в базе Gen")
    print_smart_gen_stats(app)

    # ── 10. Итог ─────────────────────────────────────────────────────────
    hdr("Итог")
    total_words   = sum(len(r.words) for r in test_records)
    total_pred    = sum(1 for r in test_records for w in r.words if w.was_predicted)
    total_conf    = sum(1 for r in test_records for w in r.words
                        if w.outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED))
    total_refuted = sum(1 for r in test_records for w in r.words
                        if w.outcome == StepOutcome.REFUTED)
    avg_pr        = sum(w.probe_count for r in test_records for w in r.words) / max(total_words, 1)

    print(f"  {'Слов обработано':<30} {total_words}")
    print(f"  {'Predicted (в Gen-словаре)':<30} {total_pred} = {total_pred/max(total_words,1):.1%}")
    print(f"  {'CONFIRMED/COMPLETED':<30} {total_conf} = {total_conf/max(total_words,1):.1%}")
    print(f"  {'REFUTED':<30} {total_refuted} = {total_refuted/max(total_words,1):.1%}")
    print(f"  {'Avg probe count':<30} {avg_pr:.2f}")
    print()

    if total_refuted > 0:
        refuted_words = [
            w for r in test_records for w in r.words
            if w.outcome == StepOutcome.REFUTED
        ]
        refuted_probes = sum(w.probe_count for w in refuted_words) / len(refuted_words)
        conf_probes_raw = [
            w.probe_count for r in test_records for w in r.words
            if w.outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED)
        ]
        conf_probes = sum(conf_probes_raw) / max(len(conf_probes_raw), 1)
        delta = refuted_probes - conf_probes
        print(f"  Avg probes при REFUTED:     {refuted_probes:.2f}")
        print(f"  Avg probes при CONFIRMED:   {conf_probes:.2f}")
        print(f"  Δ = {delta:+.2f} — {'↑ структурный сюрприз предсказывает семантический!' if delta > 0.3 else '~ корреляция слабая'}")
    print()


if __name__ == "__main__":
    main()
