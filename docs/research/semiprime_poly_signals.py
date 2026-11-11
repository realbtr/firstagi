#!/usr/bin/env python3
"""
Структурные сигналы в N, направляющие поиск основания x:
E4 систематический поиск (малая старшая цифра) vs полный скан;
E5 гауссова структура: факторизация через два представления суммой квадратов;
E6 битовая разреженность множителей -> мало переносов в двоичном умножении;
E7 сигнал близости к степени (Ферма / (N/c)^(1/2m)).
Зависимость: sympy.
"""
import math, random
from sympy import symbols, Poly, factor_list, isprime, nextprime, integer_nthroot, gcd as sgcd
t=symbols('t')

def digits_base(N,x):
    d=[]
    while N>0: d.append(N%x); N//=x
    return d
def factor_at(N,x):
    dig=digits_base(N,x)
    if len(dig)-1<2: return []
    P=Poly(list(reversed(dig)),t); _,facs=factor_list(P)
    return [math.gcd(abs(int(f.eval(x))),N) for f,_ in facs if f.degree()>=1]
def works(N,x): return any(1<g<N for g in factor_at(N,x))
def balanced(bits,rng):
    h=bits//2
    p=nextprime(rng.randrange(2**(h-1),2**h)); q=nextprime(rng.randrange(2**(h-1),2**h))
    while q==p: q=nextprime(rng.randrange(2**(h-1),2**h))
    return p*q,p,q

# ---------- E4: систематический поиск по малой старшей цифре ----------
print("="*72)
print("E4. Систематический поиск (x около (N/c)^(1/4), малые c) vs полный скан окна")
print("="*72)
def systematic_bases(N, m=2, Cmax=6, W=2):
    cand=set()
    for c in range(1,Cmax+1):
        x0=integer_nthroot(N//c, 2*m)[0]
        for x in range(max(2,x0-W),x0+W+1): cand.add(x)
    return sorted(cand)
rng=random.Random(7)
full_succ=0; sys_succ=0; full_cost=0; sys_cost=0; both=0; T=300
for _ in range(T):
    N,p,q=balanced(28,rng)
    xhi=integer_nthroot(N,4)[0]; xlo=integer_nthroot(N,6)[0]+1
    fwin=range(xlo,xhi+1)
    f_hit=any(works(N,x) for x in fwin)
    full_cost+=len(fwin)
    cb=systematic_bases(N)
    s_hit=any(works(N,x) for x in cb)
    sys_cost+=len(cb)
    full_succ+=f_hit; sys_succ+=s_hit; both+= (f_hit and s_hit)
print(f"  28-бит, {T} чисел:")
print(f"    полный скан: успех у {full_succ}/{T}, средняя цена {full_cost/T:.0f} оснований/N")
print(f"    систем.поиск (c<=6,W=2): успех у {sys_succ}/{T}, средняя цена {sys_cost/T:.0f} оснований/N")
print(f"    из успехов полного скана систем.поиск поймал {both}/{full_succ}")

# ---------- E5: гауссова структура (два представления суммой квадратов) ----------
print("\n"+"="*72)
print("E5. Гауссова структура: N=pq с p,q=1(mod4) -> два представления a^2+b^2 -> факторизация")
print("="*72)
def cornacchia(p):
    """представление p=a^2+b^2 для простого p=1(mod4)."""
    # найти корень из -1 mod p
    for z in range(2,p):
        r=pow(z,(p-1)//4,p)
        if (r*r)%p==p-1: break
    a,b=p,r
    lim=integer_nthroot(p,2)[0]
    while b>lim: a,b=b,a%b
    return b, integer_nthroot(p-b*b,2)[0]
def gauss_mul(p1,p2):
    (a,b),(c,d)=p1,p2
    return (abs(a*c-b*d), abs(a*d+b*c)), (abs(a*c+b*d), abs(a*d-b*c))
rng=random.Random(3)
for bits in (40,56):
    def prime1mod4(h):
        while True:
            x=nextprime(rng.randrange(2**(h-1),2**h))
            if x%4==1: return x
    p=prime1mod4(bits//2); q=prime1mod4(bits//2)
    while q==p: q=prime1mod4(bits//2)
    N=p*q
    rp=cornacchia(p); rq=cornacchia(q)
    rep1,rep2=gauss_mul(rp,rq)   # два существенно разных представления N=a^2+b^2
    a,b=rep1; c,d=rep2
    assert a*a+b*b==N and c*c+d*d==N
    fac=math.gcd(a*d-b*c,N)
    if fac in (1,N): fac=math.gcd(a*c-b*d,N)
    ok = 1<fac<N and N%fac==0
    print(f"  {bits}-бит N=pq, p,q=1(mod4): N={a}^2+{b}^2={c}^2+{d}^2;  gcd(ad-bc,N)->{fac}  ({'факт.OK' if ok else 'нет'})")
    print(f"    (сигнал виден заранее: N mod 4 = {N%4}; N -- сумма двух квадратов)")

# ---------- E6: битовая разреженность -> мало переносов ----------
print("\n"+"="*72)
print("E6. Битовая разреженность множителей -> мало 'тяжёлых' столбцов в base-2 умножении")
print("="*72)
def heavy_cols(p,q):
    bp=[i for i in range(p.bit_length()) if (p>>i)&1]
    bq=[j for j in range(q.bit_length()) if (q>>j)&1]
    col={}
    for i in bp:
        for j in bq: col[i+j]=col.get(i+j,0)+1
    return sum(1 for v in col.values() if v>=2), max(col.values())
def sparse_prime(h,weight,rng):
    while True:
        bits=[0, h-1]+rng.sample(range(1,h-1),weight-2)
        n=sum(1<<b for b in bits)|1
        if isprime(n): return n
rng=random.Random(11)
for tag,gen in [("разреженные (вес~4)", lambda h: sparse_prime(h,4,rng)),
                ("случайные",           lambda h: nextprime(rng.randrange(2**(h-1),2**h)))]:
    hc=[]; mx=[]; hw=[]
    for _ in range(40):
        p=gen(32); q=gen(32)
        h,m=heavy_cols(p,q); hc.append(h); mx.append(m)
        hw.append(bin(p*q).count("1"))
    print(f"  {tag}: тяжёлых столбцов(>=2) в p*q: среднее {sum(hc)/len(hc):.1f}; "
          f"макс.высота столбца {max(mx)}; вес Хэмминга N в среднем {sum(hw)/len(hw):.1f}")

# ---------- E7: сигнал близости к степени (Ферма) ----------
print("\n"+"="*72)
print("E7. Сигнал близости множителей: шаги метода Ферма (a^2-N=квадрат)")
print("="*72)
def fermat_steps(N, cap=200000):
    a=integer_nthroot(N,2)[0]+1; s=0
    while s<cap:
        b2=a*a-N; b=integer_nthroot(b2,2)[0]
        if b*b==b2: return s, a-b, a+b
        a+=1; s+=1
    return None
rng=random.Random(13)
for tag,make in [("близкие p,q (|p-q| мало)", "close"), ("случайные p,q","rand")]:
    steps=[]
    for _ in range(20):
        h=20
        if make=="close":
            p=nextprime(rng.randrange(2**(h-1),2**h)); q=nextprime(p+rng.randrange(2,200))
        else:
            p=nextprime(rng.randrange(2**(h-1),2**h)); q=nextprime(rng.randrange(2**(h-1),2**h))
        r=fermat_steps(p*q)
        steps.append(r[0] if r else None)
    good=[s for s in steps if s is not None]
    print(f"  {tag}: метод Ферма сошёлся у {len(good)}/20; медиана шагов "
          f"{sorted(good)[len(good)//2] if good else '-'}")
