"""
Серия H6–H10: следующий пул гипотез о витальности и обучении.

H6  WakeUpRestorer на большой базе (Jack × 200) даёт speedup > 1.5x при gap ≥ 100
H7  knock-curriculum (сначала самые «забытые» тексты) восстанавливает mr на 30%+
H8  Точка перегиба кривой роста Gen совпадает с падением mean_interval активных Gen
H9  vitality(INSIDE_SENTENCE) > vitality(AFTER_SENTENCE) для топ-Gen по значимости
H10 urgency Gen коррелирует с долей REFUTED при повторном предъявлении

Запуск:
    py -X utf8 training/h6_h10_experiments.py
    py -X utf8 training/h6_h10_experiments.py --quick
    py -X utf8 training/h6_h10_experiments.py --exp 6 7 8
    py -X utf8 training/h6_h10_experiments.py --findings
"""
from __future__ import annotations

import sys, os, math, random, argparse
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import CoreApplication
from core.learning import LearningSystem
from core.algorithm import StepOutcome
from curriculum.debug_session import DebugSession
from drivers.text_driver import TextDriver
from training.rich_corpus import (
    FAMILY_MATRYOSHKA, FAMILY_NARRATIVE, FAMILY_RHYTHM, ALL_TEXTS,
)

# ─── Джек: 8 строф ────────────────────────────────────────────────────────────
JACK_VERSES = [
    "вот дом который построил джек",
    "вот пшеница которая в тёмном чулане хранится в доме который построил джек",
    "вот синица которая часто ворует пшеницу которая в тёмном чулане хранится "
    "в доме который построил джек",
    "вот кошка которая пугает и ловит синицу которая часто ворует пшеницу "
    "которая в тёмном чулане хранится в доме который построил джек",
    "вот пёс без хвоста который за шиворот треплет кошку которая пугает "
    "и ловит синицу которая часто ворует пшеницу в доме который построил джек",
    "вот корова безрогая которая бодает пса без хвоста который треплет кошку "
    "которая ловит синицу которая ворует пшеницу в доме который построил джек",
    "вот старушка суровая которая доит корову безрогую которая бодает пса "
    "который треплет кошку которая ловит синицу в доме который построил джек",
    "вот ленивый и жирный пастух который бранит старушку которая доит корову "
    "которая бодает пса который треплет кошку в доме который построил джек",
]

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
def _warn(t: str) -> None: print(f"  {AM}⚠ {t}{W}")
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
    """Прогнать тексты, вернуть список исходов."""
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
    """Прогнать один текст, вернуть match_rate (обучает систему)."""
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
    """Вернуть номер токена, на котором скользящий mr впервые ≥ threshold."""
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
    """Коэффициент ранговой корреляции Спирмена."""
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
# H6: WakeUpRestorer на большой базе (Jack × N) даёт speedup > 1.5x при gap ≥ 100
# ══════════════════════════════════════════════════════════════════════════════

def experiment_6_wakeup_large(quick: bool = False) -> Dict:
    """
    H6: После обучения системы на Jack × 200 прогонов WakeUpRestorer даёт
    speedup > 1.5x при gap ≥ 100.

    Контекст: Эксп.2 (vitality_experiments) показал speedup=1.00x — потому что
    база была < 20 Gen. На большой базе (> 500 Gen) якорный поиск становится
    осмысленным: система находит meta_* Gen с высокой значимостью.

    Протокол:
      - Фаза обучения: N_PASSES полных прогонов JACK_VERSES (8 строф)
      - Тест COLD: reset_context() → steps_to_60 на 3 строфах
      - Тест WARM gap=10 / 50 / 100: WakeUpRestorer → steps_to_60

    Метрики:
      speedup_10, speedup_50, speedup_100 = steps_cold / steps_warm
    """
    N_PASSES = 25 if quick else 200
    _hdr(f"H6: WakeUpRestorer на большой базе (Jack × {N_PASSES} прогонов)")
    _sub("H6: speedup > 1.5x при gap ≥ 100 на базе > 200 Gen")
    print()

    app = _fresh()
    sys_ = app.system
    session = DebugSession(app)

    _sub(f"Фаза обучения: {N_PASSES} прогонов × 8 строф …")
    for i in range(N_PASSES):
        _run_texts(sys_, JACK_VERSES)
        if (i + 1) % max(1, N_PASSES // 5) == 0:
            _dim(f"  Pass {i+1}/{N_PASSES}: {len(sys_.base.all())} Gen")

    base_size = len(sys_.base.all())
    vstats = sys_.vitality.stats()
    _num("Gen в базе", base_size)
    _num("Tracked Gen (vitality)", vstats["tracked_gens"])
    _num("knock_candidates (urgency ≥ 2.0)", vstats["critical_count"])
    print()

    TEST_TEXTS = JACK_VERSES[:3]

    # Холодный старт
    sys_.reset_context()
    steps_cold = _steps_to_threshold(sys_, TEST_TEXTS, 0.6)
    _num("steps_cold (нет восстановления)", steps_cold)

    results: Dict[int, Dict] = {}
    for gap in [10, 50, 100]:
        sys_.reset_context()
        anchor = session.wake_up(step_gap=gap)
        steps_warm = _steps_to_threshold(sys_, TEST_TEXTS, 0.6)
        speedup = steps_cold / steps_warm if steps_warm > 0 else float("inf")
        results[gap] = {"anchor": anchor, "steps_warm": steps_warm, "speedup": speedup}
        _num(f"  gap={gap:3d}  anchor / steps_warm / speedup",
             f"{(anchor or '—')[:12]} / {steps_warm} / {speedup:.2f}x")

    print()
    speedup_100 = results[100]["speedup"]
    passed = speedup_100 > 1.5 and base_size > 200

    _verdict(passed,
             f"speedup_100={speedup_100:.2f}x (порог >1.5x), "
             f"base_size={base_size}")

    print(f"\n  {BD}Следующие вопросы:{W}")
    _dim("Q1: Как speedup зависит от N_PASSES (50/100/200)?")
    _dim("Q2: Какой минимальный base_size даёт speedup > 1.5x?")
    _dim("Q3: Даёт ли загрузка нескольких якорей (N-anchor restore) ещё больше?")

    return {
        "passed": passed,
        "base_size": base_size,
        "steps_cold": steps_cold,
        "results": results,
    }


# ══════════════════════════════════════════════════════════════════════════════
# H7: knock-curriculum восстанавливает mr «забытых» текстов на 30%+ быстрее
# ══════════════════════════════════════════════════════════════════════════════

def experiment_7_knock_curriculum(quick: bool = False) -> Dict:
    """
    H7: После «забывания» корпуса B (не предъявляли N раундов) curriculum,
    приоритизирующий тексты с наиболее низким текущим match_rate (knock-порядок),
    восстанавливает средний mr(B) на 30%+ быстрее случайного порядка.

    Логика: учитель «возвращается к пройденному, но не усвоенному».
    Knock-curriculum — формализация этой практики.

    Протокол:
      1. Обучить обе системы (knock / random) на A+B, TRAIN_ROUNDS раундов
      2. «Забыть» B: FORGET_ROUNDS раундов только на A
      3. Замерить baseline mr(B) для каждого текста
      4. KNOCK: сортировать B по mr_baseline (низший первый), RESTORE_ROUNDS раундов
         RANDOM: перемешать B случайно, RESTORE_ROUNDS раундов
      5. Финальный mr(B): knock vs random

    Метрика:
      improvement = (mr_knock - mr_random) / max(1 - mr_random, 0.01)
    """
    TRAIN_ROUNDS   = 5 if quick else 8
    FORGET_ROUNDS  = 3 if quick else 6
    RESTORE_ROUNDS = 3 if quick else 5

    _hdr("H7: knock-curriculum восстанавливает «забытое» на 30%+ быстрее")
    _sub("H7: приоритет самым забытым текстам → mr(B) восстанавливается эффективнее")
    print()

    def _build_base() -> CoreApplication:
        a = _fresh()
        for _ in range(TRAIN_ROUNDS):
            _run_texts(a.system, FAMILY_MATRYOSHKA + FAMILY_NARRATIVE)
        return a

    _sub(f"Фаза 1: общее обучение A+B × {TRAIN_ROUNDS} раундов (2 системы) …")
    app_knock  = _build_base()
    app_random = _build_base()
    _num("Gen (knock-система)",  len(app_knock.system.base.all()))
    _num("Gen (random-система)", len(app_random.system.base.all()))
    print()

    _sub(f"Фаза 2: забывание — только A × {FORGET_ROUNDS} раундов …")
    for _ in range(FORGET_ROUNDS):
        _run_texts(app_knock.system,  FAMILY_MATRYOSHKA)
        _run_texts(app_random.system, FAMILY_MATRYOSHKA)

    _sub("Замер baseline match_rate на B (FAMILY_NARRATIVE) …")
    baseline_k = {t: _text_mr(app_knock.system,  t) for t in FAMILY_NARRATIVE}
    baseline_r = {t: _text_mr(app_random.system, t) for t in FAMILY_NARRATIVE}
    avg_base = sum(baseline_k.values()) / len(baseline_k)
    _num("avg_mr(B) после забывания", f"{avg_base:.3f}")

    worst = sorted(baseline_k.items(), key=lambda x: x[1])[:3]
    _dim("Топ-3 самых «забытых»:")
    for txt, mr in worst:
        _dim(f"    mr={mr:.2f}  «{txt[:55]}»")
    print()

    _sub(f"Фаза 3: восстановление × {RESTORE_ROUNDS} раундов …")
    knock_order  = sorted(FAMILY_NARRATIVE, key=lambda t: baseline_k[t])
    random_order = list(FAMILY_NARRATIVE)
    random.seed(42)
    random.shuffle(random_order)

    for _ in range(RESTORE_ROUNDS):
        _run_texts(app_knock.system,  knock_order)
        _run_texts(app_random.system, random_order)

    final_k = [_text_mr(app_knock.system,  t) for t in FAMILY_NARRATIVE]
    final_r = [_text_mr(app_random.system, t) for t in FAMILY_NARRATIVE]
    mr_knock  = sum(final_k) / len(final_k)
    mr_random = sum(final_r) / len(final_r)
    improvement = (mr_knock - mr_random) / max(1.0 - mr_random, 0.01)

    _num("avg_mr(B) KNOCK (после восстановления)",  f"{mr_knock:.3f}")
    _num("avg_mr(B) RANDOM (после восстановления)", f"{mr_random:.3f}")
    _num("Абсолютное улучшение knock vs random",    f"{mr_knock - mr_random:+.3f}")
    _num("Относительное улучшение",                 f"{improvement:+.1%}")
    print()

    passed = improvement >= 0.30

    _verdict(passed,
             f"improvement={improvement:+.1%} (порог ≥30%), "
             f"knock={mr_knock:.3f} vs random={mr_random:.3f}")

    print(f"\n  {BD}Следующие вопросы:{W}")
    _dim("Q1: Зависит ли эффект от длины FORGET_ROUNDS (3/6/12)?")
    _dim("Q2: Оптимален ли «только худшие 50%» vs «все по mr-order»?")
    _dim("Q3: Как urgency-сигнал соотносится с mr_baseline — можно ли заменить?")

    return {
        "passed": passed,
        "mr_knock": mr_knock,
        "mr_random": mr_random,
        "improvement": improvement,
        "avg_baseline": avg_base,
    }


# ══════════════════════════════════════════════════════════════════════════════
# H8: Точка перегиба кривой роста Gen совпадает с падением mean_interval
# ══════════════════════════════════════════════════════════════════════════════

def experiment_8_growth_inflection(quick: bool = False) -> Dict:
    """
    H8: На кривой числа Gen (прогон → count) есть точка перегиба.
    В окрестности этой точки средний mean_interval активных Gen снижается:
    система «насытилась» новыми Gen и начинает глубже отрабатывать старые.

    Протокол:
      - Jack × N_PASSES прогонов; после каждого — снапшот
      - снапшот: gen_count + avg mean_interval (Gen с ≥ 5 активациями)
      - d1[i] = count[i+1] - count[i]  (скорость роста)
      - d2[i] = d1[i+1] - d1[i]        (ускорение/замедление)
      - inflection_pass = argmin(d2)    (где рост резко замедлился)
      - mi_before = avg mean_interval за 2 прогона до перегиба
      - mi_after  = avg mean_interval за 2 прогона после перегиба
      - mi_drop = (mi_after - mi_before) / mi_before  (ожидаем < -10%)

    Метрики:
      inflection_pass, mi_before, mi_after, mi_drop
    """
    N_PASSES = 20 if quick else 60
    _hdr(f"H8: Перегиб кривой роста Gen (Jack × {N_PASSES} прогонов)")
    _sub("H8: в точке перегиба mean_interval активных Gen снижается (знание уплотняется)")
    print()

    app = _fresh()
    sys_ = app.system

    snap_count: List[int]  = []
    snap_mi:    List[float] = []  # avg mean_interval Gen с ≥ 5 точками

    _sub(f"Обучение с замерами после каждого прогона …")
    for i in range(N_PASSES):
        _run_texts(sys_, JACK_VERSES)

        count = len(sys_.base.all())
        intervals = [
            r.mean_interval()
            for r in sys_.vitality._records.values()
            if r.mean_interval() is not None and len(r.activation_steps) >= 5
        ]
        avg_mi = sum(intervals) / len(intervals) if intervals else 0.0
        snap_count.append(count)
        snap_mi.append(avg_mi)

        if (i + 1) % max(1, N_PASSES // 5) == 0:
            _dim(f"  Pass {i+1:3d}/{N_PASSES}:  count={count:5d}  "
                 f"avg_mi={avg_mi:6.1f}  history_gens={len(intervals)}")

    print()

    # Первая и вторая разности
    d1 = [snap_count[i+1] - snap_count[i] for i in range(len(snap_count)-1)]
    d2 = [d1[i+1] - d1[i] for i in range(len(d1)-1)] if len(d1) > 1 else [0]

    # Точка перегиба: argmin(d2) — где прирост замедлился сильнее всего
    inflection = d2.index(min(d2)) + 1  # +1: d2[i] = change at pass i+1

    # Ограничить диапазон для сравнения mi
    lo = max(0, inflection - 2)
    hi = min(N_PASSES - 1, inflection + 2)
    mi_before = snap_mi[lo]
    mi_after  = snap_mi[hi]
    mi_drop   = (mi_after - mi_before) / max(mi_before, 0.01)

    growth_before = (snap_count[inflection] -
                     snap_count[max(0, inflection - 3)])
    growth_after  = (snap_count[min(N_PASSES-1, inflection + 3)] -
                     snap_count[inflection])

    _num("Точка перегиба (прогон №)",             inflection + 1)
    _num("Gen count на перегибе",                  snap_count[inflection])
    _num("Прирост count ДО перегиба (3 прогона)", growth_before)
    _num("Прирост count ПОСЛЕ перегиба (3 прогона)", growth_after)
    _num("mean_interval ДО перегиба",              f"{mi_before:.1f}")
    _num("mean_interval ПОСЛЕ перегиба",           f"{mi_after:.1f}")
    _num("Изменение mean_interval",                f"{mi_drop:+.1%}")
    print()

    # Подтверждено: рост замедлился И mean_interval упал > 10%
    growth_slowed = growth_after < growth_before
    mi_fell       = mi_drop < -0.10

    passed = growth_slowed and mi_fell

    _verdict(passed,
             f"рост замедлился: {growth_before}→{growth_after} ({growth_slowed}), "
             f"mi_drop={mi_drop:+.1%} (ожидали < -10%)")

    print(f"\n  {BD}Следующие вопросы:{W}")
    _dim("Q1: Точка перегиба — свойство алгоритма или размера корпуса?")
    _dim("Q2: Как меняется inflection_pass при разных corpus (Jack vs narrative)?")
    _dim("Q3: Можно ли использовать mi_drop как сигнал «насыщения» для LLM-учителя?")

    return {
        "passed": passed,
        "inflection_pass": inflection,
        "mi_before": mi_before,
        "mi_after": mi_after,
        "mi_drop": mi_drop,
        "snap_count": snap_count[:N_PASSES],
    }


# ══════════════════════════════════════════════════════════════════════════════
# H9: vitality(INSIDE_SENTENCE) > vitality(AFTER_SENTENCE) для топ-Gen
# ══════════════════════════════════════════════════════════════════════════════

def experiment_9_vitality_timing(quick: bool = False) -> Dict:
    """
    H9: Витальность топ-Gen (sig ≥ 0.6) выше сразу после обработки их
    «родного» текста, чем после 5 нейтральных текстов.

    Семантика: vitality = «живость прямо сейчас», а не просто значимость.
    Активация → urgency падает → vitality растёт.
    Нейтральные тексты → Gen не активируется → urgency растёт → vitality падает.

    Протокол:
      1. Обучить на FAMILY_MATRYOSHKA + FAMILY_RHYTHM, TRAIN_ROUNDS раундов
      2. Выбрать топ-N Gen (sig ≥ 0.6, chain_len ≤ 4)
      3. Для каждого топ-Gen:
           a. Обработать «родной» текст (FAMILY_MATRYOSHKA[0])
           b. Зафиксировать urgency сразу после (vitality_inside)
           c. Обработать 5 нейтральных текстов (из FAMILY_RHYTHM — без матрёшки)
           d. Зафиксировать urgency (vitality_after)
      4. Сравнить avg(vitality_inside) vs avg(vitality_after)
         + fraction_inside_gt_after = доля Gen с v_inside > v_after

    Метрики:
      avg_vitality_inside, avg_vitality_after, fraction_inside_gt_after
    """
    TRAIN_ROUNDS = 8 if quick else 15
    N_TOP = 10
    NEUTRAL_TEXTS = [
        "день ночь день ночь день ночь день ночь",
        "прилив отлив прилив отлив прилив отлив",
        "работа отдых работа отдых работа отдых",
        "включилось выключилось включилось выключилось",
        "рассвет закат рассвет закат рассвет закат",
    ]

    _hdr("H9: vitality(INSIDE) > vitality(AFTER) для топ-Gen")
    _sub("H9: витальность отражает активную вовлечённость, а не только значимость")
    print()

    app = _fresh()
    sys_ = app.system

    _sub(f"Обучение: FAMILY_MATRYOSHKA × {TRAIN_ROUNDS} + FAMILY_RHYTHM × {TRAIN_ROUNDS//2} …")
    for _ in range(TRAIN_ROUNDS):
        _run_texts(sys_, FAMILY_MATRYOSHKA)
    for _ in range(TRAIN_ROUNDS // 2):
        _run_texts(sys_, FAMILY_RHYTHM)

    all_gens = sys_.base.all()
    top_gens = sorted(
        [g for g in all_gens
         if g.significance >= 0.6 and 1 <= len(g.feature_chain) <= 4],
        key=lambda g: g.significance,
        reverse=True,
    )[:N_TOP]

    _num("Gen в базе",                          len(all_gens))
    _num(f"Топ-{N_TOP} (sig ≥ 0.6, len ≤ 4)", len(top_gens))
    print()

    if not top_gens:
        _warn("Нет подходящих Gen — пропускаем")
        return {"passed": None, "msg": "no_top_gens"}

    d = TextDriver(driver_id="text")
    vitality_inside: List[float] = []
    vitality_after:  List[float] = []

    NATIVE_TEXT   = FAMILY_MATRYOSHKA[0]

    for gen in top_gens:
        gid = gen.gen_id
        sig = gen.significance

        # a) обработать родной текст
        for tok in d.produce(NATIVE_TEXT):
            sys_.process_token(tok)
        sys_.reset_context()

        # b) urgency сразу после родного текста
        rec = sys_.vitality._records.get(gid)
        if rec is None or rec.last_step() is None:
            # Gen не активировался в этом тексте — считаем vitality = sig (нет истории)
            vitality_inside.append(sig)
        else:
            u = rec.urgency(sys_.engine.step_count)
            vitality_inside.append(sig * math.exp(-max(0.0, u - 1.0)))

        # c) обработать 5 нейтральных текстов
        for nt in NEUTRAL_TEXTS:
            for tok in d.produce(nt):
                sys_.process_token(tok)
            sys_.reset_context()

        # d) urgency после нейтральных
        rec2 = sys_.vitality._records.get(gid)
        if rec2 is None or rec2.last_step() is None:
            vitality_after.append(sig)
        else:
            u2 = rec2.urgency(sys_.engine.step_count)
            vitality_after.append(sig * math.exp(-max(0.0, u2 - 1.0)))

    avg_inside = sum(vitality_inside) / len(vitality_inside)
    avg_after  = sum(vitality_after)  / len(vitality_after)
    fraction   = sum(1 for vi, va in zip(vitality_inside, vitality_after)
                     if vi > va) / len(top_gens)

    _num("avg vitality_inside (сразу после родного текста)", f"{avg_inside:.4f}")
    _num("avg vitality_after  (после 5 нейтральных)",       f"{avg_after:.4f}")
    _num("Доля Gen: vitality_inside > vitality_after",       f"{fraction:.1%}")
    print()

    # Примеры
    pairs = list(zip(vitality_inside, vitality_after, top_gens))
    _dim("Примеры (топ-3 по разнице):")
    for vi, va, g in sorted(pairs, key=lambda x: x[0]-x[1], reverse=True)[:3]:
        _dim(f"    sig={g.significance:.2f}  inside={vi:.4f}  after={va:.4f}  "
             f"chain={len(g.feature_chain)}")

    passed = fraction >= 0.7 and avg_inside > avg_after

    _verdict(passed,
             f"fraction={fraction:.1%} (порог ≥70%), "
             f"inside={avg_inside:.4f} > after={avg_after:.4f}: {avg_inside > avg_after}")

    print(f"\n  {BD}Следующие вопросы:{W}")
    _dim("Q1: Через сколько нейтральных текстов vitality падает ниже 50% от inside?")
    _dim("Q2: Есть ли разница между chain=1 (трансцендентные) и chain=3-4 (конкретные)?")
    _dim("Q3: Можно ли vitality_drop использовать как сигнал для запуска EXPLORE?")

    return {
        "passed": passed,
        "avg_vitality_inside": avg_inside,
        "avg_vitality_after":  avg_after,
        "fraction_inside_gt_after": fraction,
        "n_top_gens": len(top_gens),
    }


# ══════════════════════════════════════════════════════════════════════════════
# H10: urgency Gen коррелирует с долей REFUTED при повторном предъявлении
# ══════════════════════════════════════════════════════════════════════════════

def experiment_10_urgency_refuted(quick: bool = False) -> Dict:
    """
    H10: Тексты, чьи Gen набрали высокий urgency в период «тёмного окна»
    (когда эти тексты не предъявлялись), дают больше REFUTED при повторном
    предъявлении.

    Идея: urgency = сигнал «опоздания» Gen. Если Gen опоздал, значит его
    цепочка давно не была в контексте → при предъявлении текста система
    не предсказывает его фичи → REFUTED.

    Протокол:
      1. Обучить на ALL_TEXTS × TRAIN_ROUNDS (все семьи)
      2. «Тёмное окно»: DARK_ROUNDS только на FAMILY_MATRYOSHKA + FAMILY_RHYTHM
         (FAMILY_NARRATIVE = «тёмная зона»)
      3. Снапшот urgency: для каждого Gen, которого не активировали в тёмном окне
      4. Re-presentation FAMILY_NARRATIVE: замерить refuted_rate каждого текста
         + avg urgency Gen, активированных при обработке этого текста
      5. Корреляция Спирмена: text_urgency ↔ text_refuted_rate

    Метрики:
      spearman_r, avg_urgency_dark, avg_refuted_rate
    """
    TRAIN_ROUNDS = 6 if quick else 10
    DARK_ROUNDS  = 4 if quick else 8

    _hdr("H10: urgency ↔ доля REFUTED при повторном предъявлении")
    _sub("H10: высокий urgency у Gen → больше REFUTED на их текстах при re-presentation")
    print()

    app = _fresh()
    sys_ = app.system

    _sub(f"Фаза 1: обучение на ALL_TEXTS × {TRAIN_ROUNDS} …")
    for _ in range(TRAIN_ROUNDS):
        _run_texts(sys_, ALL_TEXTS)
    _num("Gen после общего обучения", len(sys_.base.all()))
    print()

    _sub(f"Фаза 2: тёмное окно для NARRATIVE ({DARK_ROUNDS} раундов без неё) …")
    LIGHT_TEXTS = FAMILY_MATRYOSHKA + FAMILY_RHYTHM
    for _ in range(DARK_ROUNDS):
        _run_texts(sys_, LIGHT_TEXTS)

    vstats = sys_.vitality.stats()
    _num("knock_candidates (urgency ≥ 2.0)", vstats["critical_count"])
    _num("avg_urgency",                      f"{vstats['avg_urgency']:.2f}")
    print()

    # Снапшот urgency всех Gen после тёмного окна
    step_dark_end = sys_.engine.step_count
    urgency_snap: Dict[str, float] = {
        gid: rec.urgency(step_dark_end)
        for gid, rec in sys_.vitality._records.items()
    }

    # Фаза 3: re-presentation FAMILY_NARRATIVE
    _sub("Фаза 3: re-presentation NARRATIVE + замер корреляции …")
    d = TextDriver(driver_id="text")

    per_text_urgency: List[float] = []
    per_text_refuted: List[float] = []

    for text in FAMILY_NARRATIVE:
        step_before = sys_.engine.step_count
        outcomes: List[StepOutcome] = []

        for tok in d.produce(text):
            outcomes.append(sys_.process_token(tok).outcome)
        sys_.reset_context()

        step_after = sys_.engine.step_count

        # Urgency: среднее urgency_snap[gid] для Gen, активированных во время
        # re-presentation (last_step обновился в [step_before+1, step_after])
        activated: List[str] = [
            gid for gid, rec in sys_.vitality._records.items()
            if rec.last_step() is not None
            and step_before < rec.last_step() <= step_after
        ]
        text_urgency = (sum(urgency_snap.get(gid, 0.0) for gid in activated)
                        / len(activated) if activated else 0.0)
        text_refuted = (sum(1 for o in outcomes if o == StepOutcome.REFUTED)
                        / max(len(outcomes), 1))

        per_text_urgency.append(text_urgency)
        per_text_refuted.append(text_refuted)

    r = _spearman(per_text_urgency, per_text_refuted)
    avg_u = sum(per_text_urgency) / len(per_text_urgency)
    avg_r = sum(per_text_refuted) / len(per_text_refuted)

    _num("avg urgency (активированные Gen при re-presentation)", f"{avg_u:.2f}")
    _num("avg refuted_rate на NARRATIVE",                        f"{avg_r:.3f}")
    _num("Spearman r(urgency → refuted_rate)",                   f"{r:+.3f}")
    print()

    # Вывести топ-3 и боттом-3 по refuted_rate
    pairs = sorted(zip(per_text_urgency, per_text_refuted, FAMILY_NARRATIVE),
                   key=lambda x: x[1], reverse=True)
    _dim("Топ-3 самых «трудных» при re-presentation:")
    for u, rf, t in pairs[:3]:
        _dim(f"    urgency={u:.1f}  refuted={rf:.2f}  «{t[:50]}»")
    _dim("Боттом-3 (легко восстановились):")
    for u, rf, t in pairs[-3:]:
        _dim(f"    urgency={u:.1f}  refuted={rf:.2f}  «{t[:50]}»")
    print()

    passed = r >= 0.3

    _verdict(passed,
             f"Spearman r={r:+.3f} (порог ≥ 0.3), "
             f"avg_urgency={avg_u:.2f}, avg_refuted={avg_r:.3f}")

    print(f"\n  {BD}Следующие вопросы:{W}")
    _dim("Q1: Меняется ли r при DARK_ROUNDS=2/4/8/16?")
    _dim("Q2: urgency какого порога лучше всего предсказывает refuted_rate?")
    _dim("Q3: Можно ли urgency_snap заменить knock_candidates → те же тексты?")

    return {
        "passed": passed,
        "spearman_r": r,
        "avg_urgency": avg_u,
        "avg_refuted": avg_r,
        "n_texts": len(FAMILY_NARRATIVE),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Итоговый отчёт
# ══════════════════════════════════════════════════════════════════════════════

def print_summary(results: Dict[int, Dict]) -> None:
    _hdr("ИТОГИ H6–H10")
    labels = {
        6:  "WakeUpRestorer на большой базе",
        7:  "knock-curriculum vs случайный",
        8:  "Перегиб роста Gen ↔ mean_interval",
        9:  "vitality INSIDE vs AFTER",
        10: "urgency ↔ REFUTED при re-presentation",
    }
    for exp_n, res in sorted(results.items()):
        if res is None:
            continue
        status = ("✓ ПОДТВЕРЖДЕНА" if res.get("passed") is True
                  else "✗ ОПРОВЕРГНУТА" if res.get("passed") is False
                  else "— НЕТ ДАННЫХ")
        col = GR if res.get("passed") else RD
        print(f"  {col}{BD}H{exp_n}{W}  {col}{status:<20}{W}  {DM}{labels[exp_n]}{W}")
        # Ключевые метрики
        if exp_n == 6 and "results" in res:
            sp = res["results"].get(100, {}).get("speedup", 0)
            print(f"       speedup_100={sp:.2f}x  base={res.get('base_size', '?')} Gen")
        elif exp_n == 7:
            print(f"       improvement={res.get('improvement', 0):+.1%}  "
                  f"knock={res.get('mr_knock', 0):.3f} vs random={res.get('mr_random', 0):.3f}")
        elif exp_n == 8:
            print(f"       inflection=pass{res.get('inflection_pass',0)+1}  "
                  f"mi_drop={res.get('mi_drop',0):+.1%}")
        elif exp_n == 9:
            print(f"       inside={res.get('avg_vitality_inside',0):.4f}  "
                  f"after={res.get('avg_vitality_after',0):.4f}  "
                  f"fraction={res.get('fraction_inside_gt_after',0):.1%}")
        elif exp_n == 10:
            print(f"       Spearman r={res.get('spearman_r',0):+.3f}  "
                  f"avg_urgency={res.get('avg_urgency',0):.2f}")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════

EXPERIMENTS = {
    6:  experiment_6_wakeup_large,
    7:  experiment_7_knock_curriculum,
    8:  experiment_8_growth_inflection,
    9:  experiment_9_vitality_timing,
    10: experiment_10_urgency_refuted,
}


def main() -> None:
    p = argparse.ArgumentParser(description="H6–H10 experiments")
    p.add_argument("--quick",    action="store_true",
                   help="Быстрый режим (меньше итераций)")
    p.add_argument("--exp", nargs="*", type=int,
                   help="Номера экспериментов (6-10)")
    p.add_argument("--findings", action="store_true",
                   help="Показать только итоговые выводы")
    args = p.parse_args()

    to_run = sorted(args.exp) if args.exp else sorted(EXPERIMENTS.keys())
    results: Dict[int, Optional[Dict]] = {}

    for n in to_run:
        if n not in EXPERIMENTS:
            print(f"  {AM}⚠ Неизвестный номер эксперимента: {n}{W}")
            continue
        try:
            results[n] = EXPERIMENTS[n](quick=args.quick)
        except Exception as exc:
            print(f"  {RD}✗ Эксперимент H{n} упал: {exc}{W}")
            import traceback
            traceback.print_exc()
            results[n] = {"passed": None, "error": str(exc)}

    if len(results) > 1:
        print_summary(results)


if __name__ == "__main__":
    main()
