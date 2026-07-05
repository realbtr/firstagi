"""
CharGenDecoder — восстановление обозначений Gen символьного драйвера.

Проблема
--------
Gen, построенные CharTransitionDriver'ом, хранят feature_chain — список
feature_id-переходов между символами. Метка Gen = целевой символ или целевое
слово у граничного токена — не полная строка.

Решение
-------
Инвертировать кодирование RegionCharacteristics для каждого признака в цепочке:
  • target_chars.color_hue  →  нормированный unicode → конкретный символ
  • target_chars.brightness →  частотный ранг → disambiguation Кириллица/Латиница
  • feature.direction ≈ π/2 →  граница слова

Ограничения (важно понимать перед использованием)
---------------------------------------------------
1. Коллизии при tolerance=0.35.
   FeatureVector кодирует ОТНОСИТЕЛЬНЫЕ изменения. При переходе «от согласной
   к «а»» delta_color_hue → −2.0 для ЛЮБОЙ согласной высокого ранга. Это значит:
   «н→а» и «т→а» — один и тот же признак в базе (dist≈0.036 << 0.35).
   Аналогично «к→н» и «к→т» могут сливаться (dist≈0.314 < 0.35).
   Декодер сообщает confidence < 0.5 в таких случаях.

2. Регистр признаков = runtime-состояние.
   engine._features хранится в памяти. При сериализации сессии (pickle)
   признаки сохраняются, но если когда-либо будет реализован CapacityBudget
   для признаков — старые Gen потеряют ссылки.

3. source_chars первого признака — ненадёжно.
   Из-за коллизий source_chars[0] может показывать первый зарегистрированный
   символ-источник, а не тот, что реально стоял в Gen. Рекомендуется
   восстанавливать только TARGET-символы из target_chars.

Запуск демо
-----------
    py -X utf8 drivers/char_gen_decoder.py
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from .char_transition_driver import (
    FREQ_TABLE_RU, FREQ_TABLE_EN,
    _char_code_normalized,
)

if TYPE_CHECKING:
    from core.generalization import Generalization, GeneralizationBase
    from core.algorithm import AttractorEngine

_PI_HALF = math.pi / 2
_BOUNDARY_TOL = 0.05   # допуск: direction считается границей слова при |dir - π/2| < 0.05


# ══════════════════════════════════════════════════════════════════════════════
# Обратная таблица: color_hue → символ (точный)
# ══════════════════════════════════════════════════════════════════════════════

def _build_hue_table() -> Dict[float, Tuple[str, float]]:
    """
    Строит точную таблицу: color_hue → (символ, brightness).

    Используется для инверсии: если color_hue совпадает точно —
    confidence = 1.0. Если только приблизительно — confidence снижается.
    """
    table: Dict[float, Tuple[str, float]] = {}
    # Кириллица
    for ch, br in FREQ_TABLE_RU.items():
        hue = _char_code_normalized(ch)
        table[round(hue, 6)] = (ch, br)
    # ё (special case)
    hue_yo = _char_code_normalized("ё")
    table[round(hue_yo, 6)] = ("ё", FREQ_TABLE_RU.get("ё", 0.212))
    # Латиница
    for ch, br in FREQ_TABLE_EN.items():
        hue = _char_code_normalized(ch)
        rounded = round(hue, 6)
        if rounded not in table:   # Кириллица приоритетнее при совпадении
            table[rounded] = (ch, br)
    return table


_HUE_TABLE: Dict[float, Tuple[str, float]] = _build_hue_table()


def _invert_color_hue(hue: float, brightness: float) -> Tuple[Optional[str], float]:
    """
    Инвертировать color_hue → (символ, confidence ∈ [0,1]).

    Алгоритм:
      1. Точный поиск в _HUE_TABLE (confidence = 1.0 - brightness_error)
      2. Ближайший символ в Кириллице (инверсия формулы hue=(ord-1072)/31)
      3. Ближайший символ в Латинице  (инверсия формулы hue=(ord-97)/25)
      Выбирается кандидат с наименьшей ошибкой по brightness.

    Ключевое ограничение: при коллизиях (разные символы → один feature)
    возвращаемый символ — это символ, ПЕРВЫМ зарегистрированный в engine.
    Confidence отражает надёжность восстановления, а не семантическую точность.
    """
    # ── Прямой поиск по таблице ────────────────────────────────────────────────
    rounded = round(hue, 6)
    if rounded in _HUE_TABLE:
        ch, expected_br = _HUE_TABLE[rounded]
        conf = max(0.0, 1.0 - abs(expected_br - brightness) * 4)
        return ch, conf

    # ── Приближённый: Кириллица ────────────────────────────────────────────────
    best_char: Optional[str] = None
    best_conf: float = 0.0

    code_ru = round(hue * 31) + 1072
    if 1072 <= code_ru <= 1103:
        ch_ru = chr(code_ru)
        expected = FREQ_TABLE_RU.get(ch_ru, 0.5)
        conf_ru = max(0.0, 1.0 - abs(expected - brightness) * 4)
        if conf_ru > best_conf:
            best_conf = conf_ru
            best_char = ch_ru

    # ── Приближённый: Латиница ─────────────────────────────────────────────────
    code_en = round(hue * 25) + 97
    if 97 <= code_en <= 122:
        ch_en = chr(code_en)
        expected = FREQ_TABLE_EN.get(ch_en, 0.5)
        conf_en = max(0.0, 1.0 - abs(expected - brightness) * 4)
        if conf_en > best_conf:
            best_conf = conf_en
            best_char = ch_en

    # ── Специальные символы ────────────────────────────────────────────────────
    # ё (code=1105, hue≈0.210)
    if abs(hue - _char_code_normalized("ё")) < 0.02:
        expected = FREQ_TABLE_RU.get("ё", 0.212)
        conf_yo = max(0.0, 1.0 - abs(expected - brightness) * 4)
        if conf_yo > best_conf:
            best_conf = conf_yo
            best_char = "ё"

    return best_char, best_conf


# ══════════════════════════════════════════════════════════════════════════════
# Результат восстановления
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CharRecoveryResult:
    """
    Результат восстановления символьной строки из Gen.

    Поля
    ----
    words          — восстановленные слова (сгруппированы по границам direction=π/2)
    chars          — все восстановленные символы по порядку
    confidence     — средняя уверенность [0,1] по всем символам
    missing        — сколько feature_id не найдено в регистре движка
    collisions     — сколько символов восстановлены с conf < 0.5 (вероятные коллизии)
    chain_len      — длина feature_chain Gen
    """
    words:      List[str] = field(default_factory=list)
    chars:      List[str] = field(default_factory=list)
    confidence: float = 0.0
    missing:    int = 0
    collisions: int = 0
    chain_len:  int = 0

    @property
    def text(self) -> str:
        """Читаемое представление: слова через пробел."""
        return " ".join(w for w in self.words if w) if self.words else "".join(self.chars)

    @property
    def is_empty(self) -> bool:
        return not self.chars and not self.words

    @property
    def is_reliable(self) -> bool:
        """True если confidence ≥ 0.7 и нет пропущенных признаков."""
        return self.confidence >= 0.7 and self.missing == 0

    def __repr__(self) -> str:
        status = "OK" if self.is_reliable else ("PARTIAL" if not self.is_empty else "EMPTY")
        return (
            f"CharRecoveryResult({status} {self.text!r} "
            f"conf={self.confidence:.2f} miss={self.missing} coll={self.collisions})"
        )


# ══════════════════════════════════════════════════════════════════════════════
# CharGenDecoder
# ══════════════════════════════════════════════════════════════════════════════

class CharGenDecoder:
    """
    Восстанавливает символьную строку из Gen, построенного CharTransitionDriver'ом.

    Параметры
    ---------
    engine          — AttractorEngine с живым _features регистром
    include_source  — включать ли первый source-символ (ненадёжно из-за коллизий)

    Использование
    -------------
        decoder = CharGenDecoder(system.engine)
        result  = decoder.decode(gen)
        print(result.text, result.confidence)

        # Аннотировать всю базу
        n = decoder.annotate_base(system.base, min_confidence=0.65)
    """

    def __init__(self, engine: "AttractorEngine", include_source: bool = False) -> None:
        self._engine = engine
        self._include_source = include_source

    # ── Основной метод ─────────────────────────────────────────────────────────

    def decode(self, gen: "Generalization") -> CharRecoveryResult:
        """Восстановить строку из одного Gen."""
        result = CharRecoveryResult(chain_len=len(gen.feature_chain))
        if not gen.feature_chain:
            return result

        char_entries: List[Tuple[str, float, bool]] = []  # (char, conf, is_boundary)
        missing = 0
        collisions = 0

        # Первый признак: опционально восстанавливаем SOURCE
        if self._include_source:
            first_feat = self._engine.get_feature(gen.feature_chain[0])
            if first_feat is not None and first_feat.source_chars is not None:
                sc = first_feat.source_chars
                ch, conf = _invert_color_hue(sc.color_hue, sc.brightness)
                if ch:
                    is_boundary = abs(first_feat.direction - _PI_HALF) < _BOUNDARY_TOL
                    char_entries.append((ch, conf, is_boundary))
                    if conf < 0.5:
                        collisions += 1

        # Все признаки: восстанавливаем TARGET из target_chars
        for fid in gen.feature_chain:
            feat = self._engine.get_feature(fid)
            if feat is None:
                missing += 1
                continue
            tc = feat.target_chars
            if tc is None:
                missing += 1
                continue
            ch, conf = _invert_color_hue(tc.color_hue, tc.brightness)
            if ch is None:
                missing += 1
                continue
            is_boundary = abs(feat.direction - _PI_HALF) < _BOUNDARY_TOL
            char_entries.append((ch, conf, is_boundary))
            if conf < 0.5:
                collisions += 1

        if not char_entries:
            result.missing = missing
            return result

        # Группируем символы в слова по границам direction=π/2
        words: List[str] = []
        current_word: List[str] = []
        all_chars: List[str] = []
        total_conf = 0.0

        for ch, conf, is_boundary in char_entries:
            all_chars.append(ch)
            total_conf += conf
            if is_boundary:
                if current_word:
                    words.append("".join(current_word))
                current_word = [ch]
            else:
                current_word.append(ch)

        if current_word:
            words.append("".join(current_word))

        result.words = words
        result.chars = all_chars
        result.confidence = total_conf / len(char_entries)
        result.missing = missing
        result.collisions = collisions
        return result

    # ── Пакетная обработка ─────────────────────────────────────────────────────

    def decode_all(
        self,
        base: "GeneralizationBase",
        min_sig: float = 0.0,
        min_chain: int = 1,
    ) -> Dict[str, CharRecoveryResult]:
        """
        Восстановить строки для всех подходящих Gen в базе.

        Returns dict: gen_id → CharRecoveryResult
        """
        results: Dict[str, CharRecoveryResult] = {}
        for gen in base.all():
            if gen.significance < min_sig:
                continue
            if len(gen.feature_chain) < min_chain:
                continue
            results[gen.gen_id] = self.decode(gen)
        return results

    def annotate_base(
        self,
        base: "GeneralizationBase",
        min_confidence: float = 0.65,
        min_chain: int = 2,
        overwrite: bool = False,
    ) -> int:
        """
        Проставить метки Gen в базе через декодирование.

        Обновляет gen.label если:
          - label пустой ИЛИ overwrite=True
          - confidence ≥ min_confidence
          - chain_len ≥ min_chain

        Возвращает число обновлённых Gen.
        """
        updated = 0
        for gen in base.all():
            if len(gen.feature_chain) < min_chain:
                continue
            if gen.label and not overwrite:
                continue
            result = self.decode(gen)
            if result.is_empty or result.confidence < min_confidence:
                continue
            gen.label = result.text
            updated += 1
        return updated

    # ── Диагностика ────────────────────────────────────────────────────────────

    def collision_report(self, base: "GeneralizationBase") -> Dict[str, object]:
        """
        Отчёт о коллизиях в базе.

        Возвращает статистику:
          total_gen       — всего Gen проверено
          decoded_ok      — успешно декодировано (confidence ≥ 0.7)
          partial         — частично (0.3 ≤ conf < 0.7)
          failed          — не декодировано (conf < 0.3 или пусто)
          avg_confidence  — средняя уверенность
          collision_rate  — доля символов с conf < 0.5
        """
        total = ok = partial = failed = 0
        total_conf = 0.0
        total_chars = 0
        collision_chars = 0

        for gen in base.all():
            if not gen.feature_chain:
                continue
            r = self.decode(gen)
            total += 1
            total_conf += r.confidence
            total_chars += len(r.chars)
            collision_chars += r.collisions
            if r.confidence >= 0.7:
                ok += 1
            elif r.confidence >= 0.3:
                partial += 1
            else:
                failed += 1

        return {
            "total_gen":      total,
            "decoded_ok":     ok,
            "partial":        partial,
            "failed":         failed,
            "avg_confidence": total_conf / total if total else 0.0,
            "collision_rate": collision_chars / total_chars if total_chars else 0.0,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Демо
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from core.app import CoreApplication
    from core.algorithm import StepOutcome
    from drivers.char_transition_driver import CharTransitionDriver

    W  = "\033[0m"; BD = "\033[1m"; DM = "\033[90m"
    GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
    RD = "\033[91m"; MG = "\033[95m"

    def hdr(t: str) -> None:
        print(f"\n{BD}{CY}{'═'*60}{W}\n{BD}{CY}  {t}{W}\n{BD}{CY}{'═'*60}{W}\n")

    TEXTS = [
        "маша пошла в лес",
        "маша встретила медведя в лесу",
        "медведь нашёл мёд на дереве",
        "кот сидит на окне и смотрит в сад",
        "кошка и кот похожи но разные",
    ]

    # ── 1. Обучение ─────────────────────────────────────────────────────────────
    hdr("Обучение на 5 текстах (3 прохода, tolerance=0.35)")
    app = CoreApplication(config={"mock_teacher": False, "feature_tolerance": 0.35})
    app.startup()
    drv = CharTransitionDriver("chars")

    for _ in range(3):
        for t in TEXTS:
            for tok in drv.produce(t):
                app.system.process_token(tok)
            app.system.reset_context()

    base_size = app.system.base.size()
    feat_size = len(app.system.engine._features)
    print(f"  Gen в базе:    {base_size}")
    print(f"  Признаков:     {feat_size}")

    # ── 2. Декодирование ─────────────────────────────────────────────────────────
    hdr("Декодирование Gen (топ-20 по significance)")
    decoder = CharGenDecoder(app.system.engine)

    all_gens = sorted(app.system.base.all(), key=lambda g: -g.significance)
    print(f"  {'sig':>5}  {'chain':>5}  {'conf':>5}  {'ok?':>4}  decoded")
    print(f"  {'─'*55}")

    for gen in all_gens[:20]:
        r = decoder.decode(gen)
        ok = GR + "✓" + W if r.is_reliable else (AM + "~" + W if not r.is_empty else RD + "✗" + W)
        conf_col = GR if r.confidence >= 0.7 else (AM if r.confidence >= 0.4 else RD)
        text = r.text or "(пусто)"
        print(
            f"  {gen.significance:5.3f}  "
            f"{len(gen.feature_chain):>5}  "
            f"{conf_col}{r.confidence:5.2f}{W}  "
            f"{ok}  "
            f"{CY}«{text}»{W}"
            f"  {DM}miss={r.missing} coll={r.collisions}{W}"
        )

    # ── 3. Отчёт о коллизиях ────────────────────────────────────────────────────
    hdr("Отчёт о коллизиях (все Gen в базе)")
    report = decoder.collision_report(app.system.base)
    print(f"  Всего Gen:         {report['total_gen']}")
    print(f"  Декодировано OK:   {report['decoded_ok']}  (conf ≥ 0.7)")
    print(f"  Частично:          {report['partial']}  (conf 0.3–0.7)")
    print(f"  Не удалось:        {report['failed']}   (conf < 0.3)")
    print(f"  Средняя уверен.:   {report['avg_confidence']:.3f}")
    print(f"  Доля коллизий:     {report['collision_rate']:.1%}")

    # ── 4. Аннотирование базы ────────────────────────────────────────────────────
    hdr("Аннотирование базы (проставляем метки Gen с conf ≥ 0.65)")
    n = decoder.annotate_base(app.system.base, min_confidence=0.65, min_chain=2)
    print(f"  Обновлено меток: {n}")
    print()
    print(f"  Примеры аннотированных Gen:")
    for gen in sorted(app.system.base.all(), key=lambda g: -g.significance)[:10]:
        if gen.label:
            print(f"    sig={gen.significance:.3f}  chain={len(gen.feature_chain)}  «{CY}{gen.label}{W}»")

    # ── 5. Тест коллизии: «н→а» и «т→а» ────────────────────────────────────────
    hdr("Тест известной коллизии: «н→а» vs «т→а»")
    from core.feature import Feature, RegionCharacteristics
    from drivers.char_transition_driver import _char_to_region

    src_н  = _char_to_region("н", 0, 3, False, True)
    tgt_а  = _char_to_region("а", 1, 3, False, False)
    src_т  = _char_to_region("т", 0, 3, False, True)

    feat_на = Feature.from_regions("test-na", 0.0, 1.0, src_н, tgt_а)
    feat_та = Feature.from_regions("test-ta", 0.0, 1.0, src_т, tgt_а)

    dist = feat_на.vector.distance_to(feat_та.vector)
    print(f"  Расстояние между «н→а» и «т→а»:  {dist:.4f}  (tolerance=0.35)")
    print(f"  {'КОЛЛИЗИЯ' if dist < 0.35 else 'РАЗЛИЧИМЫ'}:  {'сливаются в один признак' if dist < 0.35 else 'разные признаки'}")
    print()

    ch_target, conf_target = _invert_color_hue(tgt_а.color_hue, tgt_а.brightness)
    print(f"  Восстановление TARGET из «н→а» / «т→а»:")
    print(f"    target_chars.color_hue = {tgt_а.color_hue:.4f}  → символ «{ch_target}»  conf={conf_target:.2f}")
    print(f"    (target восстанавливается верно, несмотря на коллизию источника)")
    print()

    ch_src_н, conf_н = _invert_color_hue(src_н.color_hue, src_н.brightness)
    ch_src_т, conf_т = _invert_color_hue(src_т.color_hue, src_т.brightness)
    print(f"  Восстановление SOURCE (ненадёжно при коллизии):")
    print(f"    source «н» → декодер видит «{ch_src_н}»  conf={conf_н:.2f}")
    print(f"    source «т» → декодер видит «{ch_src_т}»  conf={conf_т:.2f}")
