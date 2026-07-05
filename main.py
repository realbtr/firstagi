"""
FirstAGI — демонстрационный сценарий (Шаги 1–5).

Сценарий:
  1. Фаза обучения: система наблюдает повторяющиеся текстовые паттерны
     и жадно строит обобщения.
  2. Фаза распознавания: подаём новый текст, система ищет совпадения.
  3. Минимизация нарратива: сжимаем описание текущего состояния.
  4. Алгоритм консолидации: находим общие «опоры» между обобщениями.
  5. Фазовое пространство (Шаг 3): переменное разрешение, Macro-Token,
     детекция бифуркаций, поиск аттракторов.
  6. Ресурс и учитель (Шаг 4): нейромодуляция, ордера на награду.
  7. Фрактальное сжатие (Шаг 5): IFS Барнсли, самоподобие весовых матриц.
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np

from core.learning import LearningSystem
from core.attractor import Resolution
from core.fractal import BarnsleyCompressor, SelfSimilarityAnalyzer, FractalResolutionBridge
from drivers.text_driver import TextDriver


def separator(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def run_demo() -> None:

    # ── Инициализация ──────────────────────────────────────────────
    separator("Инициализация системы")
    sys_obj = LearningSystem(
        feature_tolerance=0.35,
        min_gen_count=2,
        max_competing=6,
    )
    driver = TextDriver("main_driver", mode="words", lowercase=True)

    # ── Фаза обучения ──────────────────────────────────────────────
    separator("Фаза 1: Обучение на повторяющихся паттернах")

    training_corpus = [
        "кот сидит на окне",
        "кот сидит на диване",
        "кот сидит на окне",          # повтор → укрепляет обобщение
        "собака бежит по улице",
        "собака бежит по парку",
        "собака бежит по улице",      # повтор
        "кот сидит на диване",        # повтор
        "птица летит над полем",
        "птица летит над лесом",
        "птица летит над полем",      # повтор
    ]

    # Строим единый словарь по всему корпусу для консистентного кодирования
    driver.build_vocab(training_corpus)

    for i, text in enumerate(training_corpus, 1):
        tokens = list(driver.produce(text))
        results = sys_obj.process_stream(tokens)

        outcomes = [r.outcome.name for r in results]
        new_gens = [r for r in results if r.outcome.name == "EXPLORING"]
        print(f"  [{i:2d}] {text!r:35s} → {outcomes}")

        # Сброс контекста между предложениями
        sys_obj.reset_context()

    stats = sys_obj.stats()
    print(f"\n  Итог обучения:")
    print(f"    Обобщений в базе :  {stats['base_size']}")
    print(f"    Уникальных признаков: {stats['features']}")
    print(f"    Шагов обработано :  {stats['steps']}")
    print(f"    Жадно создано Gen:  {stats['greedy_created']}")
    print(f"    Бифуркаций       :  {stats['bifurcations']}")

    # ── Просмотр базы обобщений ────────────────────────────────────
    separator("База обобщений (топ по значимости)")
    ranked = sys_obj.base.rank()
    for g in ranked[:10]:
        print(f"  Gen {g.gen_id[:8]}…  "
              f"level={g.generalization_level}  "
              f"sig={g.significance:.2f}  "
              f"✓{g.success_count} ✗{g.stop_count}  "
              f"label={g.label!r}")

    # ── Фаза распознавания ─────────────────────────────────────────
    separator("Фаза 2: Распознавание новых примеров")

    test_phrases = [
        "кот сидит на окне",        # точное совпадение с обученным
        "кот лежит на полу",        # новый паттерн
        "собака бежит по улице",    # точное совпадение
        "рыба плывёт в реке",       # совсем новый
    ]

    for phrase in test_phrases:
        sys_obj.reset_context()

        tokens = list(driver.produce(phrase))
        results = sys_obj.process_stream(tokens)

        confirmed = sum(1 for r in results if r.outcome.name == "CONFIRMED")
        completed = sum(1 for r in results if r.outcome.name == "COMPLETED")
        refuted   = sum(1 for r in results if r.outcome.name == "REFUTED")
        explored  = sum(1 for r in results if r.outcome.name == "EXPLORING")

        total = len(tokens)
        match_rate = (confirmed + completed) / total if total else 0

        print(f"  {phrase!r:35s} "
              f"совп={match_rate:.0%}  "
              f"✓{confirmed}  ✗{refuted}  ◎{completed}  ~{explored}")

    # ── Фазовое пространство (Шаг 3) ───────────────────────────────
    separator("Фаза 3: Фазовое пространство (Шаг 3)")

    enc = sys_obj.encoder
    ps = enc.summary()
    print(f"  Обобщений в базе      : {ps['n_gen']}")
    print(f"  Аттракторов           : {ps['n_attractors']}")
    print(f"  Macro-Token COARSE    : {ps['n_macro_coarse']}")
    print(f"  Macro-Token MEDIUM    : {ps['n_macro_medium']}")
    print(f"  Сжатие COARSE         : {ps['compression_coarse']:.1%}")
    print(f"  Сжатие MEDIUM         : {ps['compression_medium']:.1%}")
    print(f"  Средняя значимость    : {ps['avg_significance']:.3f}")
    print(f"  Максимальная длина цепочки: {ps['max_chain_length']}")
    print(f"  Записано траекторий   : {sys_obj.recorder.count}")

    # Macro-Token при разных разрешениях
    macros_coarse = enc.create_macro_tokens(Resolution.COARSE)
    if macros_coarse:
        print(f"\n  Macro-Token COARSE (топ-4):")
        for mt in macros_coarse[:4]:
            print(f"    [{mt.size:2d} Gen] prefix={mt.shared_prefix}  "
                  f"sig_total={mt.total_significance:.2f}  "
                  f"dist_feats={len(mt.distinguishing_features)}")

    # Аттракторы
    attractors = enc.find_attractors(min_strength=0.0)
    enc.attach_macro_tokens(attractors, Resolution.COARSE)
    if attractors:
        print(f"\n  Аттракторы (топ-5):")
        for attr in attractors[:5]:
            mt_info = f"  macro={attr.macro_token.shared_prefix}" if attr.macro_token else ""
            print(f"    strength={attr.strength:.0f}  "
                  f"core={len(attr.core_gen_ids)}  "
                  f"basin={attr.basin_size}{mt_info}")

    # Переменное разрешение для текущего контекста
    sys_obj.engine.context.reset()
    top_gens = sys_obj.base.rank()[:4]
    for g in top_gens:
        sys_obj.engine.context.add_active(g.gen_id)
    resolutions = enc.compute_all_resolutions(sys_obj.engine.context)
    if resolutions:
        print(f"\n  Переменное разрешение для топ-Gen:")
        for gid, res in list(resolutions.items())[:4]:
            g = sys_obj.base.get(gid)
            label = g.label or gid[:8]
            print(f"    {label:20s}  sig={g.significance:.2f}  "
                  f"level={g.generalization_level}  res={res.name}")

    # ── Минимизация нарратива ──────────────────────────────────────
    separator("Фаза 4: Минимизация нарратива")

    # Загрузим несколько Gen в контекст и минимизируем
    sys_obj.engine.context.reset()
    top_gens = sys_obj.base.rank()[:5]
    for g in top_gens:
        sys_obj.engine.context.add_active(g.gen_id)

    active_before = sys_obj.engine.context.active_gen_ids()
    narrative_min  = sys_obj.get_minimal_narrative()
    dl_before = sys_obj.minimizer.description_length(active_before)
    dl_after  = sys_obj.minimizer.description_length(narrative_min)

    print(f"  Активных Gen до минимизации : {len(active_before)}"
          f"  (MDL={dl_before:.2f})")
    print(f"  Активных Gen после           : {len(narrative_min)}"
          f"  (MDL={dl_after:.2f})")
    print(f"  Сжатие                       : "
          f"{(1 - len(narrative_min)/max(len(active_before),1))*100:.0f}%")

    # ── Консолидация ───────────────────────────────────────────────
    separator("Фаза 5: Алгоритм консолидации")

    new_gens = sys_obj.engine.consolidate(min_success=2)
    if new_gens:
        print(f"  Создано консолидированных Gen: {len(new_gens)}")
        for g in new_gens:
            print(f"    {g.gen_id[:8]}…  chain_len={g.generalization_level}  "
                  f"label={g.label!r}")
    else:
        print("  Консолидации не требуется (недостаточно повторений).")

    print(f"\n  Итоговый размер базы: {sys_obj.base.size()}")

    # ── Ресурс и Учитель (Шаг 4) ───────────────────────────────────
    separator("Фаза 6: Ресурс и Внутренний Учитель (Шаг 4)")

    rs = sys_obj.resource.state
    print(f"  Уровень ресурса  : {rs.level:.3f}  режим={rs.mode}")
    print(f"  Тренд            : {rs.trend:+.4f}")
    print(f"  Tolerance сейчас : {rs.modulate_tolerance(0.35):.3f}")
    print(f"  Resolution hint  : {rs.resolution_hint().name}")

    # Ставим учебный ордер — наградить, когда топ-2 Gen активны вместе
    top2 = [g.gen_id for g in sys_obj.base.rank()[:2]]
    order = sys_obj.teacher.add_order(
        required_gen_ids=set(top2),
        reward=50.0,
        label="топ-2 паттерна вместе",
        max_fires=1,
    )
    print(f"\n  Добавлен ордер: {order.label!r}  reward={order.reward}")
    print(f"  Активных ордеров : {sys_obj.teacher.active_order_count}")

    # Вручную активируем нужные Gen и проверяем срабатывание
    sys_obj.engine.context.reset()
    for gid in top2:
        sys_obj.engine.context.add_active(gid)
    fired = sys_obj.teacher.check_and_fire(sys_obj.engine.context, sys_obj.base)
    print(f"  Ордер сработал   : {fired > 0}  (reward={fired:.1f})")
    print(f"  Лог учителя      : {sys_obj.teacher.fired_log(last_n=1)}")

    # TeachingLog — состояние для LLM-учителей
    recent = sys_obj.teaching_log.get_recent(n=3)
    print(f"\n  TeachingLog: {sys_obj.teaching_log.size()} записей, последние {len(recent)}:")
    for entry in recent:
        print(f"    step={entry['step']}  outcome={entry['outcome']}  "
              f"resource={entry['resource_level']}")

    # ── Фрактальное сжатие (Шаг 5) ─────────────────────────────────
    separator("Фаза 7: Фрактальное сжатие (Шаг 5)")

    # Строим «весовую матрицу» из значимостей обобщений
    gens = sys_obj.base.rank()
    n = len(gens)
    if n >= 4:
        # Внешнее произведение: matrix[i,j] = sig_i * sig_j  →  имитация весовой матрицы
        sigs = np.array([g.significance for g in gens], dtype=float)
        # Дополняем до ближайшей степени 2 (≥ 8) для корректной работы PIFS
        side = max(8, 1 << (n - 1).bit_length())
        padded = np.zeros((side, side), dtype=float)
        padded[:n, :n] = np.outer(sigs, sigs)
        matrix = padded

        print(f"  Матрица весов    : {matrix.shape}  (из {n} Gen, дополнена до {side}×{side})")
        print(f"  Дисперсия        : {np.var(matrix):.4f}")

        # Анализ самоподобия
        comp = BarnsleyCompressor(range_size=4)
        analyzer = SelfSimilarityAnalyzer(comp)
        report = analyzer.analyze(matrix, n_iterations=10)

        print(f"\n  Самоподобие (IFS-ошибка) : {report['self_similarity']:.4f}"
              f"  (↓ лучше)")
        print(f"  Фрактальная размерность  : {report['fractal_dim']:.3f}")
        print(f"  Коэф. сжатия (range=4)  : {report['compression_ratio']:.1%}")
        print(f"  MSE после восстановления : {report['mse']:.4f}")
        if report['psnr_db'] < 999:
            print(f"  PSNR                     : {report['psnr_db']:.1f} дБ")

        # Мульти-разрешение
        print(f"\n  Мульти-разрешение (IFS Барнсли):")
        mr = FractalResolutionBridge.multi_resolution_encode(matrix)
        for res_name, info in sorted(mr.items(),
                                     key=lambda kv: kv[1]["compression_ratio"],
                                     reverse=True):
            print(f"    {res_name:8s}  сжатие={info['compression_ratio']:.1%}"
                  f"  MSE={info['mse']:.4f}"
                  f"  блоков={info['n_blocks']}")

        # Предложение разрешения под цель
        suggested = FractalResolutionBridge.suggest_resolution(target_compression=0.5)
        print(f"\n  Оптимальное разрешение для сжатия ≥50%: {suggested.name}")
    else:
        print("  Недостаточно обобщений для демонстрации (нужно ≥ 4).")

    separator("Готово")


if __name__ == "__main__":
    run_demo()
