#!/usr/bin/env python3
"""
Измерительный протокол к NARRATIVE_COMPACTNESS_2026-11-11.md.

Цель: НЕ доказать показатель sqrt(n)/2, а показать методику его проверки и из
какого режима различимости он вытекает. Концепты моделируются как нормированные
суммы (bundling) k различных примитивов-векторов (модель VSA/голографических
представлений). Два концепта глубины k сливаются, когда их близость превышает
порог. Горизонт различимости L_sat(n) меряется двумя критериями:

  (overlap)  E|A∩B| < 1      -> теоретически L ~ sqrt(n)   [режим 'любой общий примитив = слияние']
  (cosine)   E[cos] < tau     -> теоретически L ~ tau*n     [режим косинусного порога]

Вывод протокола: показатель sqrt(n) соответствует СТРОГОМУ режиму (overlap);
косинусный режим даёт линейный n. Какой режим у реальных представлений -- это и
есть фальсифицирующий эксперимент (здесь -- только синтетический демонстратор).

Зависимость: numpy.
"""
import numpy as np, math

def primitives(n, D, rng):
    V = rng.standard_normal((n, D))
    return V / np.linalg.norm(V, axis=1, keepdims=True)

def concept(V, k, rng):
    idx = rng.choice(V.shape[0], size=k, replace=False)
    s = V[idx].sum(0)
    return s / np.linalg.norm(s), set(idx.tolist())

def measure(n, D=2000, tau=0.5, trials=1500, kmax=22, seed=0):
    rng = np.random.default_rng(seed)
    V = primitives(n, D, rng)
    rows = []
    for k in range(1, min(kmax, n) + 1):
        cos = []; ov = []
        for _ in range(trials):
            a, sa = concept(V, k, rng); b, sb = concept(V, k, rng)
            cos.append(float(a @ b)); ov.append(len(sa & sb))
        rows.append((k, float(np.mean(cos)), float(np.mean(ov))));
    # горизонты
    L_overlap = max([k for k,_,o in rows if o < 1.0] or [0])
    L_cos     = max([k for k,c,_ in rows if c < tau] or [0])
    return rows, L_overlap, L_cos, V, D

if __name__ == "__main__":
    print("Синтетический демонстратор методики (не доказательство закона о когниции).")
    print(f"{'n':>4} {'L_overlap':>9} {'~sqrt(n)':>8} {'sqrt(n)/2':>9} {'L_cos':>6} {'~tau*n':>7} {'шум 1/sqrtD':>11}")
    for n in (30, 50, 70, 100, 140):
        rows, Lo, Lc, V, D = measure(n, seed=n)
        print(f"{n:>4} {Lo:>9} {math.sqrt(n):>8.1f} {math.sqrt(n)/2:>9.2f} "
              f"{Lc:>6} {0.5*n:>7.1f} {1/math.sqrt(D):>11.3f}")
    print()
    print("Кривая средней близости cos(глубина) для n=50 (виден рост ~k/n и шум-пол):")
    rows,_,_,V,D = measure(50, seed=50)
    for k,c,o in rows:
        if k in (1,2,3,4,5,7,10,14,20):
            bar = "#"*int(c*60)
            print(f"  k={k:>2}  cos={c:+.3f}  E|A∩B|={o:.3f}  {bar}")
    print()
    print("Число компактности при L=sqrt(n)/2 (для сверки с ансатцем):")
    for n in (30,50,65,70):
        L=math.sqrt(n)/2
        print(f"  n={n}:  n^(sqrt(n)/2) = 10^{n**L and math.log10(n**L):.2f}")
