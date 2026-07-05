"""
Абстрактный базовый класс периферийного драйвера.

Шаг 11: добавлен буфер токенов и метод query() для активного внимания.
  load_buffer(tokens)      — загрузить токены в буфер
  query(feature)           — запросить лучший токен из буфера (извлекает)
  query_ranked(feature, n) — показать топ-n кандидатов без извлечения
  buffer_size              — текущий размер буфера
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from typing import Iterator, List, Optional, Tuple, TYPE_CHECKING

from core.generalization import PeripheralToken

if TYPE_CHECKING:
    from core.feature import Feature


class PeripheralDriver(ABC):
    """
    Абстрактный драйвер периферийного устройства.

    Задача:
        Преобразовать сырые данные в поток PeripheralToken.
        Не знает о нарративе, обобщениях или контексте.

    Шаг 11 — активное внимание:
        Драйвер хранит буфер токенов. Вместо того чтобы проталкивать
        токены в систему, он отвечает на запросы: query(feature) возвращает
        лучший совпадающий токен из буфера или None (буфер пуст).

    Подклассы реализуют:
        - TextDriver     (текстовый ввод → токены слов/символов)
        - ImageDriver    (изображение → токены-признаки областей)
        - SequenceDriver (числовые последовательности → токены переходов)
    """

    def __init__(self, driver_id: str) -> None:
        self.driver_id = driver_id
        self._buffer: deque[PeripheralToken] = deque()

    @abstractmethod
    def produce(self) -> Iterator[PeripheralToken]:
        """
        Сгенерировать поток токенов.
        Может быть конечным (batch) или бесконечным (stream).
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """Сбросить драйвер в начальное состояние."""
        ...

    # ------------------------------------------------------------------
    # Активное внимание: буфер + query

    def load_buffer(self, tokens: List[PeripheralToken]) -> int:
        """
        Загрузить токены в буфер.

        Возвращает новый размер буфера.
        Не заменяет — добавляет к существующему содержимому.
        """
        self._buffer.extend(tokens)
        return len(self._buffer)

    def query(self, feature: Optional["Feature"] = None) -> Optional[PeripheralToken]:
        """
        Запросить токен из буфера.

        feature=None  → вернуть следующий токен по FIFO.
        feature=F     → найти лучший совпадающий в первых lookahead токенах
                        (по расстоянию векторов). Если ничего не совпадает
                        в пределах lookahead — вернуть следующий по FIFO.

        Возвращает None если буфер пуст.
        """
        if not self._buffer:
            return None

        if feature is None:
            return self._buffer.popleft()

        # Семантический поиск: смотрим вперёд до 5 токенов
        lookahead = min(len(self._buffer), 5)
        buf_list = list(self._buffer)
        best_idx = 0
        best_dist = float("inf")

        for i in range(lookahead):
            tok = buf_list[i]
            if hasattr(tok.data, "vector"):
                d = feature.vector.distance_to(tok.data.vector)
                if d < best_dist:
                    best_dist = d
                    best_idx = i

        # Извлечь выбранный токен из буфера
        chosen = buf_list[best_idx]
        buf_list.pop(best_idx)
        self._buffer = deque(buf_list)
        return chosen

    def query_ranked(
        self,
        feature: Optional["Feature"] = None,
        n: int = 3,
        lookahead: int = 10,
    ) -> List[Tuple[PeripheralToken, float]]:
        """
        Показать топ-n кандидатов из буфера БЕЗ извлечения.

        feature=None  → первые n токенов по FIFO, расстояние=0.0.
        feature=F     → ранжировать по расстоянию к вектору F.

        Возвращает [(token, distance), ...] по возрастанию расстояния.
        Используется чтобы увидеть альтернативы до выбора через query().
        """
        if not self._buffer:
            return []

        buf_list = list(self._buffer)[:min(len(self._buffer), lookahead)]

        if feature is None:
            return [(tok, 0.0) for tok in buf_list[:n]]

        scored: List[Tuple[PeripheralToken, float]] = []
        for tok in buf_list:
            if hasattr(tok.data, "vector"):
                d = feature.vector.distance_to(tok.data.vector)
            else:
                d = 1.0
            scored.append((tok, d))

        scored.sort(key=lambda x: x[1])
        return scored[:n]

    def clear_buffer(self) -> None:
        """Очистить буфер токенов."""
        self._buffer.clear()

    @property
    def buffer_size(self) -> int:
        """Текущий размер буфера (количество токенов в очереди)."""
        return len(self._buffer)

    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.driver_id!r}, buf={self.buffer_size})"
