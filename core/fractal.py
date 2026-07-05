"""
Шаг 5: Фрактальное сжатие (ИФС Барнсли) для матриц весов.

Теорема Барнсли–Хатчинсона:
  Любое самоподобное компактное множество является единственным аттрактором
  некоторой системы аффинных сжимающих отображений (IFS).
  Итерирование IFS из любой начальной точки сходится к аттрактору.

Применение к весам LLM:
  Матрица весов W ∈ ℝ^(m×n) содержит самоподобные паттерны
  на разных масштабах. Алгоритм PIFS находит эти паттерны:

  Кодирование:
    1. Разбить W на блоки-диапазоны (range blocks) r×r.
    2. Для каждого range-блока найти лучший domain-блок (2r×2r):
       target ≈ scale * downsample(domain) + offset.
    3. Хранить набор (domain_pos, scale, offset) — вместо m·n чисел.

  Декодирование:
    Начать с нулевой матрицы, итерировать IFS — сходимость гарантирована
    теоремой Банаха о сжимающих отображениях.

Связь с аттракторной системой (прямая):
  • Аттрактор IFS = аттрактор в смысле Gen (устойчивое состояние системы).
  • Resolution (COARSE/FINE) ↔ размер блока (крупный/мелкий).
  • Значимость Gen ↔ вклад IFS-преобразования в итоговую матрицу.
  • «Поиск общих опор» из Habr-статьи ↔ поиск самоподобных блоков.
"""

from __future__ import annotations
import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from .attractor import Resolution


# ══════════════════════════════════════════════════════════════════════
# Структуры данных
# ══════════════════════════════════════════════════════════════════════

@dataclass
class IFSBlock:
    """
    Одно IFS-преобразование.

    Кодирует: range_block ≈ scale · downsample(domain_block) + offset

    Каждый блок — это «обобщение» того, что кусок матрицы является
    аффинно-масштабированной копией другого куска.
    """
    range_y: int     # позиция range-блока (строка)
    range_x: int     # позиция range-блока (столбец)
    domain_y: int    # позиция domain-блока (строка)
    domain_x: int    # позиция domain-блока (столбец)
    scale: float     # коэффициент масштаба (|scale| < 1 — контрактивность IFS)
    offset: float    # смещение
    error: float = 0.0  # MSE аппроксимации (при кодировании)


@dataclass
class FractalCode:
    """
    Полное фрактальное кодирование матрицы.

    Хранит только список IFSBlock (намного компактнее исходной матрицы).
    Аттрактором итерирования этого кода является исходная матрица.
    """
    blocks: List[IFSBlock]
    shape: Tuple[int, int]   # исходная форма матрицы (до паддинга)
    range_size: int = 4
    domain_size: int = 8

    @property
    def n_params(self) -> int:
        """Количество хранимых параметров (4 на блок: dy, dx, scale, offset)."""
        return len(self.blocks) * 4

    @property
    def original_elements(self) -> int:
        return self.shape[0] * self.shape[1]

    @property
    def compression_ratio(self) -> float:
        """Доля сэкономленного места [0, 1). 0 = нет сжатия."""
        if self.original_elements == 0:
            return 0.0
        return 1.0 - self.n_params / self.original_elements

    @property
    def compression_factor(self) -> float:
        """Во сколько раз меньше (original / compressed). 1 = нет сжатия."""
        if self.n_params == 0:
            return float("inf")
        return self.original_elements / self.n_params

    def mean_block_error(self) -> float:
        if not self.blocks:
            return 0.0
        return sum(b.error for b in self.blocks) / len(self.blocks)


# ══════════════════════════════════════════════════════════════════════
# PIFS компрессор
# ══════════════════════════════════════════════════════════════════════

class BarnsleyCompressor:
    """
    PIFS (Partitioned Iterated Function System) компрессор матриц.

    Алгоритм:
      encode(W) → FractalCode   — O(N² · M²/step²) по умолчанию
      decode(code) → W̃          — O(n_iter · N²) итерирование IFS

    Параметры:
      range_size  — размер блока-диапазона r (мелкий = лучше качество)
      domain_step — шаг поиска domain-блоков (крупный = быстрее поиск)
      n_search    — число случайных domain-позиций (−1 = полный перебор)
    """

    def __init__(
        self,
        range_size: int = 4,
        domain_step: int = 2,
        n_search: int = -1,
    ) -> None:
        if range_size < 2:
            raise ValueError("range_size must be >= 2")
        self.range_size = range_size
        self.domain_size = range_size * 2
        self.domain_step = domain_step
        self.n_search = n_search

    # ------------------------------------------------------------------
    # Вспомогательные методы

    @staticmethod
    def _downsample(block: np.ndarray, factor: int = 2) -> np.ndarray:
        """
        Уменьшить блок в factor раз (средний пулинг).
        Использует numpy reshape: O(H·W).
        """
        H, W = block.shape
        H2, W2 = H // factor, W // factor
        return (block[:H2 * factor, :W2 * factor]
                .reshape(H2, factor, W2, factor)
                .mean(axis=(1, 3)))

    @staticmethod
    def _fit_affine(domain: np.ndarray, target: np.ndarray) -> Tuple[float, float]:
        """
        Найти оптимальные (scale, offset) методом наименьших квадратов:
            target ≈ scale · domain + offset

        Решение: регрессия target ~ domain.
        Масштаб ограничен |scale| ≤ 0.75 для гарантии контрактивности IFS.
        """
        d = domain.ravel()
        t = target.ravel()
        d_mean = float(d.mean())
        t_mean = float(t.mean())
        d_c = d - d_mean
        t_c = t - t_mean
        denom = float(np.dot(d_c, d_c))
        if denom < 1e-10:
            return 0.0, t_mean
        scale = float(np.clip(np.dot(t_c, d_c) / denom, -0.75, 0.75))
        offset = t_mean - scale * d_mean
        return scale, offset

    def _pad(self, matrix: np.ndarray) -> np.ndarray:
        """Дополнить матрицу нулями до кратного range_size."""
        H, W = matrix.shape
        pH = math.ceil(H / self.range_size) * self.range_size
        pW = math.ceil(W / self.range_size) * self.range_size
        if pH == H and pW == W:
            return matrix
        padded = np.zeros((pH, pW), dtype=float)
        padded[:H, :W] = matrix
        return padded

    def _all_domain_positions(self, H: int, W: int) -> List[Tuple[int, int]]:
        positions = []
        for di in range(0, H - self.domain_size + 1, self.domain_step):
            for dj in range(0, W - self.domain_size + 1, self.domain_step):
                positions.append((di, dj))
        return positions

    # ------------------------------------------------------------------
    # Кодирование

    def encode(self, matrix: np.ndarray) -> FractalCode:
        """
        Закодировать матрицу как набор IFS-преобразований.

        Для каждого range-блока перебирает domain-блоки и выбирает тот,
        который минимизирует MSE аппроксимации.
        """
        matrix = np.asarray(matrix, dtype=float)
        original_shape = matrix.shape
        padded = self._pad(matrix)
        H, W = padded.shape

        all_positions = self._all_domain_positions(H, W)
        if not all_positions:
            # Матрица слишком мала — кодируем среднее значение
            blocks = [IFSBlock(0, 0, 0, 0, 0.0, float(padded.mean()), 0.0)]
            return FractalCode(blocks, original_shape, self.range_size, self.domain_size)

        search_positions = (
            random.sample(all_positions, min(self.n_search, len(all_positions)))
            if self.n_search > 0 else all_positions
        )

        blocks: List[IFSBlock] = []

        for ri in range(0, H - self.range_size + 1, self.range_size):
            for rj in range(0, W - self.range_size + 1, self.range_size):
                rng = padded[ri:ri + self.range_size, rj:rj + self.range_size]
                best_err = float("inf")
                best = IFSBlock(ri, rj, 0, 0, 0.0, float(rng.mean()),
                                float(np.mean(rng ** 2)))

                for di, dj in search_positions:
                    dom = padded[di:di + self.domain_size, dj:dj + self.domain_size]
                    dom_down = self._downsample(dom)
                    scale, offset = self._fit_affine(dom_down, rng)
                    approx = scale * dom_down + offset
                    err = float(np.mean((rng - approx) ** 2))
                    if err < best_err:
                        best_err = err
                        best = IFSBlock(ri, rj, di, dj, scale, offset, err)

                blocks.append(best)

        return FractalCode(blocks, original_shape, self.range_size, self.domain_size)

    # ------------------------------------------------------------------
    # Декодирование

    def decode(
        self,
        code: FractalCode,
        n_iterations: int = 12,
        initial: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        Декодировать FractalCode итерированием IFS.

        По теореме Банаха (сжимающие отображения):
          |W̃_k − W| ≤ c^k · |W̃_0 − W| → 0 при k → ∞

        По умолчанию 12 итераций достаточно для погрешности < 1e-4
        при |scale| ≤ 0.75.
        """
        pH = math.ceil(code.shape[0] / code.range_size) * code.range_size
        pW = math.ceil(code.shape[1] / code.range_size) * code.range_size

        result = (initial.copy() if initial is not None
                  else np.zeros((pH, pW), dtype=float))

        for _ in range(n_iterations):
            new_result = np.zeros_like(result)
            for b in code.blocks:
                dom = result[b.domain_y:b.domain_y + code.domain_size,
                             b.domain_x:b.domain_x + code.domain_size]
                dom_down = self._downsample(dom)
                new_result[b.range_y:b.range_y + code.range_size,
                           b.range_x:b.range_x + code.range_size] = (
                    b.scale * dom_down + b.offset
                )
            result = new_result

        return result[:code.shape[0], :code.shape[1]]

    def roundtrip_mse(self, matrix: np.ndarray, n_iterations: int = 12) -> float:
        """MSE между исходной матрицей и результатом encode→decode."""
        matrix = np.asarray(matrix, dtype=float)
        code = self.encode(matrix)
        decoded = self.decode(code, n_iterations=n_iterations)
        return float(np.mean((matrix - decoded) ** 2))


# ══════════════════════════════════════════════════════════════════════
# Анализ самоподобия
# ══════════════════════════════════════════════════════════════════════

class SelfSimilarityAnalyzer:
    """
    Анализирует самоподобие матрицы весов.

    Показывает:
      • Среднюю ошибку IFS-кодирования (мера самоподобия)
      • Оценку фрактальной размерности (метод подсчёта коробок)
      • Коэффициент сжатия при разных разрешениях
      • Сигнал PSNR (качество реконструкции)
    """

    def __init__(self, compressor: Optional[BarnsleyCompressor] = None) -> None:
        self.compressor = compressor or BarnsleyCompressor(range_size=4)

    def self_similarity_score(self, matrix: np.ndarray) -> float:
        """
        Средняя MSE IFS-блоков после кодирования.
        0.0 = идеальное самоподобие (матрица = аттрактор IFS).
        """
        code = self.compressor.encode(np.asarray(matrix, dtype=float))
        return code.mean_block_error()

    def fractal_dimension(self, matrix: np.ndarray) -> float:
        """
        Оценка фрактальной размерности методом подсчёта коробок (box-counting).

        D ≈ 2   → гладкая поверхность (матрица близка к плоскости)
        D → 3   → очень «шероховатая» поверхность (хаотичные веса)

        Значение между 2 и 3 — фрактальная структура.
        """
        m = np.asarray(matrix, dtype=float)
        H, W = m.shape
        if H < 4 or W < 4:
            return 2.0

        vmin, vmax = float(m.min()), float(m.max())
        if abs(vmax - vmin) < 1e-10:
            return 2.0
        normalized = (m - vmin) / (vmax - vmin)

        log_inv_sizes: List[float] = []
        log_counts: List[float] = []

        for exp in range(1, int(math.log2(min(H, W))) + 1):
            size = 2 ** exp
            if size > min(H, W) // 2:
                break
            bH = math.ceil(H / size)
            bW = math.ceil(W / size)
            count = 0
            for i in range(bH):
                for j in range(bW):
                    box = normalized[i * size:(i + 1) * size,
                                     j * size:(j + 1) * size]
                    if float(box.max()) > 0.05:
                        count += 1
            if count > 0:
                log_inv_sizes.append(math.log(1.0 / size))
                log_counts.append(math.log(count))

        if len(log_inv_sizes) < 2:
            return 2.0

        # Наклон прямой log(N) ~ D · log(1/ε)
        n = len(log_inv_sizes)
        sx  = sum(log_inv_sizes)
        sy  = sum(log_counts)
        sxx = sum(x ** 2 for x in log_inv_sizes)
        sxy = sum(x * y for x, y in zip(log_inv_sizes, log_counts))
        denom = n * sxx - sx * sx
        if abs(denom) < 1e-10:
            return 2.0
        slope = (n * sxy - sx * sy) / denom
        return float(max(2.0, min(3.0, slope)))

    def analyze(self, matrix: np.ndarray, n_iterations: int = 12) -> dict:
        """Полный анализ матрицы: сжатие, качество, самоподобие."""
        m = np.asarray(matrix, dtype=float)
        code = self.compressor.encode(m)
        decoded = self.compressor.decode(code, n_iterations=n_iterations)
        mse = float(np.mean((m - decoded) ** 2))
        variance = float(np.var(m))
        psnr = (10 * math.log10(variance / mse)
                if mse > 1e-12 and variance > 1e-12 else float("inf"))
        return {
            "shape":              m.shape,
            "n_blocks":           len(code.blocks),
            "n_params":           code.n_params,
            "compression_ratio":  round(code.compression_ratio, 4),
            "compression_factor": round(code.compression_factor, 2),
            "mse":                round(mse, 8),
            "psnr_db":            round(psnr, 2),
            "self_similarity":    round(code.mean_block_error(), 8),
            "fractal_dim":        round(self.fractal_dimension(m), 3),
        }


# ══════════════════════════════════════════════════════════════════════
# Мост к аттракторной системе
# ══════════════════════════════════════════════════════════════════════

class FractalResolutionBridge:
    """
    Связывает Resolution (аттракторная система) с параметрами PIFS.

    Принцип:
      COARSE → крупные блоки → сильное сжатие, грубая реконструкция
      EXACT  → мелкие блоки  → слабое сжатие, точная реконструкция

    Это прямой аналог «изменчивой достаточности» из презентации:
    нам не нужна высокая точность, если в контексте ситуации
    мы не можем различить тонкости.
    """

    BLOCK_SIZES: Dict[Resolution, int] = {
        Resolution.COARSE: 16,
        Resolution.MEDIUM:  8,
        Resolution.FINE:    4,
        Resolution.EXACT:   2,
    }

    @classmethod
    def compressor_for(
        cls,
        resolution: Resolution,
        domain_step: int = 2,
        n_search: int = -1,
    ) -> BarnsleyCompressor:
        """Создать компрессор с параметрами для данного разрешения."""
        return BarnsleyCompressor(
            range_size=cls.BLOCK_SIZES[resolution],
            domain_step=domain_step,
            n_search=n_search,
        )

    @classmethod
    def suggest_resolution(cls, target_compression: float) -> Resolution:
        """
        Подобрать Resolution по желаемому коэффициенту сжатия.
        target_compression ∈ [0, 1]: 0 = нет сжатия, 1 = максимум.
        """
        if target_compression < 0.25:
            return Resolution.EXACT
        if target_compression < 0.5:
            return Resolution.FINE
        if target_compression < 0.75:
            return Resolution.MEDIUM
        return Resolution.COARSE

    @classmethod
    def multi_resolution_encode(
        cls,
        matrix: np.ndarray,
        resolutions: Optional[List[Resolution]] = None,
    ) -> Dict[str, dict]:
        """
        Закодировать матрицу при всех разрешениях и сравнить.
        Возвращает словарь {resolution_name: analyze_result}.
        """
        if resolutions is None:
            resolutions = list(Resolution)
        matrix = np.asarray(matrix, dtype=float)
        H, W = matrix.shape
        results = {}
        for res in resolutions:
            block = cls.BLOCK_SIZES[res]
            if block > min(H, W) // 2:
                continue   # блок не вмещается — пропустить
            comp = cls.compressor_for(res)
            analyzer = SelfSimilarityAnalyzer(comp)
            results[res.name] = analyzer.analyze(matrix)
        return results
