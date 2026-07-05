"""
Тесты Шага 5: Фрактальное сжатие ИФС Барнсли.

Покрывают:
  - IFSBlock / FractalCode — структуры данных и вычисляемые свойства
  - BarnsleyCompressor:
      _downsample, _fit_affine, _pad,
      encode (размер кода, наличие блоков),
      decode (сходимость, корректность форм),
      roundtrip для постоянной и самоподобной матриц
  - SelfSimilarityAnalyzer: score, fractal_dim, analyze
  - FractalResolutionBridge: block_sizes, compressor_for,
                              suggest_resolution, multi_resolution_encode
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
import pytest
import numpy as np

from core.fractal import (
    IFSBlock, FractalCode,
    BarnsleyCompressor,
    SelfSimilarityAnalyzer,
    FractalResolutionBridge,
)
from core.attractor import Resolution


# ── вспомогательные матрицы ────────────────────────────────────────────────

def _const(val=1.0, shape=(16, 16)) -> np.ndarray:
    """Постоянная матрица — идеально самоподобна."""
    return np.full(shape, val)


def _rank1(shape=(16, 16), seed=0) -> np.ndarray:
    """Ранг-1 матрица — высокая самоподобность."""
    rng = np.random.default_rng(seed)
    u = rng.standard_normal(shape[0])
    v = rng.standard_normal(shape[1])
    return np.outer(u, v)


def _random(shape=(16, 16), seed=42) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(shape)


def _checkerboard(shape=(16, 16)) -> np.ndarray:
    """Шахматная доска — самоподобна при чётных блоках."""
    m = np.indices(shape).sum(axis=0) % 2
    return m.astype(float)


# ══════════════════════════════════════════════════════════════════════
# IFSBlock и FractalCode
# ══════════════════════════════════════════════════════════════════════

class TestFractalCode:
    def test_n_params(self):
        blocks = [IFSBlock(0, 0, 0, 0, 0.5, 0.0) for _ in range(4)]
        code = FractalCode(blocks=blocks, shape=(8, 8), range_size=4, domain_size=8)
        assert code.n_params == 16   # 4 блока × 4 параметра

    def test_original_elements(self):
        code = FractalCode([], (12, 8), range_size=4, domain_size=8)
        assert code.original_elements == 96

    def test_compression_ratio_positive(self):
        # 4 блока в матрице 8×8 → n_params=16, original=64, ratio=1−16/64=0.75
        blocks = [IFSBlock(0, 0, 0, 0, 0.5, 0.0) for _ in range(4)]
        code = FractalCode(blocks=blocks, shape=(8, 8), range_size=4, domain_size=8)
        assert code.compression_ratio == pytest.approx(0.75)

    def test_compression_factor(self):
        blocks = [IFSBlock(0, 0, 0, 0, 0.5, 0.0) for _ in range(4)]
        code = FractalCode(blocks=blocks, shape=(8, 8), range_size=4, domain_size=8)
        assert code.compression_factor == pytest.approx(4.0)

    def test_empty_code_ratio_zero(self):
        code = FractalCode([], (0, 0), range_size=4, domain_size=8)
        assert code.compression_ratio == 0.0

    def test_mean_block_error(self):
        blocks = [
            IFSBlock(0, 0, 0, 0, 0.5, 0.0, error=0.1),
            IFSBlock(4, 0, 0, 0, 0.5, 0.0, error=0.3),
        ]
        code = FractalCode(blocks, (8, 4), range_size=4, domain_size=8)
        assert code.mean_block_error() == pytest.approx(0.2)


# ══════════════════════════════════════════════════════════════════════
# BarnsleyCompressor — внутренние методы
# ══════════════════════════════════════════════════════════════════════

class TestBarnsleyInternals:
    def test_downsample_shape(self):
        comp = BarnsleyCompressor(range_size=4)
        block = np.ones((8, 8))
        ds = comp._downsample(block)
        assert ds.shape == (4, 4)

    def test_downsample_constant(self):
        comp = BarnsleyCompressor(range_size=4)
        block = np.full((8, 8), 3.0)
        ds = comp._downsample(block)
        assert np.allclose(ds, 3.0)

    def test_downsample_averaging(self):
        comp = BarnsleyCompressor(range_size=2)
        block = np.array([[1.0, 3.0, 1.0, 3.0],
                          [1.0, 3.0, 1.0, 3.0],
                          [5.0, 7.0, 5.0, 7.0],
                          [5.0, 7.0, 5.0, 7.0]])
        ds = comp._downsample(block)
        assert ds.shape == (2, 2)
        assert ds[0, 0] == pytest.approx(2.0)
        assert ds[1, 0] == pytest.approx(6.0)

    def test_fit_affine_constant_domain(self):
        """Нулевой домен → scale≈0, offset≈mean(target)."""
        comp = BarnsleyCompressor(range_size=4)
        domain = np.zeros((4, 4))
        target = np.full((4, 4), 5.0)
        scale, offset = comp._fit_affine(domain, target)
        assert scale == pytest.approx(0.0)
        assert offset == pytest.approx(5.0)

    def test_fit_affine_identity(self):
        """domain == target → scale≈1 (или ≤0.75 из-за clip), offset≈0."""
        comp = BarnsleyCompressor(range_size=4)
        rng = np.random.default_rng(0)
        d = rng.standard_normal((4, 4))
        scale, offset = comp._fit_affine(d, d)
        approx = scale * d + offset
        # Хотя scale может быть клиппован, аппроксимация должна быть близкой
        assert np.mean((approx - d) ** 2) < 0.5

    def test_fit_affine_linear_relationship(self):
        """target = 2·domain → scale≈0.75 (клиппован), смещение корректируется."""
        comp = BarnsleyCompressor(range_size=4)
        rng = np.random.default_rng(1)
        d = rng.standard_normal((4, 4))
        d = d - d.mean()          # центрировать для чистоты теста
        t = 2.0 * d
        scale, offset = comp._fit_affine(d, t)
        # scale ограничен 0.75 — но направление верное
        assert scale > 0
        assert abs(offset) < 0.1   # оба центрированы → смещение мало

    def test_pad_already_aligned(self):
        comp = BarnsleyCompressor(range_size=4)
        m = np.ones((8, 12))
        padded = comp._pad(m)
        assert padded.shape == (8, 12)

    def test_pad_adds_zeros(self):
        comp = BarnsleyCompressor(range_size=4)
        m = np.ones((7, 9))
        padded = comp._pad(m)
        assert padded.shape[0] % 4 == 0
        assert padded.shape[1] % 4 == 0
        assert padded[7:, :].max() == pytest.approx(0.0)


# ══════════════════════════════════════════════════════════════════════
# BarnsleyCompressor — encode
# ══════════════════════════════════════════════════════════════════════

class TestBarnsleyEncode:
    def test_encode_returns_fractal_code(self):
        comp = BarnsleyCompressor(range_size=4)
        code = comp.encode(_const())
        assert isinstance(code, FractalCode)

    def test_encode_shape_preserved(self):
        comp = BarnsleyCompressor(range_size=4)
        m = _random((12, 16))
        code = comp.encode(m)
        assert code.shape == (12, 16)

    def test_encode_has_blocks(self):
        comp = BarnsleyCompressor(range_size=4)
        code = comp.encode(_const())
        assert len(code.blocks) > 0

    def test_encode_block_count(self):
        """16×16 матрица с range_size=4: 4×4=16 блоков."""
        comp = BarnsleyCompressor(range_size=4)
        code = comp.encode(_const(shape=(16, 16)))
        assert len(code.blocks) == 16

    def test_encode_compression_ratio_positive(self):
        """При range_size=4 сжатие должно быть положительным для 16×16."""
        comp = BarnsleyCompressor(range_size=4)
        code = comp.encode(_const(shape=(16, 16)))
        # n_params=64, original=256 → ratio=0.75
        assert code.compression_ratio > 0

    def test_encode_constant_low_error(self):
        """Постоянная матрица кодируется почти без ошибки."""
        comp = BarnsleyCompressor(range_size=4)
        code = comp.encode(_const(val=3.0))
        assert code.mean_block_error() < 1e-6

    def test_encode_scales_bounded(self):
        """Все scale должны быть в [−0.75, 0.75] (контрактивность)."""
        comp = BarnsleyCompressor(range_size=4)
        code = comp.encode(_random())
        for b in code.blocks:
            assert -0.75 <= b.scale <= 0.75

    def test_encode_random_n_search(self):
        """Случайный поиск (n_search=5) возвращает правильную структуру."""
        comp = BarnsleyCompressor(range_size=4, n_search=5)
        code = comp.encode(_random())
        assert len(code.blocks) > 0


# ══════════════════════════════════════════════════════════════════════
# BarnsleyCompressor — decode
# ══════════════════════════════════════════════════════════════════════

class TestBarnsleyDecode:
    def test_decode_shape(self):
        comp = BarnsleyCompressor(range_size=4)
        code = comp.encode(_const())
        decoded = comp.decode(code)
        assert decoded.shape == (16, 16)

    def test_decode_non_square(self):
        comp = BarnsleyCompressor(range_size=4)
        m = _random((12, 20))
        code = comp.encode(m)
        decoded = comp.decode(code)
        assert decoded.shape == m.shape

    def test_decode_constant_converges(self):
        """Постоянная матрица: decode восстанавливает значение."""
        comp = BarnsleyCompressor(range_size=4)
        m = _const(val=2.5)
        code = comp.encode(m)
        decoded = comp.decode(code, n_iterations=15)
        assert np.allclose(decoded, 2.5, atol=0.01)

    def test_decode_more_iterations_better(self):
        """Больше итераций → ниже ошибка (для нетривиальной матрицы)."""
        comp = BarnsleyCompressor(range_size=4)
        m = _rank1(shape=(16, 16))
        code = comp.encode(m)
        decoded_5  = comp.decode(code, n_iterations=5)
        decoded_20 = comp.decode(code, n_iterations=20)
        mse_5  = float(np.mean((m - decoded_5) ** 2))
        mse_20 = float(np.mean((m - decoded_20) ** 2))
        assert mse_20 <= mse_5 + 1e-8   # монотонное убывание

    def test_decode_initial_irrelevant(self):
        """Различные начальные матрицы сходятся к одному аттрактору."""
        comp = BarnsleyCompressor(range_size=4)
        m = _const(val=1.0)
        code = comp.encode(m)
        decoded_zero = comp.decode(code, n_iterations=20,
                                   initial=np.zeros((16, 16)))
        decoded_ones = comp.decode(code, n_iterations=20,
                                   initial=np.ones((16, 16)))
        assert np.allclose(decoded_zero, decoded_ones, atol=0.1)

    def test_roundtrip_mse_constant(self):
        comp = BarnsleyCompressor(range_size=4)
        mse = comp.roundtrip_mse(_const(val=4.0), n_iterations=15)
        assert mse < 1e-4

    def test_roundtrip_mse_rank1(self):
        """Ранг-1 матрица должна восстанавливаться лучше тривиального предиктора."""
        comp = BarnsleyCompressor(range_size=4)
        m = _rank1(shape=(16, 16))
        mse = comp.roundtrip_mse(m, n_iterations=15)
        variance = float(np.var(m))
        # MSE должно быть меньше дисперсии (лучше, чем предсказание средним)
        assert mse < variance


# ══════════════════════════════════════════════════════════════════════
# SelfSimilarityAnalyzer
# ══════════════════════════════════════════════════════════════════════

class TestSelfSimilarityAnalyzer:
    def test_score_constant_near_zero(self):
        """Постоянная матрица — максимально самоподобна → score ≈ 0."""
        comp = BarnsleyCompressor(range_size=4)
        analyzer = SelfSimilarityAnalyzer(comp)
        score = analyzer.self_similarity_score(_const(val=2.0))
        assert score < 1e-4

    def test_score_random_higher_than_constant(self):
        """Случайная матрица менее самоподобна, чем постоянная."""
        comp = BarnsleyCompressor(range_size=4)
        analyzer = SelfSimilarityAnalyzer(comp)
        score_const  = analyzer.self_similarity_score(_const())
        score_random = analyzer.self_similarity_score(_random())
        assert score_random > score_const

    def test_fractal_dim_range(self):
        """Фрактальная размерность должна быть в [2, 3]."""
        analyzer = SelfSimilarityAnalyzer()
        dim = analyzer.fractal_dimension(_random(shape=(32, 32)))
        assert 2.0 <= dim <= 3.0

    def test_fractal_dim_constant(self):
        """Постоянная матрица — плоская поверхность → размерность ≈ 2."""
        analyzer = SelfSimilarityAnalyzer()
        # Постоянная матрица может вернуть 2.0 (нет вариации)
        dim = analyzer.fractal_dimension(_const(shape=(32, 32)))
        assert dim >= 2.0

    def test_fractal_dim_small_matrix(self):
        """Маленькая матрица → возвращает 2.0 по умолчанию."""
        analyzer = SelfSimilarityAnalyzer()
        dim = analyzer.fractal_dimension(np.array([[1.0, 2.0], [3.0, 4.0]]))
        assert dim == pytest.approx(2.0)

    def test_analyze_keys(self):
        analyzer = SelfSimilarityAnalyzer(BarnsleyCompressor(range_size=4))
        result = analyzer.analyze(_random())
        for key in ("shape", "n_blocks", "n_params", "compression_ratio",
                    "compression_factor", "mse", "psnr_db",
                    "self_similarity", "fractal_dim"):
            assert key in result, f"Ключ '{key}' отсутствует"

    def test_analyze_shape(self):
        analyzer = SelfSimilarityAnalyzer(BarnsleyCompressor(range_size=4))
        m = _random(shape=(16, 20))
        result = analyzer.analyze(m)
        assert result["shape"] == (16, 20)

    def test_analyze_compression_ratio(self):
        """Для 16×16 с range_size=4 коэффициент сжатия > 0."""
        analyzer = SelfSimilarityAnalyzer(BarnsleyCompressor(range_size=4))
        result = analyzer.analyze(_random(shape=(16, 16)))
        assert result["compression_ratio"] > 0

    def test_analyze_constant_high_psnr(self):
        """Постоянная матрица → близкая к идеальной реконструкция → высокий PSNR."""
        analyzer = SelfSimilarityAnalyzer(BarnsleyCompressor(range_size=4))
        result = analyzer.analyze(_const(val=3.0))
        # MSE должна быть очень маленькой
        assert result["mse"] < 0.01


# ══════════════════════════════════════════════════════════════════════
# FractalResolutionBridge
# ══════════════════════════════════════════════════════════════════════

class TestFractalResolutionBridge:
    def test_block_sizes_ordered(self):
        """COARSE имеет самые крупные блоки, EXACT — самые мелкие."""
        bs = FractalResolutionBridge.BLOCK_SIZES
        assert bs[Resolution.COARSE] > bs[Resolution.MEDIUM]
        assert bs[Resolution.MEDIUM] > bs[Resolution.FINE]
        assert bs[Resolution.FINE]   > bs[Resolution.EXACT]

    def test_compressor_for_returns_correct_size(self):
        for res, expected_size in FractalResolutionBridge.BLOCK_SIZES.items():
            comp = FractalResolutionBridge.compressor_for(res)
            assert comp.range_size == expected_size

    def test_suggest_resolution_high_compression(self):
        """Высокое сжатие → COARSE."""
        res = FractalResolutionBridge.suggest_resolution(0.9)
        assert res == Resolution.COARSE

    def test_suggest_resolution_low_compression(self):
        """Минимальное сжатие → EXACT."""
        res = FractalResolutionBridge.suggest_resolution(0.1)
        assert res == Resolution.EXACT

    def test_suggest_resolution_medium(self):
        res = FractalResolutionBridge.suggest_resolution(0.6)
        assert res == Resolution.MEDIUM

    def test_multi_resolution_encode_returns_dict(self):
        m = _random(shape=(32, 32))
        results = FractalResolutionBridge.multi_resolution_encode(
            m, resolutions=[Resolution.COARSE, Resolution.MEDIUM]
        )
        assert "COARSE" in results or "MEDIUM" in results

    def test_multi_resolution_coarser_compresses_more(self):
        """COARSE компрессия даёт больший compression_ratio, чем FINE."""
        m = _random(shape=(32, 32))
        results = FractalResolutionBridge.multi_resolution_encode(m)
        # Берём только те разрешения, которые вошли
        if "COARSE" in results and "FINE" in results:
            assert (results["COARSE"]["compression_ratio"]
                    >= results["FINE"]["compression_ratio"])

    def test_multi_resolution_finer_lower_mse(self):
        """Мелкие блоки дают меньшую ошибку реконструкции."""
        m = _const(val=2.0, shape=(32, 32))
        results = FractalResolutionBridge.multi_resolution_encode(m)
        if "COARSE" in results and "FINE" in results:
            assert (results["FINE"]["mse"]
                    <= results["COARSE"]["mse"] + 1e-6)

    def test_multi_resolution_skips_oversized_blocks(self):
        """Блок больше половины матрицы пропускается."""
        m = _random(shape=(8, 8))   # маленькая матрица
        results = FractalResolutionBridge.multi_resolution_encode(m)
        # COARSE (block=16) не вмещается в 8×8 → должен быть пропущен
        assert "COARSE" not in results

    def test_resolution_maps_to_compression(self):
        """Грубые разрешения дают положительный compression_ratio; EXACT — нейтральный."""
        m = _random(shape=(32, 32))
        results = FractalResolutionBridge.multi_resolution_encode(m)
        for res_name, info in results.items():
            # EXACT (range_size=2): n_params == original_elements → ratio==0; это нормально
            assert info["compression_ratio"] >= 0, (
                f"{res_name}: compression_ratio не должен быть отрицательным"
            )
        # COARSE и MEDIUM всегда дают настоящее сжатие
        for coarse_name in ("COARSE", "MEDIUM"):
            if coarse_name in results:
                assert results[coarse_name]["compression_ratio"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
