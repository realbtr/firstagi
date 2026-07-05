"""
Шаг 6: CLI REPL для FirstAGI.

Интерактивный режим:
    py -m app.cli

Одноразовый режим:
    py -m app.cli --learn "текст"
    py -m app.cli --status
    py -m app.cli --load session_name --learn "текст" --save session_name
"""

from __future__ import annotations

import argparse
import sys
import os

# Добавляем корень проекта в path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.app import CoreApplication


_HELP = """\
Команды FirstAGI REPL:
  learn <текст>           — обучить систему (можно несколько раз)
  status                  — краткий снапшот системы
  narrative               — полный нарративный отчёт
  attractors              — карта аттракторов
  resource                — уровень ресурса
  base [N]                — топ-N обобщений (по умолчанию 10)
  reset                   — сбросить текущий контекст
  drivers                 — список зарегистрированных драйверов
  driver add text <id>    — добавить TextDriver с указанным id
  teacher tick            — один шаг планировщика учителей
  save <name>             — сохранить сессию
  load <name>             — загрузить сессию
  sessions                — список сохранённых сессий
  help                    — эта справка
  exit / quit             — выход
"""


def _print_learn(result: dict) -> None:
    outcomes = result["outcomes"]
    rate = result["match_rate"]
    print(f"  [{len(outcomes)} токенов]  "
          f"совп={rate:.0%}  "
          f"✓{result['confirmed']}  "
          f"✗{result['refuted']}  "
          f"◎{result['completed']}  "
          f"~{result['explored']}")
    print(f"  {result['narrative']}")


def run_repl(app: CoreApplication) -> None:
    """Основной цикл REPL."""
    print("FirstAGI  |  Шаг 6  |  введите 'help' для списка команд\n")
    while True:
        try:
            line = input("agi> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nВыход.")
            break

        if not line:
            continue

        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        try:
            if cmd in ("exit", "quit", "q"):
                print("Выход.")
                break

            elif cmd == "help":
                print(_HELP)

            elif cmd == "learn":
                if not arg:
                    print("  Использование: learn <текст>")
                    continue
                result = app.learn(arg)
                _print_learn(result)

            elif cmd == "status":
                status = app.status()
                sys_s = status["system"]
                res = status["resource"]
                print(f"  База: {sys_s['base_size']} Gen  "
                      f"признаков: {sys_s['features']}  "
                      f"шагов: {sys_s['steps']}")
                print(f"  Ресурс: {res['level']:.2f} ({res['mode']})  "
                      f"тренд: {res['trend']:+.3f}")
                sched = status["scheduler"]
                print(f"  Планировщик: {'работает' if sched['running'] else 'остановлен'}  "
                      f"тиков: {sched['tick_count']}  "
                      f"воркеров: {len(sched['workers'])}")

            elif cmd == "narrative":
                print(app.voice.state_report())

            elif cmd == "attractors":
                print(app.voice.attractor_report())

            elif cmd == "resource":
                print(f"  {app.voice.resource_report()}")

            elif cmd == "base":
                try:
                    n = int(arg) if arg else 10
                except ValueError:
                    n = 10
                gens = app.system.base.rank()[:n]
                if not gens:
                    print("  База пуста.")
                else:
                    for g in gens:
                        print(f"  {(g.label or g.gen_id[:8]):20s}  "
                              f"sig={g.significance:.2f}  "
                              f"len={g.generalization_level}  "
                              f"✓{g.success_count} ✗{g.stop_count}")

            elif cmd == "reset":
                app.system.reset_context()
                print("  Контекст сброшен.")

            elif cmd == "drivers":
                ids = app.peripherals.driver_ids()
                if ids:
                    print("  Зарегистрированные драйверы:")
                    for did in ids:
                        d = app.peripherals.get(did)
                        print(f"    {did}  ({type(d).__name__})")
                else:
                    print("  Драйверов нет.")

            elif cmd == "driver":
                sub_parts = arg.split(maxsplit=2)
                if len(sub_parts) >= 3 and sub_parts[0] == "add" and sub_parts[1] == "text":
                    app.add_text_driver(sub_parts[2])
                    print(f"  TextDriver '{sub_parts[2]}' добавлен.")
                else:
                    print("  Использование: driver add text <id>")

            elif cmd == "teacher":
                if arg.strip() == "tick":
                    pushed = app.scheduler.tick()
                    print(f"  Планировщик: tick выполнен, запушено={pushed}")
                else:
                    print("  Использование: teacher tick")

            elif cmd == "save":
                if not arg:
                    print("  Использование: save <name>")
                    continue
                path = app.save_session(arg)
                print(f"  Сессия '{arg}' сохранена: {path}")

            elif cmd == "load":
                if not arg:
                    print("  Использование: load <name>")
                    continue
                meta = app.load_session(arg)
                print(f"  Сессия '{arg}' загружена: "
                      f"база={meta.get('base_size', '?')} Gen  "
                      f"шагов={meta.get('steps', '?')}")

            elif cmd == "sessions":
                sessions = app.sessions.list_sessions()
                if not sessions:
                    print("  Нет сохранённых сессий.")
                else:
                    import time as _time
                    for s in sessions:
                        ts = s.get("created_at", 0)
                        dt = _time.strftime("%Y-%m-%d %H:%M", _time.localtime(ts)) if ts else "?"
                        print(f"  {s['name']:20s}  {dt}  "
                              f"база={s.get('base_size','?')}  "
                              f"шагов={s.get('steps','?')}")

            else:
                print(f"  Неизвестная команда: {cmd!r}. Введите 'help'.")

        except Exception as exc:
            print(f"  Ошибка: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FirstAGI CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--learn", metavar="TEXT", help="Обучить и выйти")
    parser.add_argument("--status", action="store_true", help="Показать статус и выйти")
    parser.add_argument("--load", metavar="NAME", help="Загрузить сессию перед стартом")
    parser.add_argument("--save", metavar="NAME", help="Сохранить сессию после --learn")
    parser.add_argument("--sessions-dir", default="sessions", metavar="DIR")
    parser.add_argument("--no-mock-teacher", action="store_true",
                        help="Не добавлять MockTeacherWorker")
    args = parser.parse_args()

    app = CoreApplication(config={
        "sessions_dir": args.sessions_dir,
        "mock_teacher": not args.no_mock_teacher,
    })
    app.startup(autoload=args.load)

    if args.learn:
        result = app.learn(args.learn)
        _print_learn(result)
        if args.save:
            path = app.save_session(args.save)
            print(f"  Сессия сохранена: {path}")
    elif args.status:
        print(app.voice.state_report())
    else:
        # Интерактивный REPL
        run_repl(app)

    app.shutdown()


if __name__ == "__main__":
    main()
