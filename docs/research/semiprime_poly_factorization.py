#!/usr/bin/env python3
"""
Воспроизводимый стенд к заметке SEMIPRIME_POLY_FACTORIZATION_2026-11-11.md.

Метод: факторизация полупростого N через представление
    N = P(x) = (a x^2 + b x + c)(d x^2 + e x + f)
             = ad x^4 + (ae+bd) x^3 + (af+be+cd) x^2 + (bf+ce) x + cf,
где x -- основание системы счисления (радикс).

Со стороны решателя (известно только N):
  1. выбрать основание x;
  2. записать N в системе счисления по основанию x: N = sum_i D_i x^i, D_i in [0,x);
  3. образовать "цифровой" многочлен P_x(t) = sum_i D_i t^i;
  4. разложить P_x(t) над Z. Нетривиальный множитель g с 1 < gcd(g(x),N) < N
     даёт делитель N. Поскольку N полупросто, это в точности p или q.

Зависимость: sympy.  Запуск:  python3 -I semiprime_poly_factorization.py
"""
import math, random
from sympy import symbols, Poly, factor_list, isprime, nextprime, integer_nthroot

t = symbols('t')


def digits_base(N, x):
    """Цифры N по основанию x, младшие впереди."""
    d = []
    while N > 0:
        d.append(N % x)
        N //= x
    return d


def factor_at_base(N, x):
    """Факторизует цифровой многочлен N по основанию x над Z.
    Возвращает список (множитель, значение в t=x, gcd со N)."""
    dig = digits_base(N, x)
    if len(dig) - 1 < 2:
        return []
    P = Poly(list(reversed(dig)), t)
    _, facs = factor_list(P)
    out = []
    for fac, _m in facs:
        if fac.degree() >= 1:
            v = int(fac.eval(x))
            out.append((fac.as_expr(), v, math.gcd(abs(v), N)))
    return out


def works_at_base(N, x):
    return any(1 < g < N for _, _, g in factor_at_base(N, x))


def carryfree_bases(p, q):
    """'Чистые' основания: умножение base-x записей p и q идёт без переносов
    (все коэффициенты свёртки < x). Точная характеризация квадратично-
    квадратичного представления, напрямую раскрывающего факторизацию."""
    N = p * q
    xmax = integer_nthroot(N, 4)[0]
    good = []
    for x in range(2, xmax + 1):
        dp, dq = digits_base(p, x), digits_base(q, x)
        conv = [0] * (len(dp) + len(dq) - 1)
        for i, a in enumerate(dp):
            for j, b in enumerate(dq):
                conv[i + j] += a * b
        if all(c < x for c in conv):
            good.append(x)
    return good, xmax


def balanced_semiprime(bits, rng):
    h = bits // 2
    p = nextprime(rng.randrange(2 ** (h - 1), 2 ** h))
    q = nextprime(rng.randrange(2 ** (h - 1), 2 ** h))
    while q == p:
        q = nextprime(rng.randrange(2 ** (h - 1), 2 ** h))
    return p * q, p, q


def demo():
    print("A. 'Чистое' основание (без переносов) для случайных полупростых")
    rng = random.Random(20261111)
    for bits in (24, 28, 32, 36, 40):
        trials, any_good, tot = 40, 0, 0
        for _ in range(trials):
            _, p, q = balanced_semiprime(bits, rng)
            good, xmax = carryfree_bases(p, q)
            tot += len(good)
            any_good += bool(good)
        print(f"   {bits}-бит: окно x<=N^(1/4)~{xmax:>5}; "
              f"есть основание у {any_good:2}/{trials}; "
              f"среднее число/N = {tot/trials:.2f}")

    print("\nB. Со стороны решателя: доля оснований окна, дающих распад")
    rng = random.Random(99)
    for bits in (20, 24, 28, 32, 36):
        trials, totwin, tothit, any_succ = 25, 0, 0, 0
        for _ in range(trials):
            N, _, _ = balanced_semiprime(bits, rng)
            xhi = integer_nthroot(N, 4)[0]
            xlo = max(2, integer_nthroot(N, 6)[0] + 1)
            hit = sum(works_at_base(N, x) for x in range(xlo, xhi + 1))
            totwin += xhi - xlo + 1
            tothit += hit
            any_succ += bool(hit)
        print(f"   {bits}-бит: окно~{totwin//trials:>4} осн.; "
              f"доля удачных={tothit/totwin:.4f}; успех у {any_succ:2}/{trials}")

    print("\nC. Числа специального вида N=(x0^2+c)(x0^2+f), малые c,f")
    rng = random.Random(1)
    for bits in (40, 64, 96, 128):
        while True:
            x0 = rng.randrange(2 ** (bits // 4 - 1), 2 ** (bits // 4))
            base = x0 * x0
            c = next((i for i in range(1, 1000) if isprime(base + i)), None)
            f = next((i for i in range(c + 1, 2000) if isprime(base + i)), None) if c else None
            if c and f:
                p, q = base + c, base + f
                break
        N = p * q
        guess = integer_nthroot(N, 4)[0]
        off = next((dx for dx in (-1, 0, 1) if works_at_base(N, guess + dx)), None)
        print(f"   {bits}-бит: x0={x0}, c={c}, f={f}; "
              f"решатель факторизует при x = round(N^1/4){off:+d}  "
              f"({'OK' if off is not None else 'не найдено'})")


if __name__ == "__main__":
    demo()
