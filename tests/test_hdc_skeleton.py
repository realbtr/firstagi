"""Smoke-тесты скелета SPEC (И1-Т1): геном детерминирован, HDC различает,
bind обратим, порядок стадий цикла внимания. Имена — по правилу З-0029."""
import numpy as np

from core.core_types import genome_basis, bind, hamming, D, AttentionStage


def test_genome_deterministic():
    b1, b2 = genome_basis("абв"), genome_basis("абв")
    assert all(np.array_equal(b1[c], b2[c]) for c in "абв"), "геном обязан быть аксиомой"


def test_hdc_separates():
    b = genome_basis("аб")
    assert hamming(b["а"], b["б"]) > D * 0.4, "случайные векторы почти ортогональны"
    assert hamming(b["а"], b["а"]) == 0


def test_bind_reversible():
    b = genome_basis("аб")
    assert hamming(bind(bind(b["а"], b["б"]), b["б"]), b["а"]) == 0


def test_attention_stage_order():
    order = list(AttentionStage)
    assert order.index(AttentionStage.EVALUATION) < order.index(AttentionStage.RETENTION), \
        "оценка прежде удержания (контрольный слой: ведана прежде упаданы)"
