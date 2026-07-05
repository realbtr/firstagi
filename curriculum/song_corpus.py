"""
Шаг 12: Структурированный корпус «детской песенки».

Принцип: 5 блоков с нарастающей сложностью.
Каждый блок добавляет ровно один новый «слот» в паттерн,
а перед переходом к следующему якорь повторяется для закрепления.

  А (ANCHOR):    якорь      — 2-словные фразы, интенсивное повторение
  Б (ALTERNATE): чередование — те же фразы вперемешку (модель видит варианты)
  В (EXPAND):    расширение  — место как новый слот
  Г (DISAMBIG):  дизамбигуация — время выбирает действие
  Д (FULL):      полная сцена  — все 4 слота + контрастивные пары (кот/собака)

Почему детская песенка:
  - Возврат к якорю после каждого расширения → Gen не деградируют
  - Один новый слот за раз → REFUTED локализованы, создают нужный Gen
  - Параллельные структуры (кот [X] / собака [X]) → модель обобщает паттерн,
    а не объект — это фундамент ситуативного понимания
  - Контрастивные пары как финал → временной слот начинает работать
    только когда оба якоря стабильны
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List


class SongBlock(Enum):
    """Пять блоков нарастающей сложности."""
    ANCHOR    = "А"   # кот сидит × 3 варианта, много повторений
    ALTERNATE = "Б"   # те же фразы вперемешку
    EXPAND    = "В"   # + место (на окне / на диване)
    DISAMBIG  = "Г"   # + время (утром/вечером) → дизамбигуация предиката
    FULL      = "Д"   # все слоты + контраст кот/собака


class SongCorpus:
    """
    Структурированный корпус для обучения через «детскую песенку».

    Использование:
        corpus = SongCorpus()
        texts  = corpus.build_lesson(SongBlock.ANCHOR, iterations=8)
        driver.build_vocab(corpus.all_texts())
        for text in texts:
            session.load_buffer(text)
        steps = session.run_attention_until_empty()
    """

    # ── Базовые элементы ──────────────────────────────────────────────

    # Блок А/Б: якорь (субъект + предикат)
    ANCHORS: List[str] = [
        "кот сидит",
        "кот спит",
        "кот бежит",
    ]

    # Блок В: якорь + место
    WITH_PLACE: List[str] = [
        "кот сидит на окне",
        "кот спит на диване",
        "кот сидит у окна",
        "кот бежит по двору",
    ]

    # Блок Г: время + якорь (дизамбигуация предиката по времени)
    WITH_TIME: List[str] = [
        "утром кот сидит",
        "вечером кот спит",
        "утром кот бежит",
        "вечером кот сидит",
    ]

    # Блок Д: полная сцена (все 4 слота)
    FULL_SCENE: List[str] = [
        "утром кот сидит на окне",
        "вечером кот спит на диване",
        "утром кот бежит по двору",
        "вечером кот сидит у окна",
    ]

    # Блок Д: параллельная структура — собака
    DOG_ANCHORS: List[str] = [
        "собака бежит",
        "собака лает",
    ]

    DOG_FULL: List[str] = [
        "утром собака бежит",
        "вечером собака лает",
        "утром собака бежит по двору",
        "вечером собака лает громко",
    ]

    # Блок Д: контрастивные пары (ключ к ситуативному пониманию)
    CONTRAST: List[str] = [
        "утром кот сидит",
        "утром собака бежит",
        "вечером кот спит",
        "вечером собака лает",
        "утром кот сидит на окне",
        "утром собака бежит по двору",
    ]

    # ── Построение уроков ─────────────────────────────────────────────

    def build_lesson(self, block: SongBlock, iterations: int = 1) -> List[str]:
        """
        Построить последовательность текстов для одного блока урока.

        Порядок детерминирован и педагогически оптимален:
          - якорь повторяется перед расширением и после него
          - новый материал вводится один слот за раз
          - каждая итерация — полный «куплет» детской песенки
        """
        builders = {
            SongBlock.ANCHOR:    self._build_anchor,
            SongBlock.ALTERNATE: self._build_alternate,
            SongBlock.EXPAND:    self._build_expand,
            SongBlock.DISAMBIG:  self._build_disambig,
            SongBlock.FULL:      self._build_full,
        }
        return builders[block](iterations)

    def all_texts(self) -> List[str]:
        """Все уникальные тексты корпуса (для построения vocab заранее)."""
        seen = set()
        result = []
        for t in (
            self.ANCHORS
            + self.WITH_PLACE
            + self.WITH_TIME
            + self.FULL_SCENE
            + self.DOG_ANCHORS
            + self.DOG_FULL
            + self.CONTRAST
        ):
            if t not in seen:
                seen.add(t)
                result.append(t)
        return result

    def block_info(self) -> Dict[str, Dict]:
        """Метаданные блоков: рекомендуемые итерации и цель."""
        return {
            SongBlock.ANCHOR.value:    {"iters": 8, "goal": "L1 Gen sig→1.0, якорь стабилен"},
            SongBlock.ALTERNATE.value: {"iters": 5, "goal": "конкурирующие L1, модель знает варианты"},
            SongBlock.EXPAND.value:    {"iters": 6, "goal": "L3-L4 Gen, место как слот"},
            SongBlock.DISAMBIG.value:  {"iters": 5, "goal": "L5-L6 Gen, время выбирает предикат"},
            SongBlock.FULL.value:      {"iters": 4, "goal": "L7+ Gen, ситуация как единица"},
        }

    # ── Построители блоков ────────────────────────────────────────────

    def _build_anchor(self, n: int) -> List[str]:
        """
        Блок А: якорь.
        Паттерн: AA BB CC A (возврат к первому в конце каждого куплета).
        """
        seq: List[str] = []
        for _ in range(n):
            for text in self.ANCHORS:
                seq.extend([text, text])   # пара = мини-повтор
            seq.append(self.ANCHORS[0])    # возврат к первому
        return seq

    def _build_alternate(self, n: int) -> List[str]:
        """
        Блок Б: чередование.
        Порядок меняется от куплета к куплету — модель видит все варианты
        в разных позициях, не привязываясь к одному порядку.
        """
        orders = [
            [0, 1, 2],
            [0, 2, 1],
            [1, 0, 2],
        ]
        seq: List[str] = []
        for i in range(n):
            order = orders[i % len(orders)]
            for idx in order:
                seq.append(self.ANCHORS[idx])
        return seq

    def _build_expand(self, n: int) -> List[str]:
        """
        Блок В: расширение — место как новый слот.
        Паттерн: [короткий] → [расширенный] → [короткий] (закрепление).
        """
        pairs = [
            (self.ANCHORS[0], self.WITH_PLACE[0]),   # кот сидит / на окне
            (self.ANCHORS[1], self.WITH_PLACE[1]),   # кот спит / на диване
            (self.ANCHORS[0], self.WITH_PLACE[2]),   # кот сидит / у окна
        ]
        seq: List[str] = []
        for _ in range(n):
            for short, long in pairs:
                seq.append(short)    # якорь
                seq.append(long)     # расширение
                seq.append(short)    # возврат
        return seq

    def _build_disambig(self, n: int) -> List[str]:
        """
        Блок Г: дизамбигуация — время выбирает действие.
        Паттерн: [утром→сидит] / [вечером→спит] — контрастивные пары.
        Ключевой момент: модель должна понять что «утром» предсказывает
        «сидит», а «вечером» предсказывает «спит».
        """
        pairs = [
            (self.WITH_TIME[0], self.WITH_TIME[1]),   # утром сидит / вечером спит
            (self.WITH_TIME[2], self.WITH_TIME[1]),   # утром бежит / вечером спит
            (self.WITH_TIME[0], self.WITH_TIME[3]),   # утром сидит / вечером сидит (трудный случай)
        ]
        seq: List[str] = []
        for _ in range(n):
            for a, b in pairs:
                seq.append(a)
                seq.append(b)
                seq.append(a)   # возврат к «утреннему» варианту
        return seq

    def _build_full(self, n: int) -> List[str]:
        """
        Блок Д: полная сцена — все 4 слота одновременно.
        Собака вводится как параллельная структура.
        Контрастивные пары в финале активируют L7+ Gen.
        """
        seq: List[str] = []
        for _ in range(n):
            # Кот в полной форме (закрепление)
            seq.extend(self.FULL_SCENE[:2])
            # Собака как параллельная структура
            seq.extend(self.DOG_FULL[:2])
            # Контрастивные пары (кот vs собака, утро vs вечер)
            seq.extend(self.CONTRAST[:4])
            # Финальное повторение полной формы (оба субъекта)
            seq.append(self.FULL_SCENE[0])
            seq.append(self.DOG_FULL[2])
        return seq

    def __repr__(self) -> str:
        total = len(self.all_texts())
        return f"SongCorpus(texts={total}, blocks={len(SongBlock)})"
