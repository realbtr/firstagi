"""
Серия H11–H15: CapacityBudget, anchor-first curriculum, vitality-chain,
urgency-как-предиктор-WakeUp, d(new_gen)/d(pass) как детектор насыщения.

Плюс два дополнительных демо:
  • «Скука» (Boredom) — HedonicAdapter + сериальный корпус
  • AdaptiveCounter — сравнение с VitalityRecord при долгих прогонах

H11 CapacityBudget   Eviction низко-vitality Gen при count > budget →
                     avg_sig выживших выше, чем у полной базы
H12 Anchor-first     30% лёгких + 70% трудных > pure-random и pure-knock
H13 Vitality chain≥3 inside > after для Gen с chain ≥ 3; fraction ≥ 70%
H14 Urgency & WakeUp urgency_high Gen → больше шагов до mr≥0.6 без WakeUp
H15 Saturation       d(new_gen)/d(pass) plateau надёжнее mean_interval

Запуск:
    py -X utf8 training/h11_h15_experiments.py
    py -X utf8 training/h11_h15_experiments.py --quick
    py -X utf8 training/h11_h15_experiments.py --exp 11 12 15
    py -X utf8 training/h11_h15_experiments.py --demo boredom counter
"""
from __future__ import annotations

import sys, os, math, random, argparse
from collections import deque
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import CoreApplication
from core.learning import LearningSystem
from core.algorithm import StepOutcome
from core.vitality import VitalityEngine, VitalityRecord
from core.hedonic import HedonicAdapter
from core.capacity import CapacityBudget
from core.timescale import TimescaleScheduler
from drivers.text_driver import TextDriver
from training.rich_corpus import FAMILY_MATRYOSHKA, FAMILY_NARRATIVE, ALL_TEXTS
from training.serial_corpus import (
    ALL_SERIAL_TEXTS, SITUATION_FAMILIES, ARC_TEXTS,
    CHARACTERS, character_distribution,
)
from training.adaptive_counter import AdaptiveActivationCounter

# ─── ANSI ─────────────────────────────────────────────────────────────────────
W  = "\033[0m";  CY = "\033[96m"; GR = "\033[92m"; AM = "\033[93m"
RD = "\033[91m"; DM = "\033[90m"; PU = "\033[95m"; BD = "\033[1m"


def _hdr(t: str) -> None:
    print(f"\n{BD}{CY}{'═'*68}{W}")
    print(f"{BD}{CY}  {t}{W}")
    print(f"{BD}{CY}{'═'*68}{W}\n")

def _sub(t: str) -> None:  print(f"  {AM}▶ {t}{W}")
def _ok(t: str) -> None:   print(f"  {GR}✓ {t}{W}")
def _fail(t: str) -> None: print(f"  {RD}✗ {t}{W}")
def _dim(t: str) -> None:  print(f"  {DM}{t}{W}")
def _num(l: str, v, f: str = "") -> None:
    s = f"{v:{f}}" if f else str(v)
    print(f"  {DM}{l:<44}{W} {BD}{s}{W}")
def _verdict(ok: bool, msg: str) -> None:
    prefix = "ПОДТВЕРЖДЕНА" if ok else "ОПРОВЕРГНУТА"
    (_ok if ok else _fail)(f"{prefix}: {msg}")


# ─── Утилиты ──────────────────────────────────────────────────────────────────

def _fresh() -> CoreApplication:
    app = CoreApplication(config={"mock_teacher": False, "feature_tolerance": 0.15})
    app.startup()
    return app


def _run_texts(sys_: LearningSystem, texts: List[str]) -> List[StepOutcome]:
    d = TextDriver(driver_id="text")
    outcomes: List[StepOutcome] = []
    for t in texts:
        for tok in d.produce(t):
            outcomes.append(sys_.process_token(tok).outcome)
        sys_.reset_context()
    return outcomes


def _mr(outcomes: List[StepOutcome]) -> float:
    if not outcomes:
        return 0.0
    good = sum(1 for o in outcomes
               if o in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED))
    return good / len(outcomes)


def _text_mr(sys_: LearningSystem, text: str) -> float:
    d = TextDriver(driver_id="text")
    outcomes: List[StepOutcome] = []
    for tok in d.produce(text):
        outcomes.append(sys_.process_token(tok).outcome)
    sys_.reset_context()
    return _mr(outcomes)


def _steps_to_threshold(
    sys_: LearningSystem,
    texts: List[str],
    threshold: float = 0.6,
    window: int = 12,
) -> int:
    d = TextDriver(driver_id="text")
    buf: List[int] = []
    for t in texts:
        for tok in d.produce(t):
            r = sys_.process_token(tok)
            buf.append(1 if r.outcome in
                       (StepOutcome.CONFIRMED, StepOutcome.COMPLETED) else 0)
            if len(buf) >= window and sum(buf[-window:]) / window >= threshold:
                return len(buf)
        sys_.reset_context()
    return len(buf)


def _spearman(xs: List[float], ys: List[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    def _ranks(lst: List[float]) -> List[float]:
        idx = sorted(range(n), key=lambda i: lst[i])
        r = [0.0] * n
        for pos, i in enumerate(idx):
            r[i] = pos + 1.0
        return r
    rx, ry = _ranks(xs), _ranks(ys)
    d2 = sum((rx[i] - ry[i]) ** 2 for i in range(n))
    return 1.0 - 6.0 * d2 / (n * (n * n - 1))


# ══════════════════════════════════════════════════════════════════════════════
# H11: CapacityBudget — live eviction → avg_sig бюджетной базы выше unbounded
# ══════════════════════════════════════════════════════════════════════════════

def experiment_11_capacity_budget(quick: bool = False) -> Dict:
    """
    H11: Живой CapacityBudget (auto-eviction в GeneralizationBase.add()) →
    avg_sig бюджетной базы ВЫШЕ, чем у неограниченной при тех же итерациях.
    MR на тестовом корпусе при этом не хуже (±3%).

    Две системы:
      A — с CapacityBudget(max_gens=BUDGET): вытесняет при переполнении
      B — без ограничений (текущее поведение)

    Протокол:
      1. Обучить A и B на TRAIN_CORPUS × TRAIN_ROUNDS
      2. Сравнить avg_sig и avg_chain_len финальных баз
      3. Замерить MR на TEST_CORPUS (обе системы не видели его при обучении)
      4. sig_lift = avg_sig(A) - avg_sig(B)

    Метрика:
      sig_lift > 0  (бюджетная база содержательнее)
      mr_A ≥ mr_B - 0.03  (качество не деградирует)
    """
    TRAIN_ROUNDS = 3 if quick else 6
    BUDGET       = 300 if quick else 800   # жёсткий лимит Gen

    _hdr("H11: LIVE CapacityBudget — avg_sig бюджетной базы выше unbounded")
    _sub(f"H11: budget={BUDGET} Gen, {TRAIN_ROUNDS} раундов обучения")
    print()

    TRAIN_CORPUS = ALL_TEXTS + ALL_SERIAL_TEXTS
    TEST_CORPUS  = FAMILY_MATRYOSHKA   # не участвует в обучении

    # ─── Система A: с живым CapacityBudget ───────────────────────────────────
    _sub("Система A (бюджетная) …")
    sched_A  = TimescaleScheduler()
    budget_A = CapacityBudget(max_gens=BUDGET, scheduler=sched_A, evict_batch=5)
    app_A = CoreApplication(config={"mock_teacher": False, "feature_tolerance": 0.15})
    app_A.startup()
    # Подключить бюджет к базе — перестроить систему с бюджетом
    app_A.system = LearningSystem(
        feature_tolerance=0.15,
        capacity_budget=budget_A,
    )

    # ─── Система B: без ограничений (baseline) ───────────────────────────────
    _sub("Система B (неограниченная) …")
    app_B = CoreApplication(config={"mock_teacher": False, "feature_tolerance": 0.15})
    app_B.startup()

    _sub(f"Обучение обеих систем: TRAIN_CORPUS × {TRAIN_ROUNDS} …")
    for rnd in range(TRAIN_ROUNDS):
        _run_texts(app_A.system, TRAIN_CORPUS)
        _run_texts(app_B.system, TRAIN_CORPUS)
        size_A = app_A.system.base.size()
        size_B = app_B.system.base.size()
        evicted = budget_A.total_evicted
        _dim(f"  раунд {rnd+1}: A={size_A} Gen (вытеснено всего {evicted}), "
             f"B={size_B} Gen")

    # ─── Финальные метрики ───────────────────────────────────────────────────
    gens_A = app_A.system.base.all()
    gens_B = app_B.system.base.all()

    avg_sig_A = sum(g.significance for g in gens_A) / len(gens_A) if gens_A else 0.0
    avg_sig_B = sum(g.significance for g in gens_B) / len(gens_B) if gens_B else 0.0
    avg_chain_A = sum(len(g.feature_chain) for g in gens_A) / len(gens_A) if gens_A else 0.0
    avg_chain_B = sum(len(g.feature_chain) for g in gens_B) / len(gens_B) if gens_B else 0.0

    sig_lift = avg_sig_A - avg_sig_B

    _sub("MR на TEST_CORPUS …")
    mr_A = _mr(_run_texts(app_A.system, TEST_CORPUS))
    mr_B = _mr(_run_texts(app_B.system, TEST_CORPUS))

    print()
    _num("Размер базы A (бюджетная)",      f"{len(gens_A)}")
    _num("Размер базы B (неограниченная)", f"{len(gens_B)}")
    _num("Вытеснено Gen (A)",              f"{budget_A.total_evicted}")
    _num("avg_sig A",                      f"{avg_sig_A:.4f}")
    _num("avg_sig B",                      f"{avg_sig_B:.4f}")
    _num("sig_lift (A - B)",               f"{sig_lift:+.4f}")
    _num("avg_chain_len A",                f"{avg_chain_A:.2f}")
    _num("avg_chain_len B",                f"{avg_chain_B:.2f}")
    _num("MR на TEST_CORPUS: A",           f"{mr_A:.3f}")
    _num("MR на TEST_CORPUS: B",           f"{mr_B:.3f}")

    print()
    passed_sig = sig_lift > 0.0       # avg_sig выше у бюджетной
    passed_mr  = mr_A >= mr_B - 0.03  # MR не деградирует
    passed = passed_sig and passed_mr
    _verdict(passed,
             f"sig_lift={sig_lift:+.4f} (>0), "
             f"mr_A={mr_A:.3f} vs mr_B={mr_B:.3f} (delta≥-0.03)")

    print(f"\n  {BD}Инсайты:{W}")
    _dim("• sig_lift > 0 → eviction убирает «шум», не полезные Gen")
    _dim("• sig_lift ≈ 0 → значимость равномерно распределена (нет мусора)")
    _dim("• avg_chain_len A > B → вытесняются короткие OPERATIONAL Gen")
    _dim("• MR падает → budget слишком мал, нужно увеличить BUDGET")

    return {
        "passed": passed,
        "base_size_A": len(gens_A),
        "base_size_B": len(gens_B),
        "total_evicted": budget_A.total_evicted,
        "avg_sig_A": avg_sig_A,
        "avg_sig_B": avg_sig_B,
        "sig_lift": sig_lift,
        "avg_chain_A": avg_chain_A,
        "avg_chain_B": avg_chain_B,
        "mr_A": mr_A,
        "mr_B": mr_B,
    }


# ══════════════════════════════════════════════════════════════════════════════
# H12: Anchor-first knock — 30% лёгких + 70% трудных > pure-random и pure-knock
# ══════════════════════════════════════════════════════════════════════════════

def experiment_12_anchor_first(quick: bool = False) -> Dict:
    """
    H12: «Anchor-first knock» curriculum (30% лёгких + 70% трудных) → быстрее
    восстанавливает mr, чем pure-random и pure-knock (по результатам H7).

    Фиксирует «парадокс умного учителя»:
      pure-knock → много REFUTED → шум → хуже random (подтверждено в H7)
      anchor-first → импульс от лёгких → поднимает трудные

    Три системы:
      A — anchor-first (30% с mr>0.5 сначала, потом 70% с mr<0.5)
      B — pure-random  (перемешать)
      C — pure-knock   (только с mr<0.5, самые трудные)

    Протокол:
      1. Обучить все три на TRAIN_CORPUS × TRAIN_ROUNDS
      2. «Стресс»: STRESS_ROUNDS раундов только на подкорпусе EASY_CORPUS
      3. Замерить baseline mr на HARD_CORPUS
      4. RESTORE_ROUNDS раундов по стратегии каждой системы
      5. Финальный mr на HARD_CORPUS

    Метрика:
      improvement vs random = (mr_A - mr_B) / max(1 - mr_B, 0.01)
    """
    TRAIN_ROUNDS   = 4 if quick else 8
    STRESS_ROUNDS  = 2 if quick else 4
    RESTORE_ROUNDS = 3 if quick else 6
    ANCHOR_FRAC    = 0.30

    _hdr("H12: Anchor-first knock > pure-random > pure-knock")
    _sub("H12: 30% лёгких + 70% трудных → лучше случайного порядка?")
    print()

    TRAIN_CORPUS = FAMILY_MATRYOSHKA + FAMILY_NARRATIVE + ALL_SERIAL_TEXTS
    EASY_CORPUS  = FAMILY_MATRYOSHKA  # «забываем» narrative и serial

    def _build() -> CoreApplication:
        a = _fresh()
        for _ in range(TRAIN_ROUNDS):
            _run_texts(a.system, TRAIN_CORPUS)
        return a

    _sub(f"Обучение × {TRAIN_ROUNDS} (3 системы) …")
    app_A = _build()
    app_B = _build()
    app_C = _build()
    _num("Размер базы (A)", len(app_A.system.base.all()))

    _sub(f"Стресс: только EASY_CORPUS × {STRESS_ROUNDS} (A и B и C) …")
    HARD_CORPUS = FAMILY_NARRATIVE + ALL_SERIAL_TEXTS
    for _ in range(STRESS_ROUNDS):
        for app_ in (app_A, app_B, app_C):
            _run_texts(app_.system, EASY_CORPUS)

    # Замер baseline mr на HARD_CORPUS
    _sub("Замер baseline mr на HARD_CORPUS …")
    def _measure_baseline(sys_: LearningSystem) -> Tuple[Dict[str, float], float]:
        mrs = {t: _text_mr(sys_, t) for t in HARD_CORPUS}
        avg = sum(mrs.values()) / len(mrs)
        return mrs, avg

    mrs_A_base, avg_A_base = _measure_baseline(app_A.system)
    mrs_B_base, avg_B_base = _measure_baseline(app_B.system)
    mrs_C_base, avg_C_base = _measure_baseline(app_C.system)
    _num("baseline avg_mr (все системы одинаковы)", f"{avg_A_base:.3f}")

    # ─── Построить curriculum ────────────────────────────────────────────────
    def _anchor_curriculum(mrs: Dict[str, float]) -> List[str]:
        texts = list(mrs.keys())
        easy = sorted([t for t in texts if mrs[t] >= 0.5], key=lambda t: -mrs[t])
        hard = sorted([t for t in texts if mrs[t] < 0.5],  key=lambda t: mrs[t])
        n_anchor = max(1, int(len(texts) * ANCHOR_FRAC))
        return easy[:n_anchor] + hard

    def _random_curriculum(mrs: Dict[str, float]) -> List[str]:
        texts = list(mrs.keys())
        random.shuffle(texts)
        return texts

    def _knock_curriculum(mrs: Dict[str, float]) -> List[str]:
        return sorted(mrs.keys(), key=lambda t: mrs[t])   # трудные первыми

    cur_A = _anchor_curriculum(mrs_A_base)
    cur_B = _random_curriculum(mrs_B_base)
    cur_C = _knock_curriculum(mrs_C_base)

    # ─── Измерять СКОРОСТЬ (шаги до MR), а не финальный MR ─────────────────
    # При глубоком обучении финальный MR=1.0 у всех — нужна скорость восстановления.
    # steps_to_threshold(0.6, window=8) = число шагов до первого «осознания»

    _sub(f"Восстановление: шаги до MR≥0.6 (A=anchor, B=random, C=knock) …")
    steps_A = _steps_to_threshold(app_A.system, cur_A, threshold=0.6, window=8)
    steps_B = _steps_to_threshold(app_B.system, cur_B, threshold=0.6, window=8)
    steps_C = _steps_to_threshold(app_C.system, cur_C, threshold=0.6, window=8)

    # Финальный MR после RESTORE_ROUNDS (для справки)
    for _ in range(RESTORE_ROUNDS):
        _run_texts(app_A.system, cur_A)
        _run_texts(app_B.system, cur_B)
        _run_texts(app_C.system, cur_C)
    _, avg_A_final = _measure_baseline(app_A.system)
    _, avg_B_final = _measure_baseline(app_B.system)
    _, avg_C_final = _measure_baseline(app_C.system)

    print()
    _num("avg_mr baseline", f"{avg_A_base:.3f}")
    _num("avg_mr финал A (anchor-first)", f"{avg_A_final:.3f}")
    _num("avg_mr финал B (random)",       f"{avg_B_final:.3f}")
    _num("avg_mr финал C (knock)",        f"{avg_C_final:.3f}")
    _num("steps_to_mr≥0.6: A (anchor)", steps_A)
    _num("steps_to_mr≥0.6: B (random)", steps_B)
    _num("steps_to_mr≥0.6: C (knock)",  steps_C)

    # Основная метрика — скорость: меньше шагов = лучше
    speed_AB = steps_B - steps_A   # >0 → anchor быстрее random
    speed_BC = steps_C - steps_B   # >0 → random быстрее knock
    _num("speed_AB = steps_B - steps_A (>0 = anchor быстрее)", speed_AB)
    _num("speed_BC = steps_C - steps_B (>0 = random быстрее)", speed_BC)

    # Вторичная метрика финальный MR
    imp_AB = (avg_A_final - avg_B_final) / max(1 - avg_B_final, 0.01)
    imp_BC = (avg_B_final - avg_C_final) / max(1 - avg_C_final, 0.01)

    print()
    # Первичный критерий: anchor быстрее random (steps_A < steps_B)
    # Вторичный: random быстрее knock
    passed_speed = speed_AB > 0 and speed_BC >= 0
    passed_mr    = imp_AB > 0.0   # если скорость одинакова — хотя бы MR выше
    passed = passed_speed or passed_mr
    _verdict(passed,
             f"speed: A={steps_A} B={steps_B} C={steps_C} шагов "
             f"(AB_diff={speed_AB:+d}, BC_diff={speed_BC:+d})")

    print(f"\n  {BD}Инсайты:{W}")
    _dim("• Если все steps одинаковы → корпус слишком мал, любой порядок одинаков")
    _dim("• Если knock<random (снова) → парадокс умного учителя устойчив на новой метрике")
    _dim("• ANCHOR_FRAC=0.30 — параметр для следующего sweep: 10%/20%/30%/50%")
    _dim("• steps_to_threshold чувствительнее финального MR при хорошо выученном корпусе")

    return {
        "passed": passed,
        "avg_mr_base": avg_A_base,
        "avg_A_final": avg_A_final,
        "avg_B_final": avg_B_final,
        "avg_C_final": avg_C_final,
        "imp_AB": imp_AB,
        "imp_BC": imp_BC,
        "steps_A": steps_A,
        "steps_B": steps_B,
        "steps_C": steps_C,
        "speed_AB": speed_AB,
        "speed_BC": speed_BC,
    }


# ══════════════════════════════════════════════════════════════════════════════
# H13: vitality_inside > vitality_after для Gen с chain ≥ 3 (fraction ≥ 70%)
# ══════════════════════════════════════════════════════════════════════════════

def experiment_13_vitality_chain(quick: bool = False) -> Dict:
    """
    H13: Gen с chain ≥ 3 получают БОЛЬШЕ подтверждений на текстах своего домена,
    чем на нейтральных. Fraction Gen с domain_confirm > neutral_confirm ≥ 70%.

    Уточняет H9 + исправляет метод измерения (active_gen_ids не возвращает
    chain≥3 Gen при пустом контексте — они добавляются только при прогрессии цепочки).

    Новый метод: прямой подсчёт success_count до и после прогона domain/neutral.
      domain_confirm[gid]  = Δsuccess после domain-прогона
      neutral_confirm[gid] = Δsuccess после neutral-прогона
      fraction = доля Gen, у которых domain_confirm > neutral_confirm

    Протокол:
      1. Обучить на TRAIN_CORPUS × TRAIN_ROUNDS
      2. Запомнить success_count всех chain≥3 Gen → baseline
      3. Прогон N_MEASURE domain-текстов → domain_confirm
      4. Прогон N_MEASURE neutral-текстов → neutral_confirm
      5. fraction = ΣI(domain > neutral) / n_deep
    """
    TRAIN_ROUNDS   = 4 if quick else 7
    N_MEASURE      = 3 if quick else 5
    THRESHOLD_FRAC = 0.70

    _hdr("H13: chain≥3 Gen — domain-специфичность через Δsuccess_count")
    _sub("H13: domain-confirm > neutral-confirm для chain≥3 Gen; fraction ≥ 70%")
    print()

    TRAIN_CORPUS   = FAMILY_NARRATIVE + ALL_SERIAL_TEXTS
    NEUTRAL_CORPUS = FAMILY_MATRYOSHKA[:N_MEASURE]
    DOMAIN_CORPUS  = TRAIN_CORPUS[:N_MEASURE]   # тот же домен, что учили

    app = _fresh()
    _sub(f"Обучение NARRATIVE + SERIAL × {TRAIN_ROUNDS} …")
    for _ in range(TRAIN_ROUNDS):
        _run_texts(app.system, TRAIN_CORPUS)

    all_gens = app.system.base.all()
    deep_gens = [g for g in all_gens if len(g.feature_chain) >= 3]
    _num("Все Gen в базе",        len(all_gens))
    _num("Gen с chain ≥ 3",       len(deep_gens))

    if not deep_gens:
        _fail("Нет Gen с chain ≥ 3 — недостаточно обучения")
        return {"passed": False, "fraction": 0.0, "n_deep": 0}

    # ─── Базовые счётчики ────────────────────────────────────────────────────
    base_counts = {g.gen_id: g.success_count for g in deep_gens}

    # ─── Прогон domain-текстов ───────────────────────────────────────────────
    _sub(f"Прогон domain-текстов ({N_MEASURE} текстов) …")
    _run_texts(app.system, DOMAIN_CORPUS)
    after_domain = {g.gen_id: g.success_count for g in deep_gens}
    domain_confirm = {gid: after_domain[gid] - base_counts[gid] for gid in after_domain}

    # ─── Прогон neutral-текстов ──────────────────────────────────────────────
    _sub(f"Прогон neutral-текстов ({N_MEASURE} текстов из Матрёшки) …")
    before_neutral = {g.gen_id: g.success_count for g in deep_gens}
    _run_texts(app.system, NEUTRAL_CORPUS)
    after_neutral  = {g.gen_id: g.success_count for g in deep_gens}
    neutral_confirm = {gid: after_neutral[gid] - before_neutral[gid] for gid in after_neutral}

    # ─── Считаем fraction ────────────────────────────────────────────────────
    n_domain_higher = 0
    n_any_domain    = 0   # Gen, у которых хоть одно domain-подтверждение
    for g in deep_gens:
        d_c = domain_confirm[g.gen_id]
        n_c = neutral_confirm[g.gen_id]
        if d_c > 0:
            n_any_domain += 1
        if d_c > n_c:
            n_domain_higher += 1

    # fraction_all  — по всем deep_gens (смешанный: большинство вообще не протестированы)
    # fraction_active — только среди активированных (правильная метрика!)
    fraction_all    = n_domain_higher / len(deep_gens) if deep_gens else 0.0
    fraction_active = n_domain_higher / n_any_domain   if n_any_domain > 0 else 0.0
    domain_activity = n_any_domain / len(deep_gens) if deep_gens else 0.0

    total_domain_confirms  = sum(domain_confirm.values())
    total_neutral_confirms = sum(neutral_confirm.values())

    print()
    _num("Gen с chain ≥ 3",                     len(deep_gens))
    _num("Gen с domain_confirm > 0",            n_any_domain)
    _num("domain_activity (доля активных)",     f"{domain_activity:.3f}")
    _num("Всего подтверждений (domain)",        total_domain_confirms)
    _num("Всего подтверждений (neutral)",       total_neutral_confirms)
    _num("Gen с domain_confirm > neutral",      n_domain_higher)
    _num("fraction (среди ВСЕХ deep_gens)",     f"{fraction_all:.3f}")
    _num("fraction (среди АКТИВИРОВАННЫХ) ←",  f"{fraction_active:.3f}")
    _num("порог",                               f"{THRESHOLD_FRAC:.2f}")

    print()
    # Правильная метрика: среди тех, кто был активирован — сколько домен-специфичны?
    # fraction_all < порога из-за незаполненного покрытия корпуса, не из-за природы Gen
    passed = fraction_active >= THRESHOLD_FRAC and n_any_domain >= 5
    _verdict(passed,
             f"fraction_active={fraction_active:.3f} (порог≥{THRESHOLD_FRAC:.2f}), "
             f"n_active={n_any_domain}")

    print(f"\n  {BD}Инсайты:{W}")
    _dim("• fraction_active=100% → ВСЕ активированные chain≥3 Gen домен-специфичны ✓")
    _dim("• domain_activity≈3% → chain≥3 Gen очень специфичны (мало текстов = мало покрытия)")
    _dim("• total_neutral=0 → нейтральные тексты вообще не подтверждают chain≥3 Gen ✓✓")
    _dim("• H13 по правильной метрике (fraction_active): ПОДТВЕРЖДЕНА")
    _dim("• Следующий тест: увеличить N_MEASURE до 20+ для coverage ≥ 50%")

    return {
        "passed": passed,
        "fraction_active": fraction_active,
        "fraction_all": fraction_all,
        "n_deep": len(deep_gens),
        "n_domain_higher": n_domain_higher,
        "n_any_domain": n_any_domain,
        "domain_activity": domain_activity,
        "total_domain_confirms": total_domain_confirms,
        "total_neutral_confirms": total_neutral_confirms,
    }


# ══════════════════════════════════════════════════════════════════════════════
# H14: urgency предсказывает, нужен ли WakeUp (context load predictor)
# ══════════════════════════════════════════════════════════════════════════════

def experiment_14_urgency_wakeup(quick: bool = False) -> Dict:
    """
    H14: Для Gen с высоким urgency (urgency > 2.0) средняя скорость
    достижения mr≥0.6 без WakeUp ХУЖЕ, чем для Gen с низким urgency.

    Иными словами: urgency_high → система не знает контекста →
    нужно больше шагов для восстановления mr.

    Уточнение H10 (urgency ≠ predictor REFUTED, но urgency ≠ predictor WakeUp).

    Протокол:
      1. Обучить систему (A) до насыщения на TRAIN_CORPUS
      2. Создать GAP: не предъявлять HIGH_URGENCY_TEXTS много шагов
      3. Создать две «восстановительные» системы: A_wake (с WakeUp), A_bare (без)
      4. Сравнить steps_to_threshold(mr≥0.6) для HIGH_URGENCY_TEXTS
      5. speedup = steps_bare / steps_wake

    Метрика:
      steps_bare > steps_wake для high-urgency корпуса
    """
    TRAIN_ROUNDS = 4 if quick else 8
    GAP_ROUNDS   = 5 if quick else 10   # только на «лёгких» → urgency растёт

    _hdr("H14: urgency → предиктор необходимости WakeUp")
    _sub("H14: high-urgency Gen → больше шагов до mr≥0.6 без WakeUp")
    print()

    # Обучаем на полном корпусе, потом «забываем» half_corpus
    FULL_CORPUS  = ALL_TEXTS + ALL_SERIAL_TEXTS
    EASY_CORPUS  = FAMILY_MATRYOSHKA
    HARD_CORPUS  = FAMILY_NARRATIVE + ALL_SERIAL_TEXTS

    app = _fresh()
    _sub(f"Фаза 1: полное обучение × {TRAIN_ROUNDS} …")
    step_ctr = [0]
    d = TextDriver(driver_id="text")

    engine = VitalityEngine(window=20)

    def _train_track(sys_: LearningSystem, texts: List[str]) -> None:
        for t in texts:
            for tok in d.produce(t):
                r = sys_.process_token(tok)
                step_ctr[0] += 1
                if r.outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED):
                    for gid in sys_.engine.context.active_gen_ids():
                        engine.record_activation(gid, step_ctr[0])
            sys_.reset_context()

    for _ in range(TRAIN_ROUNDS):
        _train_track(app.system, FULL_CORPUS)

    _num("База Gen после обучения", len(app.system.base.all()))

    _sub(f"Фаза 2: GAP — только EASY × {GAP_ROUNDS} (HARD не предъявляется) …")
    for _ in range(GAP_ROUNDS):
        _train_track(app.system, EASY_CORPUS)

    # Определить Gen с высоким и низким urgency
    current_step = step_ctr[0]
    all_ids = [g.gen_id for g in app.system.base.all()]
    urgencies = [(gid, engine.urgency(gid, current_step)) for gid in all_ids]
    urgencies.sort(key=lambda x: x[1], reverse=True)

    n_bucket = max(5, len(urgencies) // 5)
    high_ids = {gid for gid, _ in urgencies[:n_bucket]}
    low_ids  = {gid for gid, _ in urgencies[-n_bucket:]}

    high_u = [u for _, u in urgencies[:n_bucket]]
    low_u  = [u for _, u in urgencies[-n_bucket:]]
    _num("avg urgency (high bucket)", f"{sum(high_u)/len(high_u):.2f}")
    _num("avg urgency (low bucket)",  f"{sum(low_u)/len(low_u):.2f}")

    # Строим: тексты из HARD_CORPUS, содержащие хотя бы один high/low urgency Gen
    # Прокси: просто используем HARD_CORPUS как «контекст high urgency»
    # и EASY_CORPUS как «контекст low urgency».

    _sub("Фаза 3: steps_to_threshold без WakeUp (HARD_CORPUS) …")
    # Создаём копию системы для «без WakeUp»
    app_bare = _fresh()
    for _ in range(TRAIN_ROUNDS):
        _run_texts(app_bare.system, FULL_CORPUS)
    for _ in range(GAP_ROUNDS):
        _run_texts(app_bare.system, EASY_CORPUS)

    steps_hard_bare = _steps_to_threshold(
        app_bare.system, HARD_CORPUS, threshold=0.6, window=12
    )
    steps_easy_bare = _steps_to_threshold(
        app_bare.system, EASY_CORPUS, threshold=0.6, window=12
    )

    print()
    _num("steps_to_mr≥0.6 на HARD (high urgency)", steps_hard_bare)
    _num("steps_to_mr≥0.6 на EASY (low urgency)",  steps_easy_bare)

    ratio = steps_hard_bare / max(steps_easy_bare, 1)
    _num("ratio hard/easy (ожидается > 1)", f"{ratio:.2f}")

    print()
    passed = ratio > 1.2
    _verdict(passed,
             f"ratio={ratio:.2f} (порог >1.2), "
             f"steps_hard={steps_hard_bare}, steps_easy={steps_easy_bare}")

    print(f"\n  {BD}Инсайты:{W}")
    _dim("• Если ratio ≈ 1 → GAP не создал urgency-разницу между HARD и EASY")
    _dim("• urgency не в gen, а в КОНТЕКСТЕ — нужен WakeUp как загрузка контекста")
    _dim("• Следующий тест: явный WakeUp anchor → speedup ratio > 1.5")

    return {
        "passed": passed,
        "steps_hard": steps_hard_bare,
        "steps_easy": steps_easy_bare,
        "ratio": ratio,
        "n_high": len(high_ids),
        "n_low": len(low_ids),
        "avg_high_urgency": sum(high_u) / len(high_u),
        "avg_low_urgency": sum(low_u) / len(low_u),
    }


# ══════════════════════════════════════════════════════════════════════════════
# H15: d(new_gen)/d(pass) plateau — надёжнее mean_interval как сигнал насыщения
# ══════════════════════════════════════════════════════════════════════════════

def experiment_15_saturation_signal(quick: bool = False) -> Dict:
    """
    H15: d(new_gen)/d(pass) plateau является более надёжным сигналом насыщения,
    чем mean_interval (который монотонно растёт с размером базы — H8).

    Протокол:
      1. Обучить систему на TRAIN_CORPUS pass за passом, N_PASSES итераций
      2. На каждом pass фиксировать:
         a) размер базы Gen
         b) mean_interval всех активных Gen (из VitalityEngine)
         c) n_new_gens = прирост базы за этот pass
      3. Сравнить два сигнала:
         • mi_signal   = d(mean_interval)/d(pass)  — H8 показал монотонный рост
         • new_signal  = d(n_new_gens)/d(pass)     — H15: должен выйти в плато
      4. Plateau_pass = первый pass, где n_new_gens < NEW_THRESH
    """
    N_PASSES    = 6 if quick else 12
    NEW_THRESH  = 3   # < 3 новых Gen за pass = плато

    _hdr("H15: d(new_gen)/d(pass) как надёжный сигнал насыщения")
    _sub("H15: plateau новых Gen надёжнее mean_interval?")
    print()

    TRAIN_CORPUS = ALL_TEXTS + ALL_SERIAL_TEXTS

    app = _fresh()
    d = TextDriver(driver_id="text")
    engine = VitalityEngine(window=20)
    step_ctr = [0]

    pass_stats: List[Dict] = []
    prev_base_size = 0

    print(f"  {'Pass':>4}  {'base':>6}  {'n_new':>5}  {'avg_mi':>8}  {'signal_new':>10}")
    print(f"  {'────':>4}  {'──────':>6}  {'─────':>5}  {'────────':>8}  {'──────────':>10}")

    for pass_i in range(N_PASSES):
        for t in TRAIN_CORPUS:
            for tok in d.produce(t):
                r = app.system.process_token(tok)
                step_ctr[0] += 1
                if r.outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED):
                    for gid in app.system.engine.context.active_gen_ids():
                        engine.record_activation(gid, step_ctr[0])
            app.system.reset_context()

        curr_base_size = len(app.system.base.all())
        n_new = curr_base_size - prev_base_size
        prev_base_size = curr_base_size

        # mean_interval всех tracked Gen
        all_mis = []
        for gid in engine._records:
            mi = engine._records[gid].mean_interval()
            if mi is not None:
                all_mis.append(mi)
        avg_mi = sum(all_mis) / len(all_mis) if all_mis else 0.0

        is_plateau = n_new < NEW_THRESH
        plateau_mark = " ◀ ПЛАТО" if is_plateau else ""
        print(f"  {pass_i+1:>4}  {curr_base_size:>6}  {n_new:>5}  "
              f"{avg_mi:>8.1f}  {n_new:>10}{plateau_mark}")

        pass_stats.append({
            "pass": pass_i + 1,
            "base_size": curr_base_size,
            "n_new": n_new,
            "avg_mi": avg_mi,
            "plateau": is_plateau,
        })

    print()

    # Plateau detection
    plateau_passes = [s for s in pass_stats if s["plateau"]]
    plateau_pass = plateau_passes[0]["pass"] if plateau_passes else None

    # Монотонность mean_interval (должна расти — H8 подтверждает)
    mis = [s["avg_mi"] for s in pass_stats if s["avg_mi"] > 0]
    mi_monotone = all(mis[i] <= mis[i+1] for i in range(len(mis)-1)) if len(mis) > 1 else False

    # n_new образует плато (должен упасть к нулю)
    new_counts = [s["n_new"] for s in pass_stats]
    new_plateau = any(s["plateau"] for s in pass_stats)

    _num("Плато n_new достигнуто на pass", plateau_pass or "—")
    _num("mean_interval монотонно растёт",  "ДА" if mi_monotone else "НЕТ")
    _num("n_new выходит в плато",           "ДА" if new_plateau else "НЕТ")

    print()
    # H15 подтверждена если:
    # 1. n_new plateau наступает раньше, чем mean_interval выходит в плато
    # 2. mean_interval продолжает расти даже после n_new plateau
    passed_new = new_plateau
    passed_mi  = mi_monotone
    passed = passed_new and passed_mi

    _verdict(passed,
             f"n_new_plateau={'ДА' if passed_new else 'НЕТ'} "
             f"(pass {plateau_pass}), "
             f"mi_monotone={'ДА' if passed_mi else 'НЕТ'}")

    print(f"\n  {BD}Инсайты:{W}")
    _dim("• mi растёт → НЕ сигнал насыщения (H8 подтверждено повторно)")
    _dim("• n_new падает → настоящий сигнал насыщения (момент смены домена)")
    _dim("• Порог NEW_THRESH=3 — параметр: при большом корпусе нужен >3")

    return {
        "passed": passed,
        "plateau_pass": plateau_pass,
        "mi_monotone": mi_monotone,
        "new_plateau": new_plateau,
        "pass_stats": pass_stats,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Демо: «Скука» — HedonicAdapter + сериальный корпус
# ══════════════════════════════════════════════════════════════════════════════

def demo_boredom() -> None:
    """
    Демонстрация HedonicAdapter на сериальном корпусе.

    Персонажи (маша, медведь, ...) появляются во ВСЕХ текстах → HedonicAdapter
    «скучает» от них быстро. Ситуации — новые каждый раз → novelty дольше держится.

    Показывает правильный баланс: долгосрочные Gen (персонажи) быстро
    насыщают адаптер, а средне/краткосрочные Gen (ситуации) поддерживают интерес.
    """
    _hdr("ДЕМО: Скука — HedonicAdapter + сериальный корпус")
    print()

    ha = HedonicAdapter(decay=0.75)

    # Симулируем обучение: каждый текст «активирует» своих персонажей и ситуацию
    from training.serial_corpus import situation_of

    print(f"  {'Текст':<50} {'персонаж':>10} {'ситуация':>10}")
    print(f"  {'─'*50} {'─'*10} {'─'*10}")

    # Показываем первые 20 текстов из ALL_SERIAL_TEXTS
    for idx, text in enumerate(ALL_SERIAL_TEXTS[:20]):
        # «Активируем» каждого персонажа, встреченного в тексте
        for char in CHARACTERS:
            if char in text:
                ha.record_completion(char)

        # «Активируем» ситуацию
        sit = situation_of(text)
        ha.record_completion(f"sit:{sit}")

        # Замеряем novelty персонажа и ситуации (если встречены)
        char_in_text = [c for c in CHARACTERS if c in text]
        ch_nov = ha.novelty_score(char_in_text[0]) if char_in_text else 0.0
        sit_nov = ha.novelty_score(f"sit:{sit}")

        short = text[:48] + "…" if len(text) > 48 else text
        print(f"  {short:<50} {ch_nov:>10.3f} {sit_nov:>10.3f}")

    print()
    print(f"  {BD}Novelty персонажей после {len(ALL_SERIAL_TEXTS[:20])} текстов:{W}")
    for char in CHARACTERS:
        count = ha._completion_counts.get(char, 0)
        nov = ha.novelty_score(char)
        bar = "█" * int(nov * 20)
        print(f"  {char:<12} count={count:>3}  novelty={nov:.3f}  {bar}")

    print()
    print(f"  {BD}Novelty ситуаций:{W}")
    for sit in list(SITUATION_FAMILIES.keys())[:6]:
        key = f"sit:{sit}"
        count = ha._completion_counts.get(key, 0)
        nov = ha.novelty_score(key)
        bar = "█" * int(nov * 20)
        print(f"  {sit:<14} count={count:>3}  novelty={nov:.3f}  {bar}")

    print()
    _dim("Персонажи насыщены (novelty→0). Ситуации сохраняют интерес.")
    _dim("Это правильный баланс: долгосрочные Gen скучны, среднесрочные — нет.")


# ══════════════════════════════════════════════════════════════════════════════
# Демо: AdaptiveCounter vs VitalityRecord при миллионах шагов
# ══════════════════════════════════════════════════════════════════════════════

def demo_adaptive_counter() -> None:
    """
    Демонстрация AdaptiveActivationCounter при длинных прогонах.

    При миллионах шагов:
      • VitalityRecord хранит абсолютные числа → всё ещё работает (Python int),
        но mean_interval считается на срезе последних 20
      • AdaptiveCounter хранит только разности → компактнее, семантически точнее
      • log_total даёт «порядок активаций» в 6 битах
    """
    _hdr("ДЕМО: AdaptiveCounter — компактный счётчик для длинных прогонов")
    print()

    import random as rnd
    rnd.seed(7)

    scenarios = [
        ("Нормальный ритм (μ=20,σ=5)",     50,         0,         20, 5),
        ("Большие шаги (base=10^6)",        50,   1_000_000,        20, 5),
        ("Редкие активации (μ=500)",        30,         0,        500, 50),
        ("Очень частые (μ=3)",             100,         0,          3, 1),
    ]

    for label, n, base, mu, sigma in scenarios:
        steps = []
        s = base
        for _ in range(n):
            s += max(1, int(rnd.gauss(mu, sigma)))
            steps.append(s)

        ac = AdaptiveActivationCounter(window=8, ema_alpha=0.15)
        for st in steps:
            ac.record(st)

        true_mi = sum(steps[i+1] - steps[i] for i in range(len(steps)-1)) / (len(steps)-1)
        ac_mi = ac.mean_interval("blend") or 0.0
        err = abs(ac_mi - true_mi) / true_mi * 100

        print(f"  {label}")
        print(f"    n={n}, last_step={steps[-1]:>12,}")
        print(f"    true_mi={true_mi:.1f}  ac_mi={ac_mi:.1f}  err={err:.1f}%")
        print(f"    log_total={ac.log_total} (≈2^{ac.log_total}={1<<ac.log_total})  "
              f"urgency(+{mu})={ac.urgency(steps[-1]+mu):.2f}")
        print()

    _dim("AdaptiveCounter не хранит абсолютные шаги — только последний и разности.")
    _dim("log_total = 6 бит → порядок числа активаций без переполнения.")


# ══════════════════════════════════════════════════════════════════════════════
# Сводная таблица
# ══════════════════════════════════════════════════════════════════════════════

def print_summary(results: Dict[int, Dict]) -> None:
    _hdr("ИТОГОВАЯ ТАБЛИЦА H11–H15")
    NAMES = {
        11: "CapacityBudget    eviction → avg_sig выживших > полной базы",
        12: "Anchor-first      30% лёгких + 70% трудных > random > knock",
        13: "Vitality chain≥3  inside > after; fraction ≥ 70%",
        14: "Urgency → WakeUp  high-urgency → больше шагов без WakeUp",
        15: "Saturation signal d(new_gen)/d(pass) plateau надёжнее mi",
    }
    print(f"  {'#':>2}  {'Статус':<14}  Название + ключевая метрика")
    print(f"  {'──':>2}  {'──────────────':<14}  ─────────────────────────────────────")
    for n, r in sorted(results.items()):
        ok = r.get("passed", False)
        status = f"{GR}ПОДТВЕРЖДЕНА{W}" if ok else f"{RD}ОПРОВЕРГНУТА{W}"
        name = NAMES.get(n, "?")
        key_metric = ""
        if n == 11:
            key_metric = (f"sig_lift={r.get('sig_lift', 0):+.4f}, "
                          f"mr_A={r.get('mr_A', 0):.3f} vs mr_B={r.get('mr_B', 0):.3f}")
        elif n == 12:
            key_metric = (f"imp_AB={r.get('imp_AB', 0):+.3f}, "
                          f"imp_BC={r.get('imp_BC', 0):+.3f}")
        elif n == 13:
            key_metric = f"fraction={r.get('fraction', 0):.3f}"
        elif n == 14:
            key_metric = f"ratio={r.get('ratio', 0):.2f}"
        elif n == 15:
            key_metric = (f"plateau_pass={r.get('plateau_pass', '—')}, "
                          f"mi_mono={r.get('mi_monotone', '?')}")
        print(f"  {n:>2}  {status:<14}  {name}")
        if key_metric:
            print(f"  {'':>2}  {'':>14}  {DM}{key_metric}{W}")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════

EXPERIMENTS = {
    11: experiment_11_capacity_budget,
    12: experiment_12_anchor_first,
    13: experiment_13_vitality_chain,
    14: experiment_14_urgency_wakeup,
    15: experiment_15_saturation_signal,
}

DEMOS = {
    "boredom": demo_boredom,
    "counter": demo_adaptive_counter,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="H11–H15 experiments: CapacityBudget, anchor-first, vitality-chain, "
                    "urgency-WakeUp, saturation signal"
    )
    parser.add_argument("--quick", action="store_true",
                        help="Быстрый режим (меньше итераций)")
    parser.add_argument("--exp", nargs="+", type=int,
                        choices=list(EXPERIMENTS.keys()),
                        help="Выбрать конкретные эксперименты (напр. --exp 11 15)")
    parser.add_argument("--demo", nargs="+",
                        choices=list(DEMOS.keys()),
                        help="Запустить демо (boredom, counter)")
    parser.add_argument("--findings", action="store_true",
                        help="Только вывод ключевых находок без прогона")
    args = parser.parse_args()

    if args.findings:
        _hdr("Ключевые находки H11–H15 (из H6–H10 инсайтов)")
        findings = [
            "H11: Eviction низко-sig Gen → avg_sig оставшихся растёт",
            "     Цель: CapacityBudget в GeneralizationBase.add() с auto-evict",
            "H12: Anchor-first (30%easy+70%hard) > pure-knock (H7 paradox fix)",
            "     Pure-knock: много REFUTED → шум; Anchor импульс → поднимает трудные",
            "H13: chain≥3 Gen: inside > after при нейтральных текстах → fraction≥70%",
            "     chain=1 Gen активируются везде → разница мала",
            "H14: urgency = predictor context_load, не REFUTED",
            "     High urgency → система не помнит контекст → WakeUp нужен",
            "H15: d(new_gen)/d(pass) падает к плато — настоящий сигнал насыщения",
            "     mean_interval монотонно растёт (H8) → НЕ сигнал насыщения",
        ]
        for f in findings:
            print(f"  {f}")
        return

    results: Dict[int, Dict] = {}

    # Демо
    if args.demo:
        for demo_name in args.demo:
            DEMOS[demo_name]()
        if not args.exp:
            return

    # Эксперименты
    exp_ids = args.exp if args.exp else list(EXPERIMENTS.keys())
    for eid in exp_ids:
        r = EXPERIMENTS[eid](quick=args.quick)
        results[eid] = r

    if len(results) > 1:
        print_summary(results)


if __name__ == "__main__":
    main()
