#!/usr/bin/env python3
"""
Расширение к SEMIPRIME_POLY_FACTORIZATION: высшие степени, знаковые (balanced)
цифры, переносы как мера комбинаторной связности столбцов.
Зависимость: sympy.
"""
import math, random
from sympy import symbols, Poly, factor_list, isprime, nextprime, integer_nthroot
t = symbols('t')

def digits_base(N, x):
    d=[]
    while N>0: d.append(N%x); N//=x
    return d

def digits_balanced(N, x):
    """Знаковые цифры в (-x/2, x/2], младшие впереди."""
    d=[]; n=N
    while n>0:
        r=n%x
        if 2*r>x: r-=x
        d.append(r); n=(n-r)//x
    return d

def conv(dp,dq):
    s=[0]*(len(dp)+len(dq)-1)
    for i,a in enumerate(dp):
        for j,b in enumerate(dq): s[i+j]+=a*b
    return s

def overflow_cols(dp,dq,x):
    return sum(1 for c in conv(dp,dq) if c>=x)

def overflow_cols_bal(dp,dq,x):
    h=x//2
    return sum(1 for c in conv(dp,dq) if abs(c)>h)

def factor_at(N,x):
    dig=digits_base(N,x)
    if len(dig)-1<2: return []
    P=Poly(list(reversed(dig)),t); _,facs=factor_list(P)
    out=[]
    for fac,_m in facs:
        if fac.degree()>=1:
            v=int(fac.eval(x)); out.append(math.gcd(abs(v),N))
    return out

def works(N,x): return any(1<g<N for g in factor_at(N,x))

def balanced(bits,rng):
    h=bits//2
    p=nextprime(rng.randrange(2**(h-1),2**h)); q=nextprime(rng.randrange(2**(h-1),2**h))
    while q==p: q=nextprime(rng.randrange(2**(h-1),2**h))
    return p*q,p,q

def special(bits,rng):
    while True:
        x0=rng.randrange(2**(bits//4-1),2**(bits//4)); b=x0*x0
        c=next((i for i in range(1,1000) if isprime(b+i)),None)
        f=next((i for i in range(c+1,2000) if isprime(b+i)),None) if c else None
        if c and f: return (b+c)*(b+f),b+c,b+f,x0

# ---------- E1: кривая числа переносов по основанию ----------
print("="*72)
print("E1. Число переполненных столбцов (переносов) в зависимости от основания")
print("="*72)
rng=random.Random(5)
N,p,q=balanced(32,rng)
xhi=integer_nthroot(N,4)[0]; xlo=integer_nthroot(N,6)[0]+1
mins=min((overflow_cols(digits_base(p,x),digits_base(q,x),x),x) for x in range(xlo,xhi+1))
minb=min((overflow_cols_bal(digits_balanced(p,x),digits_balanced(q,x),x),x) for x in range(xlo,xhi+1))
atmid=overflow_cols(digits_base(p,xhi),digits_base(q,xhi),xhi)
print(f"  Случайное N={N} (p={p},q={q}), окно m=2 x∈[{xlo},{xhi}]")
print(f"    стандартные цифры: минимум переносов по окну = {mins[0]} (при x={mins[1]}); при x=N^1/4 = {atmid}")
print(f"    знаковые цифры:    минимум переносов по окну = {minb[0]} (при x={minb[1]})")
Ns,ps,qs,x0=special(32,rng)
oc=overflow_cols(digits_base(ps,x0),digits_base(qs,x0),x0)
print(f"  Специальное N={Ns} (p={ps},q={qs}), x0={x0}: переносов при x=x0 = {oc}")

# ---------- E2: carry-free частота для m=2 и m=3, станд. и знаковые ----------
print("\n"+"="*72)
print("E2. Частота 'без переносов' для степеней множителей m=2 (квартика) и m=3 (секстика)")
print("    случайные сбалансированные полупростые")
print("="*72)
def cf_freq(bits, m, trials, rng, balanced_digits=False):
    any_std=0; any_solver=0
    for _ in range(trials):
        N,p,q=balanced(bits,rng)
        # окно, где p,q имеют ровно m+1 цифр: x^m<=p<x^(m+1)
        xhi=integer_nthroot(N,2*m)[0]
        xlo=integer_nthroot(N,2*(m+1))[0]+1
        if xlo<2: xlo=2
        found_cf=False; found_s=False
        for x in range(xlo,xhi+1):
            if balanced_digits:
                dp,dq=digits_balanced(p,x),digits_balanced(q,x)
                if len(dp)-1==m and len(dq)-1==m and overflow_cols_bal(dp,dq,x)==0: found_cf=True
            else:
                dp,dq=digits_base(p,x),digits_base(q,x)
                if len(dp)-1==m and len(dq)-1==m and overflow_cols(dp,dq,x)==0: found_cf=True
            if not found_s and works(N,x): found_s=True
            if found_cf and found_s: break
        any_std+=found_cf; any_solver+=found_s
    return any_std,any_solver,trials
for bits in (24,28):
    for m in (2,3):
        r=random.Random(1000+bits+m)
        a_std,a_solv,tr=cf_freq(bits,m,30,r,balanced_digits=False)
        r=random.Random(1000+bits+m)
        a_bal,_,_=cf_freq(bits,m,30,r,balanced_digits=True)
        print(f"  {bits}-бит, m={m}: есть carry-free основание (станд) {a_std}/{tr}; "
              f"(знаковые) {a_bal}/{tr}; есть распад у решателя {a_solv}/{tr}")

# ---------- E3: концентрация рабочих оснований по величине старшей цифры ----------
print("\n"+"="*72)
print("E3. Где лежат рабочие основания: величина старшей цифры N (=a_m*b_m) там")
print("="*72)
rng=random.Random(7)
samples=[]
for _ in range(400):
    N,p,q=balanced(28,rng)
    xhi=integer_nthroot(N,4)[0]; xlo=integer_nthroot(N,6)[0]+1
    for x in range(xlo,xhi+1):
        if works(N,x):
            lead=digits_base(N,x)[-1]  # старшая цифра
            samples.append((lead, x, xhi))
from collections import Counter
cnt=Counter(l for l,_,_ in samples)
print(f"  Найдено рабочих оснований (28-бит, 400 чисел): {len(samples)}")
print(f"  Распределение по старшей цифре c=a_m*b_m: {dict(sorted(cnt.items())[:8])}")
near=sum(1 for l,x,xh in samples if x>=0.84*xh)  # близко к верху окна (c=1 диапазон)
print(f"  Доля рабочих оснований в верхних 16% окна (старшая цифра=1): {near}/{len(samples)}")
