"""
Шаг 2: Жадное обобщение и ленивое устранение неопределённости.

Три компонента:

  GreedyGeneralizer   — автоматически строит цепочки признаков из опыта.
                        «Жадность» = максимизируем длину цепочки.

  LazyDisambiguator   — держит конкурирующие гипотезы живыми как можно дольше.
                        Разрешает неопределённость только при бифуркации или лимите.

  NarrativeMinimizer  — находит кратчайшее описание текущей ситуации,
                        сохраняющее различающую способность (MDL-принцип).

Из презентации:
  «Вычисление программы» + «Минимизация нарратива» → Главный Алгоритм.
  «Изменчивая достаточность — нам не нужно много измерений, если ничего
   важного в контексте ситуации мы различить не можем.»
  «Точка бифуркации: Очевидная расходимость траекторий →
   Упрощённое разделение на две чёткие ветви внимания»
"""

from __future__ import annotations
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .generalization import Generalization, GeneralizationBase
from .context import ContextBuffer
from .algorithm import StepResult, StepOutcome
from .attractor import AttractorEncoder, TrajectoryRecorder
from .resource import ResourceDriver
from .teacher import TeacherDriver, TeachingLog, RewardOrder
from .hedonic import HedonicAdapter
from .initiative import InitiativeEngine, Proposal
from .vitality import VitalityEngine, WakeUpRestorer
from .core_types import AttentionStage


# ══════════════════════════════════════════════════════════════════════
# 1. Жадное обобщение
# ══════════════════════════════════════════════════════════════════════

class GreedyGeneralizer:
    """
    Жадное обобщение: автоматически строит цепочки признаков из опыта.

    Принцип работы:
      • При каждом подтверждении признака (CONFIRMED) расширяем текущую цепочку.
      • При завершении или разрыве — пробуем зафиксировать цепочку как нового Gen.
      • Если данная цепочка встретилась >= min_count раз — создаём Gen.
      • «Жадность» = предпочитаем длинные цепочки коротким.
      • Связываем новый Gen с уже имеющимися более короткими (гетерархия).
    """

    def __init__(
        self,
        base: GeneralizationBase,
        min_count: int = 2,    # минимум повторений перед созданием Gen
        max_chain: int = 30,   # максимальная длина цепочки (скользящее окно)
    ) -> None:
        self.base = base
        self.min_count = min_count
        self.max_chain = max_chain
        self._current_chain: List[str] = []
        self._candidates: Dict[tuple, int] = {}   # chain_tuple → count
        self._created_ids: List[str] = []

    # ------------------------------------------------------------------

    def on_step_result(self, result: StepResult) -> Optional[Generalization]:
        """
        Обработать результат шага AttractorEngine.
        Вернуть новый Gen, если он был создан.

        Правила накопления:
          CONFIRMED / COMPLETED → добавляем в цепочку.
              COMPLETED дополнительно делает «контрольную точку»
              (пробует создать Gen из накопленного, но НЕ сбрасывает цепочку).
          REFUTED               → прерывание: фиксируем, сбрасываем.
          EXPLORING             → не сбрасываем (пустой/исследовательский шаг).

        Явный сброс — только через reset_chain() (обычно на границах предложений).
        Это позволяет цепочке расти поперёк границ одиночных Gen
        и захватывать длинные последовательности признаков из потока.
        """
        if result.matched_feature_id and result.outcome in (
            StepOutcome.CONFIRMED, StepOutcome.COMPLETED
        ):
            self._current_chain.append(result.matched_feature_id)
            if len(self._current_chain) > self.max_chain:
                self._current_chain = self._current_chain[-self.max_chain:]
            # Контрольная точка на COMPLETED (не сбрасываем!)
            if result.outcome == StepOutcome.COMPLETED:
                return self._try_create()

        elif result.outcome == StepOutcome.REFUTED:
            # Зафиксировать «ветвь развилки»: подтверждённый префикс + опровергнутый признак.
            # Это позволяет строить Gen для альтернативных продолжений одного начала:
            #   [кот→сидит] + [сидит→у] → fork_L2 кандидат
            # При достижении min_count → создаётся отдельный fork Gen, который
            # HierarchicalConsolidator сможет сопоставить с Gen A=[кот→сидит, сидит→на, ...]
            if result.new_gen_id and self._current_chain:
                new_g = self.base.get(result.new_gen_id)
                if new_g and new_g.feature_chain:
                    fork_key = tuple(self._current_chain) + (new_g.feature_chain[0],)
                    self._candidates[fork_key] = self._candidates.get(fork_key, 0) + 1
                    if (self._candidates[fork_key] >= self.min_count
                            and not self.base.search_by_chain(list(fork_key))):
                        fork_gen = Generalization.new(
                            feature_chain=list(fork_key),
                            label=f"fork_L{len(fork_key)}",
                        )
                        fork_gen.success_count = self._candidates[fork_key]
                        self.base.add(fork_gen)
                        for length in range(1, len(fork_key)):
                            subs = self.base.search_by_chain(list(fork_key[:length]))
                            if subs:
                                self.base.link(fork_gen.gen_id, subs[0].gen_id)

            new_gen = self._try_create()
            self._current_chain = []
            return new_gen

        # EXPLORING: не сбрасываем, не пробуем создать
        return None

    def _try_create(self) -> Optional[Generalization]:
        """
        Попытаться создать новое обобщение из накопленной цепочки.
        Создаём только если:
          1. Длина >= 2 признаков
          2. Цепочка встречалась >= min_count раз
          3. Такого Gen ещё нет в базе
        Цепочки любой длины записываются в candidates (для статистики).
        """
        chain = list(self._current_chain)
        if not chain:
            return None

        # Всегда записываем в кандидаты (даже одиночные признаки)
        key = tuple(chain)
        self._candidates[key] = self._candidates.get(key, 0) + 1

        # Создаём Gen только для цепочек длиной >= 2
        if len(chain) < 2:
            return None

        if self._candidates[key] < self.min_count:
            return None

        # Проверить — возможно, уже существует
        existing = self.base.search_by_chain(chain)
        if existing:
            existing[0].success_count += 1
            return None

        # Создать новый Gen
        # Строим метку из меток chain=1 Gen по каждому feature_id цепочки
        parts = []
        for fid in chain:
            atom = self.base.search_by_chain([fid])
            if atom and atom[0].label:
                parts.append(atom[0].label)
        label = "·".join(parts) if parts else f"greedy_L{len(chain)}"
        new_gen = Generalization.new(
            feature_chain=chain,
            label=label,
        )
        new_gen.success_count = self._candidates[key]
        self.base.add(new_gen)
        self._created_ids.append(new_gen.gen_id)

        # Связать с более короткими существующими обобщениями (гетерархия)
        for length in range(1, len(chain)):
            sub_gens = self.base.search_by_chain(chain[:length])
            if sub_gens:
                self.base.link(new_gen.gen_id, sub_gens[0].gen_id)

        return new_gen

    @property
    def created_count(self) -> int:
        """Количество созданных обобщений."""
        return len(self._created_ids)

    @property
    def candidate_chains(self) -> Dict[tuple, int]:
        """Текущие кандидаты-цепочки и их счётчики."""
        return dict(self._candidates)

    def reset_chain(self) -> Optional[Generalization]:
        """
        Завершить текущую сессию: попытаться создать Gen из накопленной
        цепочки, затем сбросить. Возвращает созданный Gen или None.
        Вызывается на границах предложений/сессий.
        """
        new_gen = self._try_create()
        self._current_chain = []
        return new_gen


# ══════════════════════════════════════════════════════════════════════
# 2. Ленивое устранение неопределённости
# ══════════════════════════════════════════════════════════════════════

class LazyDisambiguator:
    """
    Ленивое устранение неопределённости.

    Принцип: держим ВСЕ правдоподобные Gen активными как можно дольше.
    Не выбираем «победителя» до тех пор, пока:
      • не обнаружена точка бифуркации (траектории явно расходятся), или
      • не превышен лимит конкурирующих Gen (ресурсное ограничение).

    При бифуркации — разделяем на чёткие ветви (как в презентации).
    """

    def __init__(
        self,
        base: GeneralizationBase,
        max_competing: int = 8,
    ) -> None:
        self.base = base
        self.max_competing = max_competing
        self._bifurcation_count: int = 0
        self._disambiguation_count: int = 0

    # ------------------------------------------------------------------

    def load_all_candidates(
        self,
        context: ContextBuffer,
        feature_id: str,
        top_n: Optional[int] = None,
    ) -> int:
        """
        Загрузить ВСЕ Gen, начинающиеся с данного признака (ленивость).
        Не выбираем лучший — берём всех кандидатов.
        Возвращает количество загруженных.
        """
        limit = top_n if top_n else self.max_competing
        candidates = self.base.search_by_prefix([feature_id])
        for gen in candidates[:limit]:
            context.add_active(gen.gen_id)
        return min(len(candidates), limit)

    def detect_bifurcation(
        self, context: ContextBuffer, base: GeneralizationBase
    ) -> bool:
        """
        Обнаружить точку бифуркации:
        активные Gen предсказывают разные следующие признаки.

        Из презентации: «Точка бифуркации: Очевидная расходимость траекторий».
        """
        expected = context.get_expected_features(base)
        unique_features = set(expected.values())
        is_bifurcation = len(unique_features) > 1
        if is_bifurcation:
            self._bifurcation_count += 1
        return is_bifurcation

    def disambiguate(
        self,
        context: ContextBuffer,
        base: GeneralizationBase,
        confirmed_feature_id: Optional[str] = None,
    ) -> Tuple[List[str], List[str]]:
        """
        Разрешить неопределённость.

        Стратегия:
          1. Если есть подтверждённый признак → оставить Gen, ожидавшие именно его.
          2. Иначе → оставить top-N по значимости (обрезать хвост).

        Из презентации:
          «Упрощённое разделение на две чёткие ветви внимания» (C1, C2).

        Возвращает (kept_ids, removed_ids).
        """
        active = context.active_gen_ids()
        if len(active) <= self.max_competing:
            return active, []

        self._disambiguation_count += 1

        if confirmed_feature_id:
            # Ветвь 1: оставить Gen, ожидающих подтверждённый признак
            expected = context.get_expected_features(base)
            to_keep = [
                gid for gid, fid in expected.items()
                if fid == confirmed_feature_id
            ]
            # Добавить Gen с пустым ожиданием (уже завершённые)
            for gid in active:
                gen = base.get(gid)
                if gen and gid not in expected:
                    to_keep.append(gid)
        else:
            # Ветвь 2: top-N по значимости
            ranked = sorted(
                active,
                key=lambda gid: (base.get(gid).significance if base.get(gid) else 0),
                reverse=True,
            )
            to_keep = ranked[:self.max_competing]

        to_remove = [gid for gid in active if gid not in to_keep]
        for gid in to_remove:
            context.remove_active(gid)

        return to_keep, to_remove

    def find_distinguishing_feature(
        self,
        gen_ids_a: List[str],
        gen_ids_b: List[str],
        base: GeneralizationBase,
    ) -> Optional[str]:
        """
        Найти минимальный различающий признак между двумя группами Gen.

        Возвращает feature_id, который встречается в цепочках A, но не B.
        Это «ожидаемый признак» для разрешения неопределённости.
        """
        features_a: Set[str] = set()
        features_b: Set[str] = set()

        for gid in gen_ids_a:
            gen = base.get(gid)
            if gen:
                features_a.update(gen.feature_chain)
        for gid in gen_ids_b:
            gen = base.get(gid)
            if gen:
                features_b.update(gen.feature_chain)

        unique_to_a = features_a - features_b
        return next(iter(unique_to_a), None)

    @property
    def bifurcation_count(self) -> int:
        return self._bifurcation_count

    @property
    def disambiguation_count(self) -> int:
        return self._disambiguation_count


# ══════════════════════════════════════════════════════════════════════
# 3. Минимизация нарратива
# ══════════════════════════════════════════════════════════════════════

class NarrativeMinimizer:
    """
    Минимизация нарратива (MDL — Minimum Description Length).

    Принцип: найти КРАТЧАЙШЕЕ описание текущей ситуации, которое всё ещё
    сохраняет способность различать объекты, ситуации, процессы.

    Из презентации:
      «Изменчивая достаточность — нам не нужно много измерений и разрешающей
       способности, если ничего важного в контексте ситуации мы различить не можем.»

    Алгоритм:
      1. Заменить несколько конкретных Gen одним более общим родительским Gen
         (если все дети родителя присутствуют в описании).
      2. Удалить Gen с нулевой значимостью (если есть значимые альтернативы).
      3. Убрать дублирующие Gen (поглощение: один Gen покрывает другой).
    """

    def __init__(self, base: GeneralizationBase) -> None:
        self.base = base

    # ------------------------------------------------------------------

    def minimize(self, gen_ids: List[str]) -> List[str]:
        """
        Минимизировать набор Gen, сохранив различающую способность.
        Возвращает новый (возможно более короткий) список gen_ids.
        """
        result = set(gen_ids)
        result = self._replace_with_parents(result)
        result = self._prune_insignificant(result)
        result = self._remove_absorbed(result)
        return list(result)

    def description_length(self, gen_ids: List[str]) -> float:
        """
        MDL: стоимость описания = сумма log2(chain_len + 1) по всем Gen.
        Более короткие цепочки = более дешёвое описание.
        """
        total = 0.0
        for gid in gen_ids:
            gen = self.base.get(gid)
            if gen and gen.generalization_level > 0:
                total += math.log2(gen.generalization_level + 1)
        return total

    def compare(self, ids_a: List[str], ids_b: List[str]) -> int:
        """
        Сравнить длины описаний.
        Возвращает: -1 если a короче, 0 если равны, 1 если b короче.
        """
        la = self.description_length(ids_a)
        lb = self.description_length(ids_b)
        if abs(la - lb) < 1e-9:
            return 0
        return -1 if la < lb else 1

    def is_minimal(self, gen_ids: List[str]) -> bool:
        """Проверить, является ли набор уже минимальным."""
        minimized = self.minimize(gen_ids)
        return set(minimized) == set(gen_ids)

    # ------------------------------------------------------------------

    def _replace_with_parents(self, gen_ids: Set[str]) -> Set[str]:
        """Заменить детей родителем, если все дети родителя присутствуют."""
        result = set(gen_ids)
        changed = True
        while changed:
            changed = False
            for gen_id in list(result):
                gen = self.base.get(gen_id)
                if not gen:
                    continue
                for parent_id in gen.parent_ids:
                    parent = self.base.get(parent_id)
                    if not parent or not parent.child_ids:
                        continue
                    if all(c in result for c in parent.child_ids):
                        result -= set(parent.child_ids)
                        result.add(parent_id)
                        changed = True
                        break
                if changed:
                    break
        return result

    def _prune_insignificant(self, gen_ids: Set[str]) -> Set[str]:
        """
        Удалить Gen с нулевой значимостью, если есть значимые альтернативы.
        Из статьи: значимость = ранг в опыте (частота подтверждений).
        """
        significant = {
            gid for gid in gen_ids
            if (g := self.base.get(gid)) and g.significance > 0
        }
        return significant if significant else gen_ids

    def _remove_absorbed(self, gen_ids: Set[str]) -> Set[str]:
        """
        Удалить Gen, полностью поглощённые другим Gen в наборе.
        Gen A поглощается Gen B, если цепочка A является префиксом цепочки B.
        (Более длинная цепочка содержит больше информации.)
        """
        result = set(gen_ids)
        gens = {gid: self.base.get(gid) for gid in result}
        to_remove: Set[str] = set()

        for gid_a, gen_a in gens.items():
            if gen_a is None or gid_a in to_remove:
                continue
            for gid_b, gen_b in gens.items():
                if gid_a == gid_b or gen_b is None or gid_b in to_remove:
                    continue
                # Если chain_a является префиксом chain_b → A поглощается B
                n = len(gen_a.feature_chain)
                if (n > 0
                        and gen_b.feature_chain[:n] == gen_a.feature_chain
                        and len(gen_b.feature_chain) > n):
                    to_remove.add(gid_a)
                    break

        return result - to_remove


# ══════════════════════════════════════════════════════════════════════
# 4. Иерархическая консолидация (Шаг 14)
# ══════════════════════════════════════════════════════════════════════

@dataclass
class HierarchicalConsolidationReport:
    """Результат одного цикла иерархической консолидации."""
    forks_found:      int
    meta_created:     int        # новых мета-Gen создано
    meta_strengthened: int       # существующих мета-Gen усилено
    new_gen_ids:      List[str]  # ID новых мета-Gen


class HierarchicalConsolidator:
    """
    Шаг 14: Иерархическая консолидация — факторизация развилок.

    Находит пары Gen с одинаковым префиксом (развилки) и создаёт или
    усиливает мета-Gen для общего префикса.

    Это позволяет значимости течь ВВЕРХ по гетерархии:

        Gen [утром→кот→сидит]  ┐
                                ├─→ мета [утром→кот]   подтверждается
        Gen [утром→кот→лает]   ┘    при ЛЮБОМ предикате

    Мета-Gen нижнего уровня становятся ветвями для следующего уровня:

        мета [утром→кот]    ┐
                            ├─→ мета [утром]   подтверждается
        мета [утром→собака] ┘    при ЛЮБОМ субъекте

    Многоуровневые passes строят иерархию постепенно: новые мета-Gen,
    созданные на проходе N, образуют развилки для прохода N+1.
    """

    def __init__(
        self,
        base:        GeneralizationBase,
        min_success: int = 1,
    ) -> None:
        self.base = base
        self.min_success = min_success  # мин. подтверждений ветви
        self._total_created:     int = 0
        self._total_strengthened: int = 0

    # ------------------------------------------------------------------

    def consolidate(self, passes: int = 3) -> HierarchicalConsolidationReport:
        """
        Выполнить до passes проходов иерархической консолидации.

        Каждый проход обрабатывает ВСЕ уровни снизу вверх.
        Новые мета-Gen из прохода N становятся входом для прохода N+1,
        что позволяет строить глубокую иерархию постепенно.
        Останавливается досрочно, если новых мета-Gen не появляется.
        """
        total_forks:       int = 0
        total_created:     int = 0
        total_strengthened: int = 0
        all_new_ids: List[str] = []

        for _ in range(passes):
            rep = self._single_pass()
            total_forks        += rep.forks_found
            total_created      += rep.meta_created
            total_strengthened += rep.meta_strengthened
            all_new_ids.extend(rep.new_gen_ids)
            if rep.meta_created == 0:
                break  # сошлись

        self._total_created      += total_created
        self._total_strengthened += total_strengthened

        return HierarchicalConsolidationReport(
            forks_found       = total_forks,
            meta_created      = total_created,
            meta_strengthened = total_strengthened,
            new_gen_ids       = all_new_ids,
        )

    def _single_pass(self) -> HierarchicalConsolidationReport:
        """
        Один проход: сгруппировать Gen по префиксу, создать/усилить мета-Gen.

        Порядок — от коротких префиксов к длинным (bottom-up):
        сначала мета для L2, потом для L3 и т.д.
        """
        # Сгруппировать: prefix_tuple → {continuation_feature → [Gen]}
        # Для каждого Gen проходим ВСЕ длины префиксов (1 .. len-1),
        # чтобы обнаружить развилки между Gen любой длины.
        # Например: Gen A=[f0,f1,f2] и Gen B=[f0,f1_alt] → развилка на (f0,)
        prefix_groups: Dict[tuple, Dict[str, List]] = defaultdict(lambda: defaultdict(list))
        for gen in self.base.all():
            chain = gen.feature_chain
            for k in range(1, len(chain)):
                prefix    = tuple(chain[:k])
                cont_feat = chain[k]
                prefix_groups[prefix][cont_feat].append(gen)

        created      = 0
        strengthened = 0
        forks        = 0
        new_ids: List[str] = []

        # Обрабатываем от коротких префиксов к длинным (bottom-up)
        for prefix_tuple in sorted(prefix_groups.keys(), key=len):
            cont_map = prefix_groups[prefix_tuple]

            # Нет развилки если все ветви идут одинаково
            if len(cont_map) < 2:
                continue

            # Собрать уникальные ветви: по одному представителю на продолжение
            branches = [gens[0] for gens in cont_map.values()]

            # Оставляем только подтверждённые ветви
            active = [b for b in branches if b.success_count >= self.min_success]
            if len(active) < 2:
                continue

            forks += 1
            prefix_list = list(prefix_tuple)

            existing = self.base.search_by_chain(prefix_list)
            if existing:
                existing[0].confirm()
                meta = existing[0]
                # Переименовать в meta_LN если это ещё не мета-Gen
                if meta.label and not meta.label.startswith("meta_"):
                    meta.label = f"meta_L{len(prefix_list)}"
                strengthened += 1
            else:
                # Создать мета-Gen: значимость из средних счётчиков ветвей
                avg_success = max(1, sum(b.success_count for b in active) // len(active))
                avg_stop    = sum(b.stop_count    for b in active) // len(active)
                meta = Generalization.new(
                    feature_chain = prefix_list,
                    label         = f"meta_L{len(prefix_list)}",
                )
                meta.success_count = avg_success
                meta.stop_count    = avg_stop
                self.base.add(meta)

                # Связать мета с его более короткими под-префиксами
                # (мета — РОДИТЕЛЬ sub, т.к. длиннее; sub — ПОТОМОК)
                for length in range(1, len(prefix_list)):
                    subs = self.base.search_by_chain(prefix_list[:length])
                    if subs:
                        self.base.link(meta.gen_id, subs[0].gen_id)

                created += 1
                new_ids.append(meta.gen_id)

            # Ветви — РОДИТЕЛИ мета (длиннее); мета — их ПОТОМОК
            for branch in active:
                self.base.link(branch.gen_id, meta.gen_id)

        return HierarchicalConsolidationReport(
            forks_found       = forks,
            meta_created      = created,
            meta_strengthened = strengthened,
            new_gen_ids       = new_ids,
        )

    @property
    def total_created(self) -> int:
        return self._total_created

    @property
    def total_strengthened(self) -> int:
        return self._total_strengthened

    def stats(self) -> Dict[str, Any]:
        meta_gens = [
            g for g in self.base.all()
            if g.label and g.label.startswith("meta_")
        ]
        return {
            "total_created":      self._total_created,
            "total_strengthened": self._total_strengthened,
            "current_meta_count": len(meta_gens),
            "meta_sig_avg": round(
                sum(g.significance for g in meta_gens) / len(meta_gens), 4
            ) if meta_gens else 0.0,
        }


# ══════════════════════════════════════════════════════════════════════
# 5. Интегрированная система обучения
# ══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class OperationReceipt:
    """Transport fact about one executed command, with no desired-goal label."""
    receipt_id: str
    instance_id: str
    channel_id: str
    seq: int
    command_address: str
    source_id: str
    status: str = "observed"
    outcome_gen_id: Optional[str] = None

    def __post_init__(self):
        if any(not isinstance(v, str) or not v for v in (
            self.receipt_id, self.instance_id, self.channel_id,
            self.command_address, self.source_id,
        )):
            raise ValueError("Receipt identifiers and source must be nonempty strings")
        if type(self.seq) is not int or self.seq < 0:
            raise ValueError("Operation seq must be a nonnegative integer")
        if self.status not in ("observed", "unknown", "unavailable"):
            raise ValueError("Invalid actual status")
        if (self.status == "observed") != (
            isinstance(self.outcome_gen_id, str) and bool(self.outcome_gen_id)
        ) or (self.status != "observed" and self.outcome_gen_id is not None):
            raise ValueError("Only observed receipts carry an outcome")


@dataclass(frozen=True)
class PendingOperation:
    instance_id: str
    channel_id: str
    seq: int
    command_address: str
    cue_gen_id: str
    operation_gen_id: str
    prefix: tuple
    forecasts: tuple


@dataclass(frozen=True)
class OperationRecord:
    pending: PendingOperation
    status: str
    receipt: Optional[OperationReceipt] = None


class LearningSystem:
    """
    Полная система: AttractorEngine + GreedyGeneralizer +
                    LazyDisambiguator + NarrativeMinimizer.

    Обёртка для удобного использования.
    """

    def __init__(
        self,
        feature_tolerance: float = 0.3,
        min_gen_count: int = 2,
        max_competing: int = 8,
        initial_resource: float = 0.5,
        capacity_budget=None,   # Optional[CapacityBudget]
        query_log=None,         # Optional[ContextQueryLog] — лог удивлений для SleepDriver
        provisional_base=None,  # Optional[ProvisionalBase]
        attention_tracer=None,     # Optional[AttentionTracer] — трасса C.12 (И1-Т4)
        operation_record_limit: int = 4096,
    ) -> None:
        from .generalization import GeneralizationBase
        from .algorithm import AttractorEngine
        from .provisional import ProvisionalBase
        from .attention_trace import AttentionTracer

        self._capacity_budget = capacity_budget
        self._query_log = query_log
        self.attention_trace = attention_tracer if attention_tracer is not None \
            else AttentionTracer(enabled=False)
        evict_cb = capacity_budget.enforce if capacity_budget is not None else None
        self.base = GeneralizationBase(evict_callback=evict_cb)
        self._base_tolerance = feature_tolerance
        self.provisional = provisional_base  # public: позволяет читать stats извне
        self.engine = AttractorEngine(
            self.base,
            feature_tolerance=feature_tolerance,
            provisional=provisional_base,
        )
        self.generalizer = GreedyGeneralizer(self.base, min_count=min_gen_count)
        self.disambiguator = LazyDisambiguator(self.base, max_competing=max_competing)
        self.minimizer = NarrativeMinimizer(self.base)
        self.encoder = AttractorEncoder(self.base)
        self.encoder.set_features(self.engine._features)
        self.recorder = TrajectoryRecorder()
        self.resource = ResourceDriver(initial_level=initial_resource)
        self.teacher = TeacherDriver(self.resource)
        self.teaching_log = TeachingLog()
        self.hedonic = HedonicAdapter()
        self.initiative = InitiativeEngine(self.resource)
        self.vitality = VitalityEngine()
        self.restorer = WakeUpRestorer()
        if type(operation_record_limit) is not int or operation_record_limit < 1:
            raise ValueError("operation_record_limit must be a positive integer")
        self._operation_state()
        self._operation_record_limit = operation_record_limit

    def _operation_state(self):
        # Old native session pickles have no actual ledger: migrate empty,
        # never manufacture receipts from success_count/stop_count.
        if not hasattr(self, "_operation_pending"):
            self._operation_pending = {}
            self._operation_records = {}
            self._operation_deliveries = {}
            self._operation_sources = {}
            self._operation_paused = set()
            self._operation_record_limit = 4096

    def operation_state_usage(self) -> Dict[str, int]:
        """Count retained ledger entries; this is not byte/RSS accounting."""
        self._operation_state()
        return {
            "pending": len(self._operation_pending),
            "terminal": len(self._operation_records),
            "deliveries": len(self._operation_deliveries),
            "sources": len(self._operation_sources),
            "paused": len(self._operation_paused),
            "forecast_links": sum(len(p.forecasts) for p in self._operation_pending.values())
                + sum(len(r.pending.forecasts) for r in self._operation_records.values()),
            "evidence": sum(len(getattr(g, "actual_evidence", {})) for g in self.base.all()),
        }

    def _operation_capacity(self, additional: int):
        if sum(self.operation_state_usage().values()) + additional > self._operation_record_limit:
            raise OverflowError("Operation evidence budget exhausted; stop INCOMPLETE")

    def _operation_atom(self, gen_id):
        gen = self.base.get(gen_id)
        if gen is None or len(gen.feature_chain) != 1:
            raise ValueError("Operation role must refer to an existing atomic Gen")
        return gen.feature_chain[0]

    def begin_operation(
        self, *, instance_id: str, channel_id: str, seq: int,
        command_address: str, cue_gen_id: str, operation_gen_id: str,
        contributor_gen_ids=(),
    ) -> PendingOperation:
        """Record an execution, not a selector. A2 must supply its full core contributors.

        Empty contributors are allowed for explicitly forced curriculum actions;
        this API makes no claim that the operation was chosen by native competition.
        """
        self._operation_state()
        if any(not isinstance(v, str) or not v for v in (
            instance_id, channel_id, command_address,
        )) or type(seq) is not int or seq < 0:
            raise ValueError("Invalid operation identity")
        scope, key = (instance_id, channel_id), (instance_id, channel_id, seq)
        if scope in self._operation_paused or scope in self._operation_pending:
            raise ValueError("Channel is interrupted or has a pending operation")
        if key in self._operation_records:
            raise ValueError("Operation seq cannot be reused")
        prefix = (self._operation_atom(cue_gen_id), self._operation_atom(operation_gen_id))
        forecasts = []
        for gid in dict.fromkeys(contributor_gen_ids):
            gen = self.base.get(gid)
            if (gen is None or gen.key_id != cue_gen_id or gen.oper_id != operation_gen_id
                    or not gen.goal_id or getattr(gen, "actual_link", None) != (
                        instance_id, channel_id, cue_gen_id, operation_gen_id, gen.goal_id)):
                raise ValueError("Contributor is not linked to this cue, command and scope")
            self._operation_atom(gen.goal_id)
            forecasts.append((gid, gen.goal_id, self._operation_atom(gen.goal_id),
                              tuple(gen.feature_chain)))
        self._operation_capacity(1 + len(forecasts))
        pending = PendingOperation(instance_id, channel_id, seq, command_address,
                                   cue_gen_id, operation_gen_id, prefix, tuple(forecasts))
        self._operation_pending[scope] = pending
        return pending

    def set_operation_channel_interrupted(self, instance_id, channel_id, interrupted=True):
        self._operation_state()
        if any(not isinstance(v, str) or not v for v in (instance_id, channel_id)):
            raise ValueError("Channel identity is required")
        scope = (instance_id, channel_id)
        if interrupted and scope not in self._operation_paused:
            self._operation_capacity(1)
            self._operation_paused.add(scope)
        elif not interrupted:
            self._operation_paused.discard(scope)

    def cancel_operation(self, instance_id, channel_id) -> bool:
        """Explicit cancel/reset/close; no timeout and no negative evidence."""
        self._operation_state()
        scope = (instance_id, channel_id)
        pending = self._operation_pending.get(scope)
        if pending is None:
            return False
        self._operation_records[(*scope, pending.seq)] = OperationRecord(pending, "cancelled")
        del self._operation_pending[scope]
        return True

    def _actual_evidence_update(self, gen, pending, receipt, *, origin=False):
        from .generalization import ActualEvidence
        key = (pending.instance_id, pending.channel_id, pending.seq)
        evidence = getattr(gen, "actual_evidence", {})
        if key in evidence:
            return False
        link = (pending.instance_id, pending.channel_id, pending.cue_gen_id,
                pending.operation_gen_id, gen.goal_id)
        if getattr(gen, "actual_link", None) not in (None, link):
            raise ValueError("Gen evidence belongs to a different command or scope")
        if not hasattr(gen, "actual_evidence"):
            gen.actual_evidence = {}
        gen.actual_link = link
        gen.actual_chain = tuple(gen.feature_chain)
        gen.actual_evidence[key] = ActualEvidence(
            receipt.receipt_id, receipt.outcome_gen_id == gen.goal_id, origin,
            receipt.outcome_gen_id,
        )
        return True

    def accept_operation_outcome(self, receipt: OperationReceipt) -> str:
        """Validate first, then atomically account each observed execution once."""
        if not isinstance(receipt, OperationReceipt):
            raise TypeError("Expected an OperationReceipt")
        self._operation_state()
        previous = self._operation_deliveries.get(receipt.receipt_id)
        if previous is not None:
            if previous != receipt:
                raise ValueError("Receipt ID reused with different content")
            return "duplicate"
        scope = (receipt.instance_id, receipt.channel_id)
        key = (*scope, receipt.seq)
        terminal = self._operation_records.get(key)
        pending = terminal.pending if terminal else self._operation_pending.get(scope)
        if pending is None or (pending.seq, pending.command_address) != (
            receipt.seq, receipt.command_address,
        ):
            raise ValueError("Actual does not match its pending operation")
        source_key = (*scope, receipt.source_id)
        source_seq = self._operation_sources.get(source_key)
        if receipt.status == "observed" and source_seq is not None and source_seq != receipt.seq:
            raise ValueError("Observed source event replayed under a different operation seq")
        if terminal:
            if terminal.status == "observed" and receipt.status == "observed" and (
                terminal.receipt.outcome_gen_id != receipt.outcome_gen_id
            ):
                raise ValueError("Conflicting actual for an already observed execution")
            add_source = terminal.status == "observed" and receipt.status == "observed" and source_seq is None
            self._operation_capacity(1 + int(add_source))
            self._operation_deliveries[receipt.receipt_id] = receipt
            if add_source:
                self._operation_sources[source_key] = receipt.seq
            return "late_cancelled" if terminal.status == "cancelled" else "duplicate"
        if receipt.status != "observed":
            self._operation_capacity(1)
            self._operation_deliveries[receipt.receipt_id] = receipt
            return "unknown"
        self._operation_atom(receipt.outcome_gen_id)
        if scope in self._operation_paused:
            raise ValueError("Resume the interrupted channel before admitting actual")
        if (self._operation_atom(pending.cue_gen_id),
            self._operation_atom(pending.operation_gen_id)) != pending.prefix:
            raise ValueError("Pending cue/operation encoding changed")
        updates = []
        for gid, forecast, expected_feature, chain in pending.forecasts:
            gen = self.base.get(gid)
            if (gen is None or (gen.key_id, gen.oper_id, gen.goal_id) != (
                pending.cue_gen_id, pending.operation_gen_id, forecast,
            ) or tuple(gen.feature_chain) != chain
                or self._operation_atom(forecast) != expected_feature
                or getattr(gen, "actual_link", None) != (*scope, pending.cue_gen_id,
                                                      pending.operation_gen_id, forecast)):
                raise ValueError("Frozen forecast changed or disappeared before actual")
            updates.append(gen)
        self._operation_capacity(2 + len(updates))
        for gen in updates:
            self._actual_evidence_update(gen, pending, receipt)
        self._operation_deliveries[receipt.receipt_id] = receipt
        self._operation_sources[source_key] = receipt.seq
        self._operation_records[key] = OperationRecord(pending, "observed", receipt)
        del self._operation_pending[scope]
        return "observed"

    def bind_operation_evidence(self, gen_id: str, receipt_id: str) -> bool:
        """Bind a native learned chain to observed roles, including its origin.

        This never creates a Gen or uses task success. It validates that the
        existing native learner created exactly cue→operation→actual chain.
        A2 still must wire this to its live recall/competition path.
        """
        self._operation_state()
        receipt = self._operation_deliveries.get(receipt_id)
        if receipt is None or receipt.status != "observed":
            raise ValueError("Binding requires an observed receipt")
        key = (receipt.instance_id, receipt.channel_id, receipt.seq)
        record = self._operation_records.get(key)
        if record is None or record.status != "observed":
            raise ValueError("Cancelled/unknown executions cannot originate a link")
        receipt = record.receipt  # Canonical delivery, even when an alias was supplied.
        pending = record.pending
        gen = self.base.get(gen_id)
        actual_feature = self._operation_atom(receipt.outcome_gen_id)
        if (gen is None or gen_id not in self.generalizer._created_ids
                or tuple(gen.feature_chain) != (*pending.prefix, actual_feature)):
            raise ValueError("Link must originate from the matching native learned chain")
        roles = (pending.cue_gen_id, pending.operation_gen_id, receipt.outcome_gen_id)
        old_roles = (gen.key_id, gen.oper_id, gen.goal_id)
        link = (pending.instance_id, pending.channel_id, *roles)
        if (old_roles not in ((None, None, None), roles)
                or getattr(gen, "actual_link", None) not in (None, link)):
            raise ValueError("Cannot rebind an existing link or channel evidence")
        if key in getattr(gen, "actual_evidence", {}):
            return False
        self._operation_capacity(1)
        gen.key_id, gen.oper_id, gen.goal_id = roles
        return self._actual_evidence_update(gen, pending, receipt,
                                            origin=gen_id not in {f[0] for f in pending.forecasts})

    def process_token(self, token) -> StepResult:
        """
        Обработать один токен.

        Порядок (12 шагов):
          0. Инициатива: сформировать предложения ДО прихода токена.
          1. Модулировать параметры движка текущим ресурсом.
          2. Шаг Ядра.
          3. Жадное обобщение.
          4. Запись фазовой траектории.
          5. Обновить ресурс по результату.
          6. Внутренний учитель: проверить ордера (мгновенный вброс).
         6б. Гедоника: при COMPLETED — записать завершения, выдать награду.
         6в. Инициатива: оценить предложения, выдать бонус за угаданное.
         6г. Витальность: при CONFIRMED/COMPLETED — зафиксировать активации.
          7. Лог состояния для внешних учителей.
          8. Применить ордера, выставленные внешними учителями.
          9. Ленивое разрешение неопределённости.
        """
        from .algorithm import StepResult

        _tracing = self.attention_trace.enabled

        # 0. Инициатива: предложения ДО токена
        proposals = self.initiative.propose(
            self.engine.context, self.base, self.hedonic
        )
        if _tracing and proposals:
            # Санскара: формирующий импульс подействовал до контакта
            self.attention_trace.emit(AttentionStage.PROBE_IMPULSE, tick=self.engine.step_count,
                             n_proposals=len(proposals))

        # 1. Модуляция параметров движка ресурсом
        rs = self.resource.state
        self.engine.feature_tolerance = rs.modulate_tolerance(self._base_tolerance)

        if _tracing:
            _fid = getattr(getattr(token, "data", None), "feature_id", "") or ""
            _tick0 = self.engine.step_count
            _active_before = set(self.engine.context.active_gen_ids())
            # Виджняна: сырой сигнал получен; Намарупа: различие оформлено
            self.attention_trace.emit(AttentionStage.SIGNAL_IN, node=_fid, tick=_tick0)
            self.attention_trace.emit(AttentionStage.DISTINCTION, node=_fid, tick=_tick0)
            # Аятана: активный контекст готов к сопоставлению
            self.attention_trace.emit(AttentionStage.CONTEXT_READY, tick=_tick0,
                             n_active=len(_active_before))

        # 2. Шаг Ядра
        result = self.engine.step(token)

        if _tracing:
            _tick = self.engine.step_count
            # Спарша: контакт токена с ожиданиями состоялся
            self.attention_trace.emit(AttentionStage.CONTACT, node=_fid, tick=_tick,
                             outcome=result.outcome.name)
            # Авидья: зарегистрирована ненулевая неопределённость
            if result.outcome in (StepOutcome.REFUTED, StepOutcome.EXPLORING):
                self.attention_trace.emit(AttentionStage.UNCERTAINTY, node=_fid, tick=_tick,
                                 outcome=result.outcome.name)
            # Джати/Джара-марана: фиксация и распад актуального контекста
            # (C.12: события контекста, не жизни Gen в базе)
            _active_after = set(self.engine.context.active_gen_ids())
            for _gid in _active_after - _active_before:
                self.attention_trace.emit(AttentionStage.CONTEXT_FIXATION, node=_gid, tick=_tick,
                                 kind="context_fixation")
            for _gid in _active_before - _active_after:
                self.attention_trace.emit(AttentionStage.CONTEXT_DECAY, node=_gid, tick=_tick,
                                 kind="context_decay")

        # 2а. Лог удивлений для SleepDriver: запись REFUTED с контекстом
        if self._query_log is not None and result.outcome == StepOutcome.REFUTED:
            # Записываем Gen, которые ожидали другого признака (нарушенные ожидания).
            # removed_gen_ids = Gen убранные из контекста при REFUTED (они существуют
            # в базе, просто деактивированы). Это контекст ДО удивления.
            _expected_ids = list(result.removed_gen_ids) if result.removed_gen_ids else []
            _ctx_depth = 0
            for _gid in _expected_ids:
                _g = self.base.get(_gid)
                if _g:
                    _ctx_depth = max(_ctx_depth, len(_g.feature_chain))
            self._query_log.record(
                feature_id=token.data.feature_id if hasattr(token.data, "feature_id") else "",
                active_gen_ids=_expected_ids,
                new_gen_id=result.new_gen_id,
                chain_len=_ctx_depth,
                token_label=getattr(token, "label", "") or "",
            )

        # 3. Жадное обобщение
        self.generalizer.on_step_result(result)

        # 4. Запись траектории
        active = self.engine.context.active_gen_ids()
        self.recorder.record(result, active)

        # 5. Обновить ресурс
        self.resource.step(result)

        if _tracing:
            # Ведана: resource_state обновлён по исходу (C.12 буквально);
            # до появления узлового RS6 — по затронутым узлам такта
            _tick = self.engine.step_count
            _level = round(self.resource.state.level, 4)
            _touched = self.engine.context.active_gen_ids() or [""]
            for _gid in _touched:
                self.attention_trace.emit(AttentionStage.EVALUATION, node=_gid, tick=_tick,
                                 outcome=result.outcome.name, level=_level)

        # 6. Внутренний учитель — мгновенный триггер
        self.teacher.check_and_fire(self.engine.context, self.base)

        # 6б. Гедоника: при COMPLETED зафиксировать и начислить награду
        _COMPLETED_BASE = 5.0
        if result.outcome == StepOutcome.COMPLETED:
            for gid in result.completed_gen_ids:
                self.hedonic.record_completion(gid)
                reward = self.hedonic.reward_for(gid, _COMPLETED_BASE)
                self.resource.add_reward(reward)
                if _tracing:
                    # Танха: гедоническая реакция на завершение
                    self.attention_trace.emit(AttentionStage.DRIVE, node=gid,
                                     tick=self.engine.step_count, kind="hedonic")

        # 6в. Инициатива: оценить совпадение, выдать бонус
        initiative_bonus = self.initiative.evaluate(proposals, result.matched_feature_id)
        if initiative_bonus > 0:
            self.resource.add_reward(initiative_bonus)
            if _tracing:
                # Танха: ставка инициативы сыграла
                self.attention_trace.emit(AttentionStage.DRIVE, tick=self.engine.step_count,
                                 kind="initiative")

        # 6г. Витальность: зафиксировать активации подтверждённых Gen
        if result.outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED):
            _vstep = self.engine.step_count
            for gid in self.engine.context.active_gen_ids():
                self.vitality.record_activation(gid, _vstep)
                if _tracing:
                    # Упадана: конкурент удерживает позицию (C.12)
                    self.attention_trace.emit(AttentionStage.RETENTION, node=gid, tick=_vstep)
            if self._capacity_budget is not None:
                self._capacity_budget.set_step(_vstep)

        # 7. Лог для внешних учителей
        self.teaching_log.log_state(result, self.resource.state, active)

        # 8. Применить ордера от внешних учителей
        for order in self.teaching_log.pop_pending_orders():
            self.teacher._orders.append(order)

        # 9. Ленивое разрешение если слишком много конкурентов
        if self.disambiguator.detect_bifurcation(self.engine.context, self.base):
            if _tracing:
                # Бхава: суперпозиция конкурентов ещё не схлопнулась
                self.attention_trace.emit(AttentionStage.SUPERPOSITION, tick=self.engine.step_count,
                                 n_active=len(self.engine.context.active_gen_ids()))
            if len(self.engine.context.active_gen_ids()) > self.disambiguator.max_competing:
                _before_dis = (set(self.engine.context.active_gen_ids())
                               if _tracing else None)
                self.disambiguator.disambiguate(
                    self.engine.context,
                    self.base,
                    confirmed_feature_id=result.matched_feature_id,
                )
                if _tracing:
                    # Разрешение конкуренции: проигравшие покидают контекст
                    _after_dis = set(self.engine.context.active_gen_ids())
                    for _gid in _before_dis - _after_dis:
                        self.attention_trace.emit(AttentionStage.CONTEXT_DECAY, node=_gid,
                                         tick=self.engine.step_count,
                                         kind="disambiguation")

        return result

    def process_stream(self, tokens) -> List[StepResult]:
        """Обработать поток токенов."""
        results = []
        for token in tokens:
            results.append(self.process_token(token))
        return results

    def get_minimal_narrative(self) -> List[str]:
        """Минимизированное описание текущего состояния."""
        active = self.engine.context.active_gen_ids()
        return self.minimizer.minimize(active)

    def get_next_word_candidates(self) -> List[str]:
        """
        Ожидаемые слова-кандидаты из активных Gen цепочек.

        Для каждого активного Gen читает label.split('·')[current_pos]
        как ожидаемое следующее слово. Сортирует по убыванию значимости.

        Используется SmartTextDriver.set_candidates() — вызывать после
        каждого process_token() чтобы обновить кандидатов перед следующим токеном.

        Returns: уникальные слова, порядок по значимости Gen (наивысшая — первая).
        """
        context = self.engine.context
        seen: dict = {}   # word → max_significance

        for gen_id, active_gen in context._active.items():
            gen = self.base.get(gen_id)
            if not gen or not gen.label:
                continue
            k = active_gen.current_feature_index
            parts = gen.label.split("·")
            if k < len(parts):
                raw = parts[k].split("|")[0].strip()
                if raw and not raw.startswith("auto_") and not raw.startswith("greedy_"):
                    sig = gen.significance
                    if raw not in seen or sig > seen[raw]:
                        seen[raw] = sig

        return [w for w, _ in sorted(seen.items(), key=lambda x: -x[1])]

    def apply_divergence_corrections(
        self,
        corrections: dict,          # {gen_id: penalty} penalty < 0
        max_penalty: int = 5,
    ) -> int:
        """
        Применить поправки дивергенции к значимости Gen.

        Каждый отрицательный penalty увеличивает stop_count генерации,
        снижая её significance = success_count / (success_count + stop_count).

        Параметры
        ---------
        corrections : словарь {gen_id: penalty}, penalty < 0
        max_penalty : максимальный прирост stop_count за один вызов

        Возвращает число изменённых Gen.
        """
        modified = 0
        for gen_id, delta in corrections.items():
            if delta >= 0:
                continue
            gen = self.base.get(gen_id)
            if gen is None:
                continue
            penalty = min(int(abs(delta) * 2) + 1, max_penalty)
            gen.stop_count += penalty
            modified += 1
        return modified

    def reset_context(self) -> None:
        """
        Сбросить контекст, обобщитель и запись траектории
        (вызывать на границах предложений/сессий).
        """
        if self.attention_trace.enabled:
            # Джара-марана: распад всего актуального контекста на границе
            _tick = self.engine.step_count
            for _gid in self.engine.context.active_gen_ids():
                self.attention_trace.emit(AttentionStage.CONTEXT_DECAY, node=_gid, tick=_tick,
                                 kind="context_reset")
        self.engine.context.reset()
        self.generalizer.reset_chain()
        self.recorder.reset()
        # Восстановление ресурса при явном сбросе (граница сессии = пауза)
        self.resource.recover(0.02)

    def last_proposals(self) -> List[Proposal]:
        """Последние предложения инициативы (до последнего токена)."""
        return self.initiative.last_proposals

    def stats(self) -> dict:
        rs = self.resource.state
        return {
            "base_size":      self.base.size(),
            "features":       len(self.engine._features),
            "steps":          self.engine.step_count,
            "greedy_created": self.generalizer.created_count,
            "bifurcations":   self.disambiguator.bifurcation_count,
            "disambiguations": self.disambiguator.disambiguation_count,
            "phase_space":    self.encoder.summary(),
            "resource": {
                "level":  round(rs.level, 4),
                "mode":   rs.mode,
                "trend":  round(rs.trend, 4),
            },
            "teacher": {
                "active_orders": self.teacher.active_order_count,
                "total_reward":  self.teacher.total_fired_reward,
                "log_entries":   self.teaching_log.size(),
            },
            "hedonic":    self.hedonic.stats(),
            "initiative": self.initiative.stats(),
            "vitality":   self.vitality.stats(),
        }
