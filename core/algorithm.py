"""
Главный алгоритм — Разрешение Неопределённости (AttractorEngine).

Цикл (из статьи Habr):

  1. Из актуального контекста берём ОЖИДАЕМЫЙ ПРИЗНАК.
  2. Сравниваем с реальным признаком из токена.
  3. Если ПОДТВЕРЖДЁН  → берём следующий ожидаемый признак из контекста.
  4. Если ОПРОВЕРГНУТ  → создаём НОВОЕ ОБОБЩЕНИЕ + убираем опровергнутые Gen.
  5. Если контекст ПУСТ или ЗАВЕРШЁН →
     исследуем окрестности наименее обобщённого (короткие цепочки).

Алгоритм консолидации (фоновый):
  - Записывает статистику переходов.
  - При накоплении достаточной статистики:
    находит общие «опоры» конкурирующих обобщений (поиск общих опор).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Tuple
import uuid

from .feature import Feature, FeatureVector
from .generalization import Generalization, GeneralizationBase, PeripheralToken
from .context import ContextBuffer
from .provisional import ProvisionalBase


class StepOutcome(Enum):
    """Результат одного шага главного алгоритма."""
    CONFIRMED     = auto()   # признак подтверждён, контекст продолжается
    REFUTED       = auto()   # признак опровергнут, создано новое обобщение
    COMPLETED     = auto()   # всё обобщение полностью подтверждено (успех)
    EXPLORING     = auto()   # контекст пуст/завершён, исследуем окрестности
    CYCLE_AVOIDED = auto()   # токен уже был — пропускаем


@dataclass
class StepResult:
    """Результат одного шага движения внимания."""
    outcome: StepOutcome
    token: PeripheralToken
    matched_feature_id: Optional[str] = None
    new_gen_id: Optional[str] = None            # создано при REFUTED
    completed_gen_ids: List[str] = field(default_factory=list)
    removed_gen_ids: List[str] = field(default_factory=list)
    message: str = ""


class AttractorEngine:
    """
    Движок прямого исчисления аттрактора.

    Реализует главный алгоритм разрешения неопределённости.
    Управляет:
        - GeneralizationBase (долговременная память / опыт)
        - ContextBuffer      (рабочая память / актуальный контекст)
        - Реестром Feature   (все известные признаки)
    """

    def __init__(
        self,
        base: GeneralizationBase,
        feature_tolerance: float = 0.3,
        min_context_gens: int = 1,
        max_history: int = 1000,
        provisional: Optional[ProvisionalBase] = None,
    ) -> None:
        self.base = base
        self.context = ContextBuffer()
        self._features: dict[str, Feature] = {}          # все известные признаки
        self.feature_tolerance = feature_tolerance        # порог совпадения признаков
        self.min_context_gens = min_context_gens
        self.max_history = max_history
        self._step_count: int = 0
        self._provisional = provisional

    # ------------------------------------------------------------------
    # Управление признаками

    def register_feature(self, feature: Feature) -> Feature:
        """Зарегистрировать признак в реестре."""
        self._features[feature.feature_id] = feature
        return feature

    def get_feature(self, feature_id: str) -> Optional[Feature]:
        return self._features.get(feature_id)

    def find_matching_feature(self, incoming: Feature) -> Optional[str]:
        """
        Найти уже известный признак, совпадающий с входящим.
        Возвращает feature_id наилучшего совпадения или None.
        """
        best_id: Optional[str] = None
        best_dist = float("inf")
        for fid, known in self._features.items():
            d = incoming.vector.distance_to(known.vector)
            if d < best_dist and d <= self.feature_tolerance:
                best_dist = d
                best_id = fid
        return best_id

    # ------------------------------------------------------------------
    # Инициализация контекста из базы

    def load_context_from_base(self, top_n: int = 10) -> int:
        """
        Загрузить в контекст top-N самых значимых обобщений из базы.
        Вызывается при старте или сбросе внимания.
        Возвращает количество загруженных Gen.
        """
        top = self.base.rank()[:top_n]
        for gen in top:
            if gen.generalization_level > 0:
                self.context.add_active(gen.gen_id)
        return len(top)

    # ------------------------------------------------------------------
    # ГЛАВНЫЙ ШАГ АЛГОРИТМА

    def step(self, token: PeripheralToken) -> StepResult:
        """
        Один шаг направленного движения внимания.

        Цикл (из статьи Habr):
          1. Если контекст пуст/завершён — загрузить кандидатов для текущего токена.
          2. Попытаться сопоставить токен с ожидаемыми признаками.
          3. Подтверждён  → CONFIRMED / COMPLETED.
          4. Опровергнут  → REFUTED, новое обобщение.
          5. Нет кандидатов → EXPLORING.

        Ключевое изменение относительно v1:
          Загрузка контекста и сопоставление происходят в ОДНОМ шаге.
          Первый токен предложения тоже может дать CONFIRMED/COMPLETED,
          если в базе уже есть подходящее обобщение.
        """
        self._step_count += 1

        # Вытеснить устаревшие provisional Gen
        if self._provisional is not None:
            for evict_id in self._provisional.tick():
                self.base.remove(evict_id)
                self.context.remove_active(evict_id)

        # Защита от циклов
        if self.context.seen(token.token_id):
            return StepResult(
                outcome=StepOutcome.CYCLE_AVOIDED,
                token=token,
                message="Токен уже обрабатывался — пропуск.",
            )
        self.context.add_to_history(token.token_id)

        # Разобрать токен в Feature
        # Дедупликация: регистрируем новый feature_id только если нет похожего
        # в пределах tolerance. Это предотвращает засорение _features дублями
        # (каждый вызов learn() порождал новый UUID для той же траектории).
        incoming_feature = self._token_to_feature(token)
        if incoming_feature and self.find_matching_feature(incoming_feature) is None:
            self.register_feature(incoming_feature)

        # Очистить завершённые Gen перед следующим шагом.
        # Удаляем проактивно (а не только когда ВСЕ завершены),
        # чтобы «зомби» (выполненные chain=1 Gen) не блокировали
        # загрузку свежих кандидатов при REFUTED-каскадах.
        self.context.clear_completed(self.base)

        # Если контекст пуст — загрузить кандидатов для текущего признака
        if self.context.is_empty():
            loaded = self._load_context_for_feature(incoming_feature, token_label=token.label)
            if loaded == 0:
                # База пуста или нет совпадений → чистое исследование
                return StepResult(
                    outcome=StepOutcome.EXPLORING,
                    token=token,
                    message="Контекст пуст, нет кандидатов.",
                )

        # Получить ожидаемые признаки
        expected = self.context.get_expected_features(self.base)
        if not expected:
            return StepResult(
                outcome=StepOutcome.EXPLORING,
                token=token,
                message="Нет ожидаемых признаков в контексте.",
            )

        # Нет входящего признака → REFUTED
        if incoming_feature is None:
            return self._handle_refuted(token, expected, incoming_feature=None)

        # Сопоставить входящий признак с ожидаемыми
        matched_gen_id, matched_feat_id = self._match_expected(incoming_feature, expected)

        if matched_feat_id is not None:
            # ПОДТВЕРЖДЁН
            # Зафиксировать подтверждение provisional Gen, ожидавших этот признак
            if self._provisional is not None:
                for gen_id, feat_id in expected.items():
                    if feat_id == matched_feat_id and self._provisional.is_tracked(gen_id):
                        self._provisional.confirm(gen_id)

            completed = self.context.confirm_feature(matched_feat_id, self.base)
            # Фиксируем переход для статистики
            next_expected = self.context.get_expected_features(self.base)
            for next_feat_id in next_expected.values():
                self.base.record_transition(matched_feat_id, next_feat_id)

            token.gen_id = matched_gen_id

            if completed:
                return StepResult(
                    outcome=StepOutcome.COMPLETED,
                    token=token,
                    matched_feature_id=matched_feat_id,
                    completed_gen_ids=completed,
                    message=f"Обобщения завершены: {completed}",
                )
            return StepResult(
                outcome=StepOutcome.CONFIRMED,
                token=token,
                matched_feature_id=matched_feat_id,
                message=f"Признак {matched_feat_id[:8]}… подтверждён.",
            )
        else:
            # ОПРОВЕРГНУТ
            return self._handle_refuted(token, expected, incoming_feature)

    # ------------------------------------------------------------------
    # Вспомогательные методы

    def _token_to_feature(self, token: PeripheralToken) -> Optional[Feature]:
        """
        Извлечь Feature из токена.
        Драйверы могут класть Feature напрямую или сырые данные.
        """
        if isinstance(token.data, Feature):
            return token.data
        return None

    def _match_expected(
        self,
        incoming: Feature,
        expected: dict[str, str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Сопоставить входящий признак с ожидаемыми.
        Возвращает (gen_id, feature_id) наилучшего совпадения.
        """
        best_gen_id: Optional[str] = None
        best_feat_id: Optional[str] = None
        best_dist = float("inf")

        for gen_id, feat_id in expected.items():
            known = self._features.get(feat_id)
            if known is None:
                continue
            d = incoming.vector.distance_to(known.vector)
            if d < best_dist and d <= self.feature_tolerance:
                best_dist = d
                best_gen_id = gen_id
                best_feat_id = feat_id

        return best_gen_id, best_feat_id

    def _handle_refuted(
        self,
        token: PeripheralToken,
        expected: dict[str, str],
        incoming_feature: Optional[Feature],
    ) -> StepResult:
        """
        Признак опровергнут.
        1. Удалить из контекста опровергнутые Gen.
        2. Создать новое обобщение (или зарегистрировать новый признак).
        """
        # Опровергнуть все ожидавшие Gen
        removed_ids: List[str] = []
        for gen_id, feat_id in list(expected.items()):
            removed = self.context.refute_feature(feat_id, self.base)
            removed_ids.extend(removed)

        # Создать новое обобщение для нового признака
        new_gen: Optional[Generalization] = None
        if incoming_feature is not None:
            # Зарегистрировать как атомарный признак-обобщение
            new_feat_id = self._ensure_feature_registered(incoming_feature)
            new_gen = Generalization.new(
                feature_chain=[new_feat_id],
                label=token.label or f"auto_{self._step_count}",
            )
            self.base.add(new_gen)
            self.context.add_active(new_gen.gen_id)
            if self._provisional is not None:
                self._provisional.track(new_gen.gen_id)

        return StepResult(
            outcome=StepOutcome.REFUTED,
            token=token,
            new_gen_id=new_gen.gen_id if new_gen else None,
            removed_gen_ids=removed_ids,
            message=(
                f"Признак опровергнут. Удалено Gen: {removed_ids}. "
                f"Создано: {new_gen.gen_id[:8] if new_gen else '—'}…"
            ),
        )

    def _ensure_feature_registered(self, feature: Feature) -> str:
        """Найти или зарегистрировать признак, вернуть его ID."""
        existing_id = self.find_matching_feature(feature)
        if existing_id:
            return existing_id
        self.register_feature(feature)
        return feature.feature_id

    def recall_operation_context(self, cue_gen_id, instance_id, channel_id):
        """Restore learned command continuations in the live context after cue intake.

        This remains a metered full scan, not a claimed local index. Scope and
        role checks precede context admission; A3 adds the shared causal guard.
        """
        cue = self.base.get(cue_gen_id)
        if cue is None or len(cue.feature_chain) != 1:
            raise ValueError("Cue must refer to a native atomic Gen")
        restored = []
        for gen in self.base.iter_operation_records():
            link = getattr(gen, "actual_link", None)
            if (link == (instance_id, channel_id, cue_gen_id, gen.oper_id, gen.goal_id)
                    and gen.oper_id and gen.goal_id and len(gen.feature_chain) == 3
                    and gen.feature_chain[0] == cue.feature_chain[0]
                    and getattr(gen, "actual_chain", None) == tuple(gen.feature_chain)
                    and getattr(gen, "actual_evidence", {})
                    and sum(e.origin for e in gen.actual_evidence.values()) == 1):
                restored.append(gen.gen_id)
        for gid in getattr(self, "_operation_context_ids", ()):
            self.context.remove_active(gid)
        for gid in restored:
            self.context.add_active(gid, current_feature_index=1)
        self._operation_context_ids = tuple(restored)
        return tuple(restored)

    def _load_context_for_feature(
        self,
        incoming_feature: Optional[Feature],
        token_label: Optional[str] = None,
    ) -> int:
        """
        Загрузить кандидатов в контекст для текущего признака.

        Стратегия:
          1. Найти Gen, начинающийся с признака, похожего на входящий.
          2. Если не найдено — загрузить малообобщённые Gen.
          3. Если база пуста — создать новый одиночный Gen.

        Возвращает количество загруженных Gen.
        """
        loaded = 0

        # Приоритет 1: только chain=1 Gen по входящему признаку.
        # Загружаем исключительно атомарные Gen (chain_len=1), чтобы избежать
        # «загрязнения контекста» длинными Gen из других текстов/ситуаций:
        # chain≥2 Gen могут ожидать признаки, специфичные для другого потока,
        # и при несовпадении вызывать лавину REFUTED-событий.
        if incoming_feature is not None:
            existing_feat_id = self.find_matching_feature(incoming_feature)
            if existing_feat_id:
                candidates = self.base.search_by_prefix([existing_feat_id])
                for gen in candidates:
                    if len(gen.feature_chain) == 1:
                        self.context.add_active(gen.gen_id)
                        loaded += 1

        # Приоритет 2: малообобщённые Gen (исследование окрестностей)
        if loaded == 0:
            low_level = self.base.low_level(max_chain_length=1)
            for gen in low_level[:self.min_context_gens * 3]:
                self.context.add_active(gen.gen_id)
                loaded += 1

        # Приоритет 3: база пуста → первичное обобщение
        if loaded == 0 and incoming_feature is not None:
            feat_id = self._ensure_feature_registered(incoming_feature)
            new_gen = Generalization.new(
                feature_chain=[feat_id],
                label=token_label or "root",
            )
            self.base.add(new_gen)
            self.context.add_active(new_gen.gen_id)
            loaded = 1

        return loaded

    # ------------------------------------------------------------------
    # Алгоритм консолидации (упрощённая версия)

    def consolidate(self, min_success: int = 5) -> List[Generalization]:
        """
        Алгоритм консолидации: найти и объединить обобщения с общими «опорами».

        Логика:
          - Найти пары Gen с одинаковым началом цепочки признаков.
          - Если оба достаточно подтверждены → создать новый Gen более высокого уровня.
          - Новый Gen включает общий префикс + ссылки на обе ветки как children.

        Возвращает список вновь созданных обобщений.
        """
        created: List[Generalization] = []
        gens = [g for g in self.base.all() if g.success_count >= min_success]

        merged: set[str] = set()
        for i, g1 in enumerate(gens):
            if g1.gen_id in merged:
                continue
            for g2 in gens[i + 1:]:
                if g2.gen_id in merged:
                    continue
                prefix = self._common_prefix(g1.feature_chain, g2.feature_chain)
                if len(prefix) >= 1 and prefix != g1.feature_chain:
                    # Нашли общий префикс — создаём обобщение более высокого уровня
                    existing = self.base.search_by_chain(prefix)
                    if existing:
                        parent = existing[0]
                    else:
                        parent = Generalization.new(
                            feature_chain=prefix,
                            label=f"consolidated_{len(prefix)}",
                        )
                        parent.success_count = (g1.success_count + g2.success_count) // 2
                        self.base.add(parent)
                        created.append(parent)

                    self.base.link(parent.gen_id, g1.gen_id)
                    self.base.link(parent.gen_id, g2.gen_id)
                    merged.add(g1.gen_id)
                    merged.add(g2.gen_id)

        return created

    @staticmethod
    def _common_prefix(a: List[str], b: List[str]) -> List[str]:
        prefix = []
        for x, y in zip(a, b):
            if x == y:
                prefix.append(x)
            else:
                break
        return prefix

    # ------------------------------------------------------------------

    @property
    def step_count(self) -> int:
        return self._step_count

    def __repr__(self) -> str:
        return (
            f"AttractorEngine("
            f"base={self.base}, "
            f"context={self.context}, "
            f"features={len(self._features)}, "
            f"steps={self._step_count})"
        )
