"""
Эксперимент «Масштаб 1000 джеков»: интеграция, возврат учителя,
и точка «bypass» — когда гетерархия осваивает консолидацию изнутри.

Три вопроса:
  Q1 «Учитель возвращается»: сколько повторов нужно на каждый текст/семью
     до достижения мастерства (match_rate ≥ 0.7 три посещения подряд)?

  Q2 «Интеграция»: когда появляются Gen, покрывающие несколько семей
     (кросс-доменные паттерны)?

  Q3 «Bypass»: при каком числе итераций GreedyGeneralizer сам порождает
     Gen, неотличимые по структуре от мета-Gen HierarchicalConsolidator?
     Есть ли вообще такая точка, или без консолидатора их не бывает?

Протокол:
  - Два режима: WITH_CONSOL / WITHOUT_CONSOL (параллельно)
  - Условие одно: 35 итераций по всем 49 текстам ≈ 1715 проходов
  - Консолидация в WITH_CONSOL каждые 5 полных кругов (раз в ~245 проходов)
  - Снапшот каждые 5 кругов: gen_count, meta_count, match_rate, natural_meta_count
  - Кривые возврата учителя: visit_count per text per mastery threshold

Запуск:
    py -X utf8 training/integration_experiment.py
    py -X utf8 training/integration_experiment.py --quick   # 15 итераций
"""

from __future__ import annotations

import sys
import os
import time
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import CoreApplication
from core.learning import LearningSystem, HierarchicalConsolidator
from core.algorithm import StepOutcome
from curriculum.debug_session import DebugSession
from drivers.text_driver import TextDriver
from training.rich_corpus import (
    ALL_TEXTS, FAMILY_LABELS, family_of, corpus_stats
)

# ── Цвета ──────────────────────────────────────────────────────────────
W  = "\033[0m";  CY = "\033[96m"; GR = "\033[92m"; AM = "\033[93m"
RD = "\033[91m"; DM = "\033[90m"; PU = "\033[95m"; BL = "\033[94m"
BD = "\033[1m"

def _hdr(t):
    print(f"\n{BD}{CY}{'═'*68}{W}\n{BD}{CY}  {t}{W}\n{BD}{CY}{'═'*68}{W}\n")

def _sub(t):  print(f"  {AM}▶ {t}{W}")
def _ok(t):   print(f"  {GR}✓ {t}{W}")
def _warn(t): print(f"  {AM}⚠ {t}{W}")
def _dim(t):  print(f"  {DM}{t}{W}")
def _num(label, val, fmt=""):
    v = f"{val:{fmt}}" if fmt else str(val)
    print(f"  {DM}{label:<44}{W} {BD}{v}{W}")

FAMILY_COLORS = {
    "matryoshka":  PU,
    "bifurcation": CY,
    "rhythm":      GR,
    "narrative":   AM,
    "unknown":     DM,
}


# ══════════════════════════════════════════════════════════════════════
# Утилиты
# ══════════════════════════════════════════════════════════════════════

def _fresh(tol: float = 0.15) -> CoreApplication:
    app = CoreApplication(config={"mock_teacher": False, "feature_tolerance": tol})
    app.startup()
    return app


def _simulate_text(sys_: LearningSystem, text: str) -> float:
    """Прогнать текст, вернуть match_rate (с мутацией — настоящее обучение)."""
    driver = TextDriver(driver_id="text")
    tokens = list(driver.produce(text))
    confirmed = 0
    for tok in tokens:
        r = sys_.process_token(tok)
        if r.outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED):
            confirmed += 1
    sys_.reset_context()
    return confirmed / len(tokens) if tokens else 0.0


def detect_natural_meta(sys_: LearningSystem,
                         min_sig: float = 0.6,
                         min_children: int = 2,
                         max_chain: int = 3) -> List[Dict]:
    """
    Найти Gen, которые выглядят как «естественные мета-Gen»:
      - короткая цепочка (≤ max_chain) — абстрактный уровень
      - высокая значимость (≥ min_sig) — хорошо подтверждены
      - являются префиксом для ≥ min_children других Gen

    Это GreedyGeneralizer-порождённые аналоги мета-Gen.
    В отличие от consolidator-мета, они НЕ помечены meta_* / fork_*.
    """
    all_gens = sys_.base.all()
    results = []
    for g in all_gens:
        if len(g.feature_chain) > max_chain:
            continue
        if g.significance < min_sig:
            continue
        if g.label and (g.label.startswith("meta_") or g.label.startswith("fork_")):
            continue   # это consol-мета, не считаем
        # Сколько других Gen используют эту цепочку как префикс?
        prefix = g.feature_chain
        children = [
            other for other in all_gens
            if other.gen_id != g.gen_id
            and len(other.feature_chain) > len(prefix)
            and list(other.feature_chain[:len(prefix)]) == list(prefix)
        ]
        if len(children) >= min_children:
            results.append({
                "gen_id":    g.gen_id[:8],
                "sig":       round(g.significance, 3),
                "chain_len": len(g.feature_chain),
                "children":  len(children),
                "label":     g.label or "",
            })
    results.sort(key=lambda x: (-x["children"], -x["sig"]))
    return results


def consol_meta_count(sys_: LearningSystem) -> int:
    """Число Gen, явно созданных HierarchicalConsolidator (meta_* / fork_*)."""
    return sum(
        1 for g in sys_.base.all()
        if g.label and (g.label.startswith("meta_") or g.label.startswith("fork_"))
    )


# ══════════════════════════════════════════════════════════════════════
# Трекер посещений (учитель возвращается)
# ══════════════════════════════════════════════════════════════════════

@dataclass
class TextTracker:
    """История визитов учителя к одному тексту."""
    text: str
    family: str
    visits: List[float] = field(default_factory=list)   # match_rate на каждом визите
    mastered_at: Optional[int] = None                    # номер визита, когда «освоен»

    MASTERY_THRESHOLD: float = 0.65
    MASTERY_WINDOW:    int   = 3      # N подряд визитов выше порога

    def record(self, match_rate: float) -> None:
        self.visits.append(match_rate)
        if self.mastered_at is None and self._check_mastery():
            self.mastered_at = len(self.visits)

    def _check_mastery(self) -> bool:
        w = self.visits[-self.MASTERY_WINDOW:]
        return (len(w) == self.MASTERY_WINDOW
                and all(v >= self.MASTERY_THRESHOLD for v in w))

    @property
    def mastered(self) -> bool:
        return self.mastered_at is not None

    @property
    def last_mr(self) -> float:
        return self.visits[-1] if self.visits else 0.0

    @property
    def avg_mr(self) -> float:
        return sum(self.visits) / len(self.visits) if self.visits else 0.0


class TeacherCurriculum:
    """
    Стратегия учителя с приоритетом слабых текстов.

    Каждый «круг»:
      - Все тексты посещаются хотя бы раз
      - Неосвоенные тексты посещаются ещё раз (дополнительный проход)
      - После мастерства — «освежение» раз в REFRESH_EVERY кругов
    """
    REFRESH_EVERY = 5

    def __init__(self, texts: List[str]) -> None:
        self.trackers: Dict[str, TextTracker] = {
            t: TextTracker(t, family_of(t)) for t in texts
        }
        self.round_num: int = 0

    def texts_for_round(self) -> List[str]:
        """Тексты для текущего круга (приоритет слабых)."""
        all_t = list(self.trackers.keys())
        primary  = [t for t in all_t if not self.trackers[t].mastered]
        refresh  = [t for t in all_t
                    if self.trackers[t].mastered
                    and self.round_num % self.REFRESH_EVERY == 0]
        # Неосвоенные дважды — чтобы учитель настаивал на сложных
        return primary + primary + refresh

    def record(self, text: str, mr: float) -> None:
        self.trackers[text].record(mr)

    def advance_round(self) -> None:
        self.round_num += 1

    def mastery_summary(self) -> Dict[str, any]:
        trackers = list(self.trackers.values())
        mastered = [t for t in trackers if t.mastered]
        by_family: Dict[str, Dict] = {}
        for fam in FAMILY_LABELS:
            fam_trackers = [t for t in trackers if t.family == fam]
            fam_mastered = [t for t in fam_trackers if t.mastered]
            visits_to_m  = [t.mastered_at for t in fam_mastered if t.mastered_at]
            by_family[fam] = {
                "total":          len(fam_trackers),
                "mastered":       len(fam_mastered),
                "avg_visits":     round(sum(visits_to_m) / len(visits_to_m), 1) if visits_to_m else None,
                "min_visits":     min(visits_to_m) if visits_to_m else None,
                "max_visits":     max(visits_to_m) if visits_to_m else None,
            }
        return {
            "total":     len(trackers),
            "mastered":  len(mastered),
            "by_family": by_family,
        }


# ══════════════════════════════════════════════════════════════════════
# Снапшот состояния системы
# ══════════════════════════════════════════════════════════════════════

@dataclass
class Snapshot:
    round_num:        int
    gen_count:        int
    consol_meta:      int
    natural_meta:     int
    avg_match_rate:   float
    text_count:       int
    mastered_count:   int


def take_snapshot(
    sys_: LearningSystem,
    curr: TeacherCurriculum,
    round_num: int,
) -> Snapshot:
    ms = curr.mastery_summary()
    trackers = list(curr.trackers.values())
    all_mrs = [t.last_mr for t in trackers if t.visits]
    avg_mr = sum(all_mrs) / len(all_mrs) if all_mrs else 0.0
    natural = detect_natural_meta(sys_)
    return Snapshot(
        round_num=round_num,
        gen_count=len(sys_.base.all()),
        consol_meta=consol_meta_count(sys_),
        natural_meta=len(natural),
        avg_match_rate=round(avg_mr, 4),
        text_count=ms["total"],
        mastered_count=ms["mastered"],
    )


# ══════════════════════════════════════════════════════════════════════
# Основная функция прогона
# ══════════════════════════════════════════════════════════════════════

def run_condition(
    condition_name: str,
    n_rounds: int,
    with_consolidation: bool,
    consol_every: int = 5,
    snap_every: int   = 5,
) -> Tuple[List[Snapshot], TeacherCurriculum, LearningSystem]:

    app = _fresh(tol=0.15)
    sys_ = app.system
    session = DebugSession(app)

    # Словарь по всему корпусу
    app.peripherals.get("text").build_vocab(ALL_TEXTS)

    curr = TeacherCurriculum(ALL_TEXTS)
    snapshots: List[Snapshot] = []
    total_passes = 0

    _sub(f"Условие «{condition_name}»: {n_rounds} кругов × ~{len(ALL_TEXTS)} текстов …")
    t0 = time.time()

    for rnd in range(1, n_rounds + 1):
        texts = curr.texts_for_round()
        total_passes += len(texts)

        for text in texts:
            mr = _simulate_text(sys_, text)
            curr.record(text, mr)

        if with_consolidation and rnd % consol_every == 0:
            session.consolidate(n_steps=len(ALL_TEXTS) * 3, tolerance_factor=0.6)
            session.consolidate_hierarchy(passes=3)

        if rnd % snap_every == 0 or rnd == 1:
            snap = take_snapshot(sys_, curr, rnd)
            snapshots.append(snap)

        curr.advance_round()

    elapsed = time.time() - t0
    _num(f"  Время ({condition_name})", f"{elapsed:.1f} сек")
    _num(f"  Всего проходов", total_passes)

    return snapshots, curr, sys_


# ══════════════════════════════════════════════════════════════════════
# Анализ bypass-точки
# ══════════════════════════════════════════════════════════════════════

def find_bypass_point(
    snaps_with:    List[Snapshot],
    snaps_without: List[Snapshot],
) -> Optional[int]:
    """
    Найти round, когда natural_meta в WITHOUT_CONSOL
    достигает того же уровня, что consol_meta в WITH_CONSOL.

    Возвращает round или None если не достигнуто.
    """
    # Словарь round → consol_meta (WITH)
    with_by_round = {s.round_num: s.consol_meta for s in snaps_with}
    for s in snaps_without:
        target = with_by_round.get(s.round_num, 0)
        if s.natural_meta >= target and target > 0:
            return s.round_num
    return None


# ══════════════════════════════════════════════════════════════════════
# Вывод таблиц
# ══════════════════════════════════════════════════════════════════════

def print_snapshot_table(snaps: List[Snapshot], label: str) -> None:
    print(f"\n  {BD}Прогресс: {label}{W}")
    print(f"  {BD}{'Круг':>5}  {'Gen':>5}  {'c-meta':>6}  {'n-meta':>6}  "
          f"{'avg_mr':>6}  {'освоено':>7}{W}")
    for s in snaps:
        mr_col = GR if s.avg_match_rate > 0.6 else (AM if s.avg_match_rate > 0.3 else RD)
        nm_col = GR if s.natural_meta > 0 else DM
        print(f"  {s.round_num:>5}  {s.gen_count:>5}  "
              f"{s.consol_meta:>6}  "
              f"{nm_col}{s.natural_meta:>6}{W}  "
              f"{mr_col}{s.avg_match_rate:>6.3f}{W}  "
              f"{s.mastered_count:>3}/{s.text_count}")


def print_mastery_table(curr: TeacherCurriculum) -> None:
    ms = curr.mastery_summary()
    print(f"\n  {BD}Мастерство по семьям:{W}")
    print(f"  {BD}{'Семья':<15}  {'Всего':>6}  {'Освоено':>8}  "
          f"{'avg_visits':>10}  {'min':>4}  {'max':>4}{W}")
    for fam, stats in ms["by_family"].items():
        col = FAMILY_COLORS.get(fam, DM)
        avg_v = f"{stats['avg_visits']:.1f}" if stats['avg_visits'] is not None else "—"
        mn_v  = str(stats['min_visits']) if stats['min_visits'] is not None else "—"
        mx_v  = str(stats['max_visits']) if stats['max_visits'] is not None else "—"
        print(f"  {col}{fam:<15}{W}  {stats['total']:>6}  "
              f"{stats['mastered']:>8}  {avg_v:>10}  {mn_v:>4}  {mx_v:>4}")
    print(f"  {'ИТОГО':<15}  {ms['total']:>6}  {ms['mastered']:>8}")


def print_natural_meta_detail(sys_: LearningSystem, n: int = 10) -> None:
    naturals = detect_natural_meta(sys_)
    if not naturals:
        _dim("Естественных мета-Gen не обнаружено.")
        return
    print(f"\n  {BD}Топ-{n} «естественных мета-Gen» (без консолидатора):{W}")
    print(f"  {BD}{'gen_id':>10}  {'sig':>5}  {'chain':>5}  {'children':>8}  {'label'}{W}")
    for g in naturals[:n]:
        print(f"  {GR}{g['gen_id']:>10}{W}  {AM}{g['sig']:>5.3f}{W}  "
              f"{g['chain_len']:>5}  {g['children']:>8}  {DM}{g['label']}{W}")


def print_hard_texts(curr: TeacherCurriculum, n: int = 10) -> None:
    """Самые трудные тексты (больше всего визитов до мастерства)."""
    mastered = [t for t in curr.trackers.values() if t.mastered]
    if not mastered:
        _warn("Ни один текст не освоен.")
        return
    mastered.sort(key=lambda t: -(t.mastered_at or 0))
    print(f"\n  {BD}Топ-{n} труднейших текстов (визитов до мастерства):{W}")
    for tr in mastered[:n]:
        col = FAMILY_COLORS.get(tr.family, DM)
        short = tr.text[:55]
        print(f"  {BD}{tr.mastered_at:>3}{W} визита  "
              f"{col}{tr.family:<12}{W}  «{DM}{short}{W}»")


# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════

def main(n_rounds: int = 35, consol_every: int = 5, snap_every: int = 5) -> None:
    _hdr(f"Интеграция «масштаб 1000 джеков» · {n_rounds} кругов × {len(ALL_TEXTS)} текстов")

    cs = corpus_stats()
    _num("Корпус: всего текстов", cs["total"])
    for fam, cnt in cs.items():
        if fam == "total": continue
        col = FAMILY_COLORS.get(fam, DM)
        print(f"  {col}{fam:<15}{W} {cnt}")
    _num("Ожидаемых проходов (approx)", f"~{n_rounds * len(ALL_TEXTS) * 2}")
    _num("Консолидация каждые N кругов", consol_every)
    print()

    # ── Условие A: с консолидацией ─────────────────────────────────
    snaps_with, curr_with, sys_with = run_condition(
        "С консолидацией",
        n_rounds=n_rounds,
        with_consolidation=True,
        consol_every=consol_every,
        snap_every=snap_every,
    )

    # ── Условие B: без консолидации ────────────────────────────────
    snaps_without, curr_without, sys_without = run_condition(
        "Без консолидации",
        n_rounds=n_rounds,
        with_consolidation=False,
        snap_every=snap_every,
    )

    # ══════════════════════════════════════════════════════════════
    # Таблицы прогресса
    # ══════════════════════════════════════════════════════════════
    _hdr("Q1+Q2 — Прогресс: Gen, мета-Gen, match_rate, мастерство")

    print_snapshot_table(snaps_with,    "С консолидацией")
    print_snapshot_table(snaps_without, "Без консолидации")

    # ══════════════════════════════════════════════════════════════
    # Мастерство по семьям — Q1
    # ══════════════════════════════════════════════════════════════
    _hdr("Q1 — Возврат учителя: визитов до мастерства по семьям")

    print(f"\n  {BD}С консолидацией:{W}")
    print_mastery_table(curr_with)
    print_hard_texts(curr_with)

    print(f"\n  {BD}Без консолидации:{W}")
    print_mastery_table(curr_without)
    print_hard_texts(curr_without)

    # ══════════════════════════════════════════════════════════════
    # Bypass-точка — Q3
    # ══════════════════════════════════════════════════════════════
    _hdr("Q3 — «Bypass»: когда гетерархия учится консолидировать изнутри")

    bypass_round = find_bypass_point(snaps_with, snaps_without)

    print(f"  {BD}Естественные мета-Gen (без консолидатора):{W}")
    print_natural_meta_detail(sys_without, n=15)

    final_with    = snaps_with[-1]
    final_without = snaps_without[-1]

    _num("Финал WITH:    consol_meta", final_with.consol_meta)
    _num("Финал WITHOUT: natural_meta", final_without.natural_meta)

    if bypass_round:
        _ok(f"Bypass-точка найдена: раунд {bypass_round}")
        _dim("→ С этого момента GreedyGeneralizer порождает эквиваленты мета-Gen.")
        _dim("→ HierarchicalConsolidator становится «костылём» только до этой точки.")
    else:
        _warn(f"Bypass-точка НЕ достигнута за {n_rounds} кругов.")
        ratio = final_without.natural_meta / max(final_with.consol_meta, 1)
        _dim(f"  natural_meta / consol_meta = {ratio:.2f} (нужно ≥ 1.0)")
        _dim("→ GreedyGeneralizer один не справляется без явной консолидации.")
        _dim("→ HierarchicalConsolidator остаётся необходимым на данном масштабе.")

    # ══════════════════════════════════════════════════════════════
    # Сравнительный итог
    # ══════════════════════════════════════════════════════════════
    _hdr("Итоговое сравнение")

    print(f"  {BD}{'Метрика':<35}  {'С консол.':>12}  {'Без консол.':>12}{W}")
    metrics = [
        ("Gen в базе (финал)",
         final_with.gen_count, final_without.gen_count),
        ("Консолидатор-мета-Gen",
         final_with.consol_meta, final_without.consol_meta),
        ("Естественных мета-Gen",
         final_with.natural_meta, final_without.natural_meta),
        ("Освоено текстов",
         final_with.mastered_count, final_without.mastered_count),
        ("avg match_rate (финал)",
         f"{final_with.avg_match_rate:.3f}", f"{final_without.avg_match_rate:.3f}"),
    ]
    for label, va, vb in metrics:
        print(f"  {label:<35}  {BD}{str(va):>12}{W}  {BD}{str(vb):>12}{W}")

    _hdr("Следующие вопросы")
    print(f"  {BD}H6 (WakeUp на большой базе):{W}")
    _dim(f"  → Теперь база {final_with.gen_count} Gen. Запустить H6 на этой базе.")
    print(f"\n  {BD}H7 (knock→curriculum):{W}")
    knock = sys_with.vitality.knock_candidates(
        [g.gen_id for g in sys_with.base.all()],
        sys_with.base,
        sys_with.engine.step_count,
        threshold=2.0,
    )
    _dim(f"  → {len(knock)} кандидатов urgency≥2.0. Вернуть учителя к ним принудительно.")
    print(f"\n  {BD}H8 (перегиб кривой роста):{W}")
    if len(snaps_with) >= 3:
        early_g  = snaps_with[1].gen_count - snaps_with[0].gen_count
        late_g   = snaps_with[-1].gen_count - snaps_with[-2].gen_count
        _dim(f"  → ΔGen ранний={early_g}, поздний={late_g}. Перегиб {'найден' if late_g < early_g else 'не выражен'}.")
    print(f"\n  {BD}Bypass-вывод:{W}")
    if bypass_round:
        _dim(f"  → После раунда {bypass_round} можно отключать HierarchicalConsolidator.")
        _dim(f"  → Тест: убрать консолидацию после bypass_round и отслеживать деградацию.")
    else:
        _dim(f"  → Увеличить n_rounds до {n_rounds * 3} и повторить для поиска bypass-точки.")
        _dim(f"  → Альтернатива: добавить в GreedyGeneralizer отслеживание «суффиксных детей».")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick",       action="store_true", help="Быстрый режим: 15 кругов")
    parser.add_argument("--rounds",      type=int, default=35)
    parser.add_argument("--consol-every", type=int, default=5)
    args = parser.parse_args()
    n = 15 if args.quick else args.rounds
    main(n_rounds=n, consol_every=args.consol_every)
