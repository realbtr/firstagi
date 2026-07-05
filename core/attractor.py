"""
Шаг 3: Прямое кодирование аттрактора в фазовом пространстве.

Из презентации (слайд 6):
  ┌─────────────────────────────────────────────────────────────────────┐
  │ Левая панель:   Несущественные вариации Avar→Bvar                  │
  │                 ↓ Обобщённый ключ/цель/импульс A→B                 │
  │                 (Без потери различающей способности)                │
  │                                                                     │
  │ Средняя панель: Точка бифуркации A→B                               │
  │                 ↓ Упрощённое разделение на ветви C1, C2            │
  │                                                                     │
  │ Правая панель:  Большой объём необобщённых признаков               │
  │                 ↓ Обобщение в Макро-Токен (с сохранением структуры)│
  └─────────────────────────────────────────────────────────────────────┘

Три операции AttractorEncoder:
  1. Переменное разрешение   — coarsening/refining фазового пространства
  2. Детекция бифуркаций     — где траектории явно расходятся
  3. Макро-токенизация        — группировка похожих Gen в один Macro-Token
"""

from __future__ import annotations
import uuid
import time
import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Tuple

from .generalization import Generalization, GeneralizationBase
from .context import ContextBuffer
from .algorithm import StepResult, StepOutcome


# ══════════════════════════════════════════════════════════════════════
# Типы данных
# ══════════════════════════════════════════════════════════════════════

class Resolution(Enum):
    """
    Уровень разрешения в фазовом пространстве.

    «Изменчивая достаточность — нам не нужно много измерений и
     разрешающей способности, если ничего важного в контексте
     ситуации мы различить не можем.»

    COARSE   — группируем по первому признаку (максимальное обобщение)
    MEDIUM   — первые два признака
    FINE     — первые три признака
    EXACT    — все признаки (минимальное обобщение, у точек бифуркации)
    """
    COARSE = 1
    MEDIUM = 2
    FINE   = 3
    EXACT  = 4

    def prefix_length(self) -> int:
        """Длина префикса цепочки, используемого при данном разрешении."""
        return {
            Resolution.COARSE: 1,
            Resolution.MEDIUM: 2,
            Resolution.FINE:   3,
            Resolution.EXACT:  9999,
        }[self]

    def coarser(self) -> Resolution:
        return Resolution(max(1, self.value - 1))

    def finer(self) -> Resolution:
        return Resolution(min(4, self.value + 1))


@dataclass
class PhasePoint:
    """Точка в фазовом пространстве (gen_id × позиция × разрешение)."""
    gen_id: str
    feature_index: int = 0         # позиция в цепочке признаков
    resolution: Resolution = Resolution.FINE
    outcome: Optional[str] = None  # CONFIRMED / COMPLETED / REFUTED / EXPLORING


@dataclass
class BifurcationPoint:
    """
    Точка бифуркации: место, где траектории явно расходятся.

    «Точка бифуркации: Очевидная расходимость траекторий →
     Упрощённое разделение на две чёткие ветви внимания»
    """
    bifurcation_id: str
    branch_a: List[str]                     # gen_ids в ветви A
    branch_b: List[str]                     # gen_ids в ветви B
    distinguishing_feature_a: Optional[str] # признак, уникальный для A
    distinguishing_feature_b: Optional[str] # признак, уникальный для B
    divergence_score: float                 # чёткость разделения [0, 1]
    position_gen_id: str                    # Gen, в котором произошло ветвление


@dataclass
class MacroToken:
    """
    Макро-токен: группа Gen, неразличимых при текущем разрешении.

    «Обобщённый ключ, Обобщённая цель, Обобщённый импульс
     (Без потери различающей способности)»

    Macro-Token = обобщение с сохранением структуры информации.
    """
    macro_id: str
    member_gen_ids: List[str]           # все Gen в группе
    representative_id: str              # самый значимый Gen (обобщённый ключ)
    resolution: Resolution
    shared_prefix: List[str]            # общий префикс цепочек (что объединяет)
    distinguishing_features: Set[str]   # признаки, отличающие от других Macro-Token
    total_significance: float = 0.0     # суммарная значимость группы

    @property
    def size(self) -> int:
        return len(self.member_gen_ids)


@dataclass
class Attractor:
    """
    Аттрактор: устойчивая траектория в фазовом пространстве.

    Многие начальные условия приводят к одному и тому же аттрактору.
    Аттрактор = высокозначимый Gen + его «бассейн» (кто к нему сходится).
    """
    attractor_id: str
    core_gen_ids: List[str]     # Gen в ядре аттрактора (высокая значимость)
    basin_gen_ids: List[str]    # Gen, сходящиеся к этому аттрактору
    strength: float             # устойчивость (взвешенное число подтверждений)
    macro_token: Optional[MacroToken] = None  # Macro-Token если создан

    @property
    def basin_size(self) -> int:
        return len(set(self.basin_gen_ids))


# ══════════════════════════════════════════════════════════════════════
# Траектория в фазовом пространстве
# ══════════════════════════════════════════════════════════════════════

class PhaseTrajectory:
    """Траектория в фазовом пространстве: последовательность PhasePoint."""

    def __init__(self, trajectory_id: str = None) -> None:
        self.trajectory_id: str = trajectory_id or str(uuid.uuid4())
        self.points: List[PhasePoint] = []
        self.start_time: float = time.time()

    def add(self, point: PhasePoint) -> None:
        self.points.append(point)

    @property
    def length(self) -> int:
        return len(self.points)

    @property
    def gen_sequence(self) -> List[str]:
        return [p.gen_id for p in self.points]

    def last_point(self) -> Optional[PhasePoint]:
        return self.points[-1] if self.points else None

    def diverges_from(self, other: PhaseTrajectory) -> Optional[int]:
        """Вернуть индекс первого расхождения с другой траекторией."""
        for i, (p1, p2) in enumerate(zip(self.points, other.points)):
            if p1.gen_id != p2.gen_id:
                return i
        if len(self.points) != len(other.points):
            return min(len(self.points), len(other.points))
        return None  # Полное совпадение

    def converges_to(
        self, other: PhaseTrajectory, tail_length: int = 2
    ) -> bool:
        """Проверить, совпадают ли последние tail_length точек (сходимость)."""
        if self.length < tail_length or other.length < tail_length:
            return False
        return self.gen_sequence[-tail_length:] == other.gen_sequence[-tail_length:]

    def coarsen(self, resolution: Resolution) -> PhaseTrajectory:
        """Вернуть огрублённую версию траектории."""
        new_traj = PhaseTrajectory(self.trajectory_id + "_c")
        for p in self.points:
            new_traj.add(PhasePoint(
                gen_id=p.gen_id,
                feature_index=p.feature_index,
                resolution=resolution,
                outcome=p.outcome,
            ))
        return new_traj

    def __repr__(self) -> str:
        return f"PhaseTrajectory(len={self.length}, ids={self.gen_sequence[:3]}...)"


# ══════════════════════════════════════════════════════════════════════
# Запись траекторий (TrajectoryRecorder)
# ══════════════════════════════════════════════════════════════════════

class TrajectoryRecorder:
    """
    Записывает фазовые траектории во время работы движка.
    Подключается к LearningSystem и пишет в каждом шаге.
    """

    def __init__(self) -> None:
        self._current: PhaseTrajectory = PhaseTrajectory()
        self._completed: List[PhaseTrajectory] = []

    def record(self, result: StepResult, active_gen_ids: List[str]) -> None:
        """Записать один шаг в текущую траекторию."""
        if result.outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED):
            for gen_id in active_gen_ids:
                self._current.add(PhasePoint(
                    gen_id=gen_id,
                    feature_index=self._current.length,
                    outcome=result.outcome.name,
                ))
        elif result.outcome in (StepOutcome.REFUTED, StepOutcome.EXPLORING):
            if self._current.length > 0:
                self._completed.append(self._current)
            self._current = PhaseTrajectory()

    def reset(self) -> None:
        """Завершить текущую траекторию (граница предложения/сессии)."""
        if self._current.length > 0:
            self._completed.append(self._current)
        self._current = PhaseTrajectory()

    def all_trajectories(self) -> List[PhaseTrajectory]:
        return list(self._completed)

    @property
    def count(self) -> int:
        return len(self._completed)


# ══════════════════════════════════════════════════════════════════════
# AttractorEncoder — основной класс Шага 3
# ══════════════════════════════════════════════════════════════════════

class AttractorEncoder:
    """
    Прямое кодирование аттрактора в фазовом пространстве.

    Реализует три операции из презентации:
      1. Переменное разрешение   (compute_resolution / compute_all_resolutions)
      2. Детекция бифуркаций     (detect_bifurcations)
      3. Макро-токенизация        (create_macro_tokens / find_attractors)
    """

    def __init__(
        self,
        base: GeneralizationBase,
        min_significance: float = 0.3,
    ) -> None:
        self.base = base
        self.min_significance = min_significance
        self._features: Dict = {}

    def set_features(self, features: Dict) -> None:
        """Разделить реестр признаков с AttractorEngine."""
        self._features = features

    # ─── 1. ПЕРЕМЕННОЕ РАЗРЕШЕНИЕ ──────────────────────────────────

    def compute_resolution(
        self,
        gen_id: str,
        near_bifurcation: bool = False,
    ) -> Resolution:
        """
        Определить оптимальное разрешение для Gen.

        Правило «Изменчивой достаточности»:
          • Высокая значимость, длинная цепочка → COARSE (достаточно грубо)
          • Рядом с бифуркацией → EXACT (нужна точность для различения)
          • Новый/неизученный → FINE (ещё не знаем, что важно)
        """
        if near_bifurcation:
            return Resolution.EXACT

        gen = self.base.get(gen_id)
        if gen is None:
            return Resolution.MEDIUM

        sig = gen.significance
        level = gen.generalization_level

        if sig >= 0.8 and level >= 3:
            return Resolution.COARSE
        elif sig >= 0.5:
            return Resolution.MEDIUM
        elif sig > 0.0:
            return Resolution.FINE
        else:
            return Resolution.EXACT   # Новый Gen — нужна максимальная точность

    def compute_all_resolutions(
        self, context: ContextBuffer
    ) -> Dict[str, Resolution]:
        """Вычислить разрешение для всех активных Gen в контексте."""
        active = context.active_gen_ids()
        bifurcations = self.detect_bifurcations(context)

        near_bif: Set[str] = set()
        for bif in bifurcations:
            near_bif.update(bif.branch_a)
            near_bif.update(bif.branch_b)

        return {
            gid: self.compute_resolution(gid, near_bifurcation=(gid in near_bif))
            for gid in active
        }

    def phase_space_dimensionality(self, context: ContextBuffer) -> dict:
        """
        Оценить «эффективную размерность» фазового пространства
        в текущем контексте.

        Из презентации: «Минимизация разрешения и размерности
        фазового пространства».
        """
        resolutions = self.compute_all_resolutions(context)
        active = context.active_gen_ids()

        counts = {r: 0 for r in Resolution}
        for res in resolutions.values():
            counts[res] += 1

        # Эффективная размерность = среднее разрешение × число Gen
        if not resolutions:
            return {"effective_dim": 0, "counts": counts}

        avg_res = sum(r.value for r in resolutions.values()) / len(resolutions)
        eff_dim = avg_res * len(active)

        return {
            "n_active": len(active),
            "avg_resolution": avg_res,
            "effective_dim": eff_dim,
            "counts": {r.name: c for r, c in counts.items()},
        }

    # ─── 2. ДЕТЕКЦИЯ БИФУРКАЦИЙ ────────────────────────────────────

    def detect_bifurcations(
        self, context: ContextBuffer
    ) -> List[BifurcationPoint]:
        """
        Найти точки бифуркации в текущем контексте.

        Бифуркация = активные Gen предсказывают РАЗНЫЕ следующие признаки.
        «Точка бифуркации: Очевидная расходимость траекторий»
        """
        expected = context.get_expected_features(self.base)

        # Сгруппировать Gen по ожидаемому следующему признаку
        feat_groups: Dict[str, List[str]] = {}
        for gen_id, feat_id in expected.items():
            feat_groups.setdefault(feat_id, []).append(gen_id)

        if len(feat_groups) <= 1:
            return []

        bifurcations: List[BifurcationPoint] = []
        feat_list = list(feat_groups.items())

        for i in range(len(feat_list)):
            for j in range(i + 1, len(feat_list)):
                feat_a, gens_a = feat_list[i]
                feat_b, gens_b = feat_list[j]

                # Чёткость разделения: насколько равны размеры ветвей
                total = len(gens_a) + len(gens_b)
                divergence = 1.0 - abs(len(gens_a) - len(gens_b)) / max(total, 1)

                features_a = self._collect_features(gens_a)
                features_b = self._collect_features(gens_b)

                bif = BifurcationPoint(
                    bifurcation_id=str(uuid.uuid4()),
                    branch_a=gens_a,
                    branch_b=gens_b,
                    distinguishing_feature_a=next(
                        iter(features_a - features_b), None
                    ),
                    distinguishing_feature_b=next(
                        iter(features_b - features_a), None
                    ),
                    divergence_score=divergence,
                    position_gen_id=gens_a[0] if gens_a else "",
                )
                bifurcations.append(bif)

        return sorted(bifurcations, key=lambda b: b.divergence_score, reverse=True)

    def split_on_bifurcation(
        self,
        bif: BifurcationPoint,
        context: ContextBuffer,
        confirmed_branch: str = "a",
    ) -> Tuple[List[str], List[str]]:
        """
        Разделить контекст на две чёткие ветви в точке бифуркации.

        confirmed_branch: "a" или "b" — какую ветвь считать основной.
        Возвращает (kept_ids, removed_ids).
        """
        if confirmed_branch == "a":
            keep = set(bif.branch_a)
            remove = set(bif.branch_b)
        else:
            keep = set(bif.branch_b)
            remove = set(bif.branch_a)

        active = set(context.active_gen_ids())
        to_remove = list(active & remove)
        to_keep = list(active & keep)

        for gid in to_remove:
            context.remove_active(gid)

        return to_keep, to_remove

    # ─── 3. МАКРО-ТОКЕНИЗАЦИЯ ───────────────────────────────────────

    def create_macro_tokens(
        self,
        resolution: Resolution = Resolution.MEDIUM,
        min_members: int = 1,
    ) -> List[MacroToken]:
        """
        Сгруппировать Gen в Macro-Token при заданном разрешении.

        Разрешение определяет длину общего префикса:
          COARSE → 1 признак (максимальное обобщение)
          MEDIUM → 2 признака
          FINE   → 3 признака
          EXACT  → без группировки

        «Большой объём необобщённых признаков →
         Обобщение с сохранением структуры информации»
        """
        prefix_len = resolution.prefix_length()

        groups: Dict[tuple, List[str]] = {}
        for gen in self.base.all():
            if not gen.feature_chain:
                continue
            prefix = tuple(gen.feature_chain[:prefix_len])
            groups.setdefault(prefix, []).append(gen.gen_id)

        macro_tokens: List[MacroToken] = []
        for prefix, gen_ids in groups.items():
            if len(gen_ids) < min_members:
                continue

            gens = [g for gid in gen_ids if (g := self.base.get(gid))]
            if not gens:
                continue

            rep = max(gens, key=lambda g: g.significance)

            # Различающие признаки = всё, что за общим префиксом
            suffix_features: Set[str] = set()
            for g in gens:
                suffix_features.update(g.feature_chain[len(prefix):])

            total_sig = sum(g.significance for g in gens)

            mt = MacroToken(
                macro_id=str(uuid.uuid4()),
                member_gen_ids=gen_ids,
                representative_id=rep.gen_id,
                resolution=resolution,
                shared_prefix=list(prefix),
                distinguishing_features=suffix_features,
                total_significance=total_sig,
            )
            macro_tokens.append(mt)

        return sorted(macro_tokens, key=lambda m: m.total_significance, reverse=True)

    def find_macro_token_for(
        self,
        gen_id: str,
        macro_tokens: List[MacroToken],
    ) -> Optional[MacroToken]:
        """Найти Macro-Token, которому принадлежит данный Gen."""
        for mt in macro_tokens:
            if gen_id in mt.member_gen_ids:
                return mt
        return None

    def compression_ratio(
        self,
        resolution: Resolution = Resolution.MEDIUM,
    ) -> float:
        """
        Коэффициент сжатия при данном разрешении.

        = 1 - (кол-во Macro-Token) / (кол-во Gen)

        Показывает, насколько эффективно Macro-Token сжимают базу.
        """
        n_gen = self.base.size()
        if n_gen == 0:
            return 0.0
        macros = self.create_macro_tokens(resolution)
        return 1.0 - len(macros) / n_gen

    # ─── 4. ПОИСК АТТРАКТОРОВ ──────────────────────────────────────

    def find_attractors(
        self,
        min_strength: float = 0.3,
        max_attractors: int = 20,
    ) -> List[Attractor]:
        """
        Найти аттракторы: устойчивые Gen, к которым сходятся траектории.

        Аттрактор = Gen с высокой значимостью + его «бассейн»
        (Gen, переходящие к нему по статистике переходов).
        """
        candidates = [
            g for g in self.base.all()
            if g.significance >= min_strength and g.generalization_level >= 1
        ]

        attractors: List[Attractor] = []
        for gen in candidates:
            basin: Set[str] = {gen.gen_id}

            # Найти Gen, переходящие к признакам данного Gen
            for feat_id in gen.feature_chain:
                for other in self.base.all():
                    transitions = self.base.get_transitions(other.gen_id)
                    if feat_id in transitions:
                        basin.add(other.gen_id)

            # Добавить Gen с тем же первым признаком (одинаковый «бассейн»)
            if gen.feature_chain:
                for pm in self.base.search_by_prefix([gen.feature_chain[0]]):
                    if pm.significance >= min_strength * 0.5:
                        basin.add(pm.gen_id)

            strength = sum(
                (g := self.base.get(gid)) and g.success_count or 0
                for gid in basin
            )

            attractors.append(Attractor(
                attractor_id=str(uuid.uuid4()),
                core_gen_ids=[gen.gen_id],
                basin_gen_ids=list(basin),
                strength=float(strength),
            ))

        merged = self._merge_overlapping(attractors)
        merged.sort(key=lambda a: a.strength, reverse=True)
        return merged[:max_attractors]

    def attach_macro_tokens(
        self,
        attractors: List[Attractor],
        resolution: Resolution = Resolution.MEDIUM,
    ) -> None:
        """Привязать Macro-Token к каждому аттрактору."""
        macros = self.create_macro_tokens(resolution)
        for attr in attractors:
            for core_id in attr.core_gen_ids:
                mt = self.find_macro_token_for(core_id, macros)
                if mt:
                    attr.macro_token = mt
                    break

    def _merge_overlapping(
        self, attractors: List[Attractor], overlap_threshold: float = 0.5
    ) -> List[Attractor]:
        """Объединить аттракторы с сильно пересекающимися бассейнами."""
        if not attractors:
            return []

        merged: List[Attractor] = []
        used: Set[str] = set()

        for a in attractors:
            if a.attractor_id in used:
                continue

            basin_a = set(a.basin_gen_ids)
            core = list(a.core_gen_ids)
            basin = set(basin_a)
            strength = a.strength

            for b in attractors:
                if b.attractor_id in used or b.attractor_id == a.attractor_id:
                    continue
                basin_b = set(b.basin_gen_ids)
                smaller = min(len(basin_a), len(basin_b))
                if smaller > 0 and len(basin_a & basin_b) / smaller > overlap_threshold:
                    core.extend(b.core_gen_ids)
                    basin |= basin_b
                    strength += b.strength
                    used.add(b.attractor_id)

            merged.append(Attractor(
                attractor_id=a.attractor_id,
                core_gen_ids=core,
                basin_gen_ids=list(basin),
                strength=strength,
            ))
            used.add(a.attractor_id)

        return merged

    # ─── 5. ВСПОМОГАТЕЛЬНЫЕ ────────────────────────────────────────

    def _collect_features(self, gen_ids: List[str]) -> Set[str]:
        features: Set[str] = set()
        for gid in gen_ids:
            if (gen := self.base.get(gid)):
                features.update(gen.feature_chain)
        return features

    # ─── 6. СВОДКА ФАЗОВОГО ПРОСТРАНСТВА ───────────────────────────

    def summary(self) -> dict:
        """Сводная статистика фазового пространства."""
        gens = self.base.all()
        n = len(gens)
        if n == 0:
            return {"n_gen": 0}

        sig_vals = [g.significance for g in gens]
        chain_lens = [g.generalization_level for g in gens]
        attractors = self.find_attractors(min_strength=0.3)
        macros_c = self.create_macro_tokens(Resolution.COARSE)
        macros_m = self.create_macro_tokens(Resolution.MEDIUM)

        return {
            "n_gen": n,
            "n_attractors": len(attractors),
            "n_macro_coarse": len(macros_c),
            "n_macro_medium": len(macros_m),
            "compression_coarse": round(self.compression_ratio(Resolution.COARSE), 3),
            "compression_medium": round(self.compression_ratio(Resolution.MEDIUM), 3),
            "avg_significance": round(sum(sig_vals) / n, 3),
            "max_significance": round(max(sig_vals), 3),
            "avg_chain_length": round(sum(chain_lens) / n, 2),
            "max_chain_length": max(chain_lens),
            "top_attractor_strength": attractors[0].strength if attractors else 0,
        }
