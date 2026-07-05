"""FirstAGI core types — Итерация 1, задача И1-Т2 (начало).
Инварианты: SPEC_FINAL §1-3. Один бинарник: никаких ветвлений по типу экземпляра.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
import numpy as np

D = 1024   # HDC-размерность (SPEC §2)
W_BUDGET = 9  # 7±2, верхняя граница (SPEC §5)

# --- Субстрат адресации: HDC (З-0012) ----------------------------------
def genome_basis(alphabet: str, seed: int = 108) -> dict:
    """Геном: канонические векторы базиса L0. Fixed seed = аксиома рождения (В10)."""
    rng = np.random.default_rng(seed)
    return {ch: rng.integers(0, 2, D, dtype=np.uint8) for ch in alphabet}

def bind(a, b):
    return np.bitwise_xor(a, b)

def bundle(vs):
    return (np.sum(vs, axis=0) * 2 >= len(vs)).astype(np.uint8)

class Resolution(Enum):  # З-0014: префиксное сравнение, модулируется энергией
    COARSE = 256; MEDIUM = 512; FINE = 768; EXACT = 1024

def hamming(a, b, res: Resolution = Resolution.EXACT) -> int:
    n = res.value
    return int(np.count_nonzero(a[:n] != b[:n]))

# --- Ресурсное состояние узла: RS6 (НЕ путать с Curator.phase и энергией
#     Тела — З-0015). Статистика достатка/динамики подтверждений узла. ---
class RS6(Enum):
    LARGE_GROWING = auto(); LARGE_SHRINKING = auto()
    SUFFICIENT_GROWING = auto(); SUFFICIENT_STABLE = auto()
    SCARCE_GROWING = auto(); SCARCE_SHRINKING = auto()

# --- Стадии элементарного цикла внимания (SPEC §1.7) ---------------------
# Имена — инженерные (правило З-0029). Соответствие 12 ниданам — контрольный
# слой: core/attention_trace.py::NIDANA_CORRESPONDENCE (испытание философией,
# не источник имён). Порядок членов enum = порядок стадий цикла.
class AttentionStage(Enum):
    UNCERTAINTY = auto()       # зарегистрирована ненулевая неопределённость
    PROBE_IMPULSE = auto()     # зонд/предложение сформированы до контакта
    SIGNAL_IN = auto()         # сырой сигнал получен от драйвера
    DISTINCTION = auto()       # различию присвоен идентификатор
    CONTEXT_READY = auto()     # активный контекст загружен к сопоставлению
    CONTACT = auto()           # сопоставление сигнала с ожиданиями
    EVALUATION = auto()        # исход оценён; ресурсное состояние обновлено
    DRIVE = auto()             # реакция влечения (гедоника/инициатива)
    RETENTION = auto()         # конкурент удерживает позицию (витальность)
    SUPERPOSITION = auto()     # конкуренция не схлопнулась
    CONTEXT_FIXATION = auto()  # узел вошёл в актуальный контекст
    CONTEXT_DECAY = auto()     # узел покинул актуальный контекст

@dataclass
class BetaCounter:
    success: int = 0
    failure: int = 0
    def merge(self, other):  # коммутативность — инвариант контракта (В6)
        self.success += other.success; self.failure += other.failure

@dataclass
class Handle:
    slot: int
    generation: int

@dataclass
class MeaningToken:
    id: Handle
    driver: str
    level: int
    f_cur: np.ndarray
    f_tgt: np.ndarray
    cmd: list                       # Policy: токены уровня k-1 (решение А2)
    in_stats: dict = field(default_factory=dict)
    out_stats: dict = field(default_factory=dict)
    competitors: set = field(default_factory=set)   # |...| <= W_BUDGET
    resource_state: RS6 = RS6.SCARCE_GROWING
    salience: float = 0.0
    confirmation_density: float = 0.0  # плотность осаждённого подтверждённого
                                       # вклада (контрольный слой: карма)
