"""
db_inspector.py — интерактивный интерпретатор базы данных GenBaseDB.

Команды CLI:
  py -X utf8 data/db_inspector.py                  # интерактивный REPL
  py -X utf8 data/db_inspector.py --stats           # сводная статистика
  py -X utf8 data/db_inspector.py --top 20          # топ Gen по significance
  py -X utf8 data/db_inspector.py --search маша     # поиск по label
  py -X utf8 data/db_inspector.py --chain 3 6       # Gen с chain 3..6
  py -X utf8 data/db_inspector.py --runs            # список тренировок
  py -X utf8 data/db_inspector.py --experiments     # список экспериментов
  py -X utf8 data/db_inspector.py --populate        # наполнить примерами
  py -X utf8 data/db_inspector.py --repl            # интерактивный режим

REPL-команды (в интерактивном режиме):
  stats           — сводка
  top [n]         — топ N Gen (default 15)
  search <query>  — поиск
  chain <min> <max> — по длине цепочки
  runs [n]        — список прогонов
  exp             — эксперименты
  snap <run_id>   — снапшоты прогона
  help            — эта справка
  quit / exit     — выход
"""
from __future__ import annotations

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.gen_base import GenBaseDB

# ─── ANSI ─────────────────────────────────────────────────────────────────────
W  = "\033[0m";  CY = "\033[96m"; GR = "\033[92m"; AM = "\033[93m"
RD = "\033[91m"; DM = "\033[90m"; BD = "\033[1m"


def _hdr(t: str) -> None:
    print(f"\n{BD}{CY}{'═'*68}{W}")
    print(f"{BD}{CY}  {t}{W}")
    print(f"{BD}{CY}{'═'*68}{W}\n")


# ──────────────────────────────────────────────────────────────────────────────
# Форматирование таблиц
# ──────────────────────────────────────────────────────────────────────────────

def _print_gens(rows, title="Gen"):
    if not rows:
        print(f"  {DM}(пусто){W}")
        return
    _hdr(title)
    print(f"  {'#':>3}  {'gen_id':>10}  {'label':<22}  {'chain':>5}  {'sig':>6}  {'succ':>5}  {'stop':>5}")
    print(f"  {'─'*3}  {'─'*10}  {'─'*22}  {'─'*5}  {'─'*6}  {'─'*5}  {'─'*5}")
    for i, r in enumerate(rows, 1):
        gid   = r.get("gen_id", "")[:10]
        label = (r.get("label") or "—")[:22]
        clen  = r.get("chain_len", 0)
        sig   = r.get("significance", 0)
        succ  = r.get("success", "—")
        stop  = r.get("stop", "—")
        bar   = "█" * int(sig * 10)
        sig_c = GR if sig >= 0.7 else (AM if sig >= 0.3 else DM)
        print(
            f"  {i:>3}  {gid:<10}  {label:<22}  {clen:>5}  "
            f"{sig_c}{sig:>6.3f}{W}  {succ:>5}  {stop:>5}  {DM}{bar}{W}"
        )


def _print_stats(s):
    _hdr("Статистика базы данных")
    print(f"  {'Всего Gen':<30} {BD}{s['total_gens']:,}{W}")
    print(f"  {'avg significance':<30} {BD}{s['avg_sig']:.4f}{W}")
    print(f"  {'max significance':<30} {BD}{s['max_sig']:.4f}{W}")
    print(f"  {'Тренировочных прогонов':<30} {BD}{s['training_runs']}{W}")
    print(f"  {'Экспериментов':<30} {BD}{s['experiments']}{W}")

    if s["exp_status"]:
        print()
        print(f"  {'Статусы экспериментов:'}")
        for status, cnt in s["exp_status"].items():
            c = GR if status == "CONFIRMED" else (RD if status == "REFUTED" else AM)
            print(f"    {c}{status:<14}{W} {cnt}")

    if s["chain_dist"]:
        print()
        print(f"  {'Распределение по chain_len:'}")
        print(f"  {'chain':>6}  {'count':>6}  {'avg_sig':>7}  {'bar'}")
        print(f"  {'─'*6}  {'─'*6}  {'─'*7}  {'─'*30}")
        for d in s["chain_dist"]:
            bar = "█" * min(30, d["count"] // max(1, s["total_gens"] // 30))
            print(
                f"  {d['chain_len']:>6}  {d['count']:>6}  "
                f"{d['avg_sig']:>7.4f}  {DM}{bar}{W}"
            )


def _print_runs(rows):
    if not rows:
        print(f"  {DM}Нет прогонов в базе{W}")
        return
    _hdr("Тренировочные прогоны")
    print(f"  {'run_id':<22}  {'corpus':<20}  {'passes':>6}  {'base':>6}  {'mr':>5}  {'time':>8}")
    print(f"  {'─'*22}  {'─'*20}  {'─'*6}  {'─'*6}  {'─'*5}  {'─'*8}")
    for r in rows:
        t = r.get("duration_s") or 0
        t_str = f"{t:.1f}s" if t < 3600 else f"{t/60:.1f}m"
        mr_c  = GR if (r.get("final_mr") or 0) >= 0.7 else AM
        print(
            f"  {r['run_id']:<22}  {(r['corpus_name'] or '—'):<20}  "
            f"{(r['n_passes'] or 0):>6}  {(r['base_size'] or 0):>6}  "
            f"{mr_c}{(r['final_mr'] or 0):>5.3f}{W}  {t_str:>8}"
        )


def _print_experiments(rows):
    if not rows:
        print(f"  {DM}Нет экспериментов в базе{W}")
        return
    _hdr("Эксперименты")
    print(f"  {'exp_id':<8}  {'status':<12}  {'key_metric':<28}  hypothesis")
    print(f"  {'─'*8}  {'─'*12}  {'─'*28}  {'─'*30}")
    for r in rows:
        status = r.get("status", "?")
        c = GR if status == "CONFIRMED" else (RD if status == "REFUTED" else AM)
        hyp = (r.get("hypothesis") or "")[:50]
        km  = (r.get("key_metric") or "")[:28]
        print(
            f"  {r['exp_id']:<8}  {c}{status:<12}{W}  "
            f"{DM}{km:<28}{W}  {hyp}"
        )


def _print_snapshots(rows, run_id):
    if not rows:
        print(f"  {DM}Нет снапшотов для run_id={run_id}{W}")
        return
    _hdr(f"Снапшоты прогона: {run_id}")
    print(f"  {'pass':>5}  {'base':>7}  {'n_new':>5}  {'avg_sig':>7}  {'mr':>5}  {'step':>10}")
    print(f"  {'─'*5}  {'─'*7}  {'─'*5}  {'─'*7}  {'─'*5}  {'─'*10}")
    for r in rows:
        print(
            f"  {r['pass_num']:>5}  {r['base_size']:>7,}  {r['n_new']:>5}  "
            f"{(r['avg_sig'] or 0):>7.4f}  {(r['mr'] or 0):>5.3f}  {r['step']:>10,}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Наполнение примерами (populate)
# ──────────────────────────────────────────────────────────────────────────────

def _populate(db: GenBaseDB) -> None:
    """Заполнить базу данными из текущего обучения + экспериментов."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from core.app import CoreApplication
    from core.algorithm import StepOutcome
    from drivers.text_driver import TextDriver
    from training.serial_corpus import ALL_SERIAL_TEXTS
    from training.rich_corpus import ALL_TEXTS

    print(f"  {AM}Обучение системы для populate...{W}")
    app = CoreApplication(config={"mock_teacher": False, "feature_tolerance": 0.15})
    app.startup()
    d = TextDriver(driver_id="text")

    corpus = ALL_TEXTS + ALL_SERIAL_TEXTS
    run_id = db.start_run("ALL_TEXTS+SERIAL", notes="populate from db_inspector")

    import time
    t0 = time.perf_counter()
    prev_base = 0

    for pass_i in range(1, 6):
        confirmed = tokens = 0
        for t in corpus:
            for tok in d.produce(t):
                r = app.system.process_token(tok)
                tokens += 1
                if r.outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED):
                    confirmed += 1
            app.system.reset_context()

        curr_base = len(app.system.base.all())
        mr  = confirmed / tokens if tokens else 0.0
        sig = sum(g.significance for g in app.system.base.all()) / max(curr_base, 1)
        db.log_snapshot(run_id, pass_i, curr_base, curr_base - prev_base,
                        sig, 0.0, mr, pass_i * tokens)
        prev_base = curr_base
        print(f"  Pass {pass_i}: base={curr_base}  mr={mr:.3f}")

    elapsed = time.perf_counter() - t0

    # Checkpoint Gen
    print(f"  {AM}Сохранение {len(app.system.base.all())} Gen в базу...{W}")
    n = db.checkpoint(app.system.base)
    db.finish_run(run_id, 5, len(app.system.base.all()), mr, elapsed)
    print(f"  {GR}✓ Сохранено: {n} Gen{W}")

    # Записать эксперименты из known findings
    experiments = [
        ("H1",  "Ритм активаций VitalityRecord",
         "REFUTED",  "avg_interval=2.0 vs expected=13"),
        ("H2",  "WakeUpRestorer ускоряет small base",
         "REFUTED",  "speedup=1.00x"),
        ("H3",  "Сторожок urgency≥2 даёт knock_candidates",
         "CONFIRMED","13 candidates, max_urgency=10.0"),
        ("H4",  "База растёт и выходит в плато",
         "CONFIRMED","plateau_ratio=0.00 (с итер.5)"),
        ("H5",  "Vitality измеряется внутри предложений",
         "REFUTED",  "vitality=0.0 (снимали вне обработки)"),
        ("H6",  "WakeUp ускоряет large base",
         "REFUTED",  "speedup=1.00x на 1589 Gen"),
        ("H7",  "Knock-curriculum восстанавливает mr на 30%+",
         "REFUTED",  "knock=-52.7% (хуже random)"),
        ("H8",  "Перегиб mean_interval при росте базы",
         "REFUTED",  "mi_drop=+911% (растёт, не падает)"),
        ("H9",  "vitality_inside > vitality_after",
         "REFUTED",  "fraction=60% (порог 70%)"),
        ("H10", "urgency коррелирует с REFUTED rate",
         "REFUTED",  "Spearman r=+0.007"),
        ("H11", "CapacityBudget eviction → avg_sig выживших выше",
         "CONFIRMED","sig_lift=+0.09"),
        ("H15", "d(new_gen)/d(pass) plateau — надёжный сигнал",
         "CONFIRMED","plateau на pass=6 (tiny corpus)"),
    ]
    for exp_id, hyp, status, km in experiments:
        db.log_experiment(exp_id, hyp, status, km)
    print(f"  {GR}✓ Записано экспериментов: {len(experiments)}{W}")


# ──────────────────────────────────────────────────────────────────────────────
# REPL
# ──────────────────────────────────────────────────────────────────────────────

HELP_TEXT = """
  Доступные команды:
    stats             — сводная статистика базы
    top [n]           — топ N Gen по significance (default 15)
    search <query>    — поиск Gen по label или цепочке
    chain <min> <max> — Gen с chain_len в диапазоне [min, max]
    runs [n]          — список тренировочных прогонов
    exp               — список экспериментов
    snap <run_id>     — снапшоты конкретного прогона
    help              — эта справка
    quit | exit       — выход
"""


def _repl(db: GenBaseDB) -> None:
    _hdr("GenBaseDB Inspector — REPL")
    print(f"  Файл: {db.path}")
    s = db.stats()
    print(f"  Gen в базе: {BD}{s['total_gens']:,}{W}  "
          f"Прогонов: {BD}{s['training_runs']}{W}  "
          f"Экспериментов: {BD}{s['experiments']}{W}")
    print(f"\n  {DM}Введите команду. Справка: help{W}\n")

    while True:
        try:
            raw = input(f"  {CY}db>{W} ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not raw:
            continue
        parts = raw.split()
        cmd   = parts[0].lower()

        if cmd in ("quit", "exit", "q"):
            break
        elif cmd == "help":
            print(HELP_TEXT)
        elif cmd == "stats":
            _print_stats(db.stats())
        elif cmd == "top":
            n = int(parts[1]) if len(parts) > 1 else 15
            _print_gens(db.top_gens(n), f"Топ-{n} Gen по significance")
        elif cmd == "search":
            if len(parts) < 2:
                print(f"  {AM}Использование: search <query>{W}")
            else:
                q = " ".join(parts[1:])
                _print_gens(db.search(q), f"Результаты поиска: «{q}»")
        elif cmd == "chain":
            mi = int(parts[1]) if len(parts) > 1 else 1
            ma = int(parts[2]) if len(parts) > 2 else 10
            _print_gens(db.chain_filter(mi, ma), f"Gen с chain {mi}..{ma}")
        elif cmd == "runs":
            n = int(parts[1]) if len(parts) > 1 else 10
            _print_runs(db.runs(n))
        elif cmd == "exp":
            _print_experiments(db.experiments())
        elif cmd == "snap":
            if len(parts) < 2:
                print(f"  {AM}Использование: snap <run_id>{W}")
            else:
                _print_snapshots(db.snapshots(parts[1]), parts[1])
        else:
            print(f"  {RD}Неизвестная команда: {cmd}. Введите help.{W}")

    print(f"\n  {DM}До свидания.{W}\n")


# ──────────────────────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="GenBaseDB Inspector — просмотр и анализ базы обобщений"
    )
    parser.add_argument("--stats",       action="store_true", help="Сводная статистика")
    parser.add_argument("--top",         type=int, metavar="N", help="Топ N Gen")
    parser.add_argument("--search",      type=str, metavar="QUERY", help="Поиск Gen")
    parser.add_argument("--chain",       nargs=2, type=int, metavar=("MIN", "MAX"),
                        help="Фильтр по chain_len")
    parser.add_argument("--runs",        action="store_true", help="Список прогонов")
    parser.add_argument("--experiments", action="store_true", help="Список экспериментов")
    parser.add_argument("--populate",    action="store_true",
                        help="Наполнить базу примерами (обучение + эксперименты)")
    parser.add_argument("--repl",        action="store_true",
                        help="Интерактивный режим (default если нет аргументов)")
    parser.add_argument("--db",          type=str, default=None,
                        help="Путь к .db файлу (default: data/gen_base.db)")
    args = parser.parse_args()

    from pathlib import Path
    db_path = Path(args.db) if args.db else None
    db = GenBaseDB(db_path)

    try:
        if args.populate:
            _populate(db)
        elif args.stats:
            _print_stats(db.stats())
        elif args.top is not None:
            _print_gens(db.top_gens(args.top), f"Топ-{args.top} Gen")
        elif args.search:
            _print_gens(db.search(args.search), f"Поиск: «{args.search}»")
        elif args.chain:
            _print_gens(db.chain_filter(*args.chain), f"chain {args.chain[0]}..{args.chain[1]}")
        elif args.runs:
            _print_runs(db.runs())
        elif args.experiments:
            _print_experiments(db.experiments())
        else:
            _repl(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
