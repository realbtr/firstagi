"""
training/live_connect.py — Интерактивный клиент к работающей сессии.

Подключается к серверу (default http://localhost:8073) и даёт
интерактивный терминал: наблюдение за моделью + команды.

Запуск:
  py -X utf8 training/live_connect.py
  py -X utf8 training/live_connect.py --port 8073

Команды
───────
  > текст          — скормить модели текст (POST /feed)
  > /ask вопрос    — задать вопрос через гетерархию (POST /ask)
  > /status        — снапшот состояния (GET /stats)
  > /top N         — топ-N Gen (GET /top_gens)
  > /corpus        — список документов
  > /add id текст  — добавить документ (POST /documents)
  > /voices N      — вопросы модели в голосах персонажей
  > /pause         — приостановить цикл
  > /resume        — возобновить цикл
  > /activity N    — последние N событий
  > /quit          — выход
"""
from __future__ import annotations

import argparse
import http.client
import json
import sys
import threading
import time
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

console = Console(highlight=False)

# ══════════════════════════════════════════════════════════════════════════════
# HTTP-клиент
# ══════════════════════════════════════════════════════════════════════════════

class ServerClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 8073) -> None:
        self.base = f"http://{host}:{port}"
        self._host = host
        self._port = port

    def _conn(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection(self._host, self._port, timeout=5)

    def get(self, path: str) -> Optional[Dict]:
        try:
            conn = self._conn()
            conn.request("GET", path)
            resp = conn.getresponse()
            return json.loads(resp.read())
        except Exception as e:
            return {"_error": str(e)}

    def post(self, path: str, body: Dict) -> Optional[Dict]:
        try:
            data = json.dumps(body).encode()
            conn = self._conn()
            conn.request("POST", path, body=data,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            return json.loads(resp.read())
        except Exception as e:
            return {"_error": str(e)}

    def ping(self) -> bool:
        r = self.get("/loop/status")
        return r is not None and "_error" not in r


# ══════════════════════════════════════════════════════════════════════════════
# TUI вывод
# ══════════════════════════════════════════════════════════════════════════════

ICONS = {
    "search_hit":    "🔍",
    "search_miss":   "❌",
    "probe_abort":   "⛔",
    "cold_start":    "🌱",
    "loop_paused":   "⏸",
    "loop_resumed":  "▶",
    "llm_ask":       "🤖",
    "llm_answer":    "💬",
    "llm_skip":      "⏳",
    "user_feed":     "👤",
    "user_ask":      "❓",
    "gen_update":    "📈",
    "error":         "⚠",
}
COLORS = {
    "search_hit":   "green",
    "search_miss":  "red",
    "probe_abort":  "yellow",
    "cold_start":   "cyan",
    "llm_ask":      "magenta",
    "llm_answer":   "blue",
    "llm_skip":     "dim",
    "user_feed":    "bright_white",
    "user_ask":     "bright_yellow",
    "gen_update":   "green",
    "error":        "red",
}


def show_activity(client: ServerClient, n: int = 15) -> None:
    data = client.get(f"/activity?n={n}")
    if "_error" in data:
        console.print(f"[red]Ошибка: {data['_error']}[/red]")
        return
    events = data.get("events", [])
    lines = []
    for ev in events:
        icon  = ICONS.get(ev["kind"], "•")
        color = COLORS.get(ev["kind"], "white")
        lines.append(
            f"[dim]{ev['ts']}[/dim] {icon} [{color}]{ev['msg']}[/{color}]"
        )
    body = "\n".join(lines) if lines else "[dim]Нет событий[/dim]"
    console.print(Panel(body, title="[bold]Активность модели[/bold]",
                        border_style="magenta"))


def show_status(client: ServerClient) -> None:
    data = client.get("/stats")
    if "_error" in data:
        console.print(f"[red]Ошибка: {data['_error']}[/red]")
        return
    exp = data.get("exploration", {})
    ss  = data.get("server_stats", {})

    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    t.add_column("key",   style="dim", no_wrap=True)
    t.add_column("value", style="bright_white")
    t.add_row("Gen-база",    f"{data.get('gen_count',0)} обобщений")
    t.add_row("Циклов",      str(data.get('cycle_count',0)))
    t.add_row("LLM вызовов", f"{data.get('budget_used',0)}/{data.get('budget_limit',0)} "
                              f"(ждать {data.get('rate_wait',0)}с)")
    t.add_row("Визитов",     f"{exp.get('total_visits',0)} ({exp.get('unique_paras',0)} уникальных)")
    t.add_row("Поисков",     f"{ss.get('searches',0)} "
                              f"(hit: {ss.get('hits',0)}, miss: {ss.get('misses',0)})")
    t.add_row("ProbeChain",  f"{ss.get('probe_chains',0)} (abort: {ss.get('probe_aborts',0)})")
    t.add_row("Корпус",      f"{ss.get('corpus_size',0)} документов")
    paused = "[yellow]ПАУЗА[/yellow]" if data.get("paused") else "[green]работает[/green]"
    t.add_row("Статус",      paused)
    console.print(Panel(t, title="[bold]Состояние модели[/bold]", border_style="blue"))


def show_top_gens(client: ServerClient, n: int = 10) -> None:
    data = client.get(f"/top_gens?n={n}")
    if "_error" in data:
        console.print(f"[red]Ошибка: {data['_error']}[/red]")
        return
    gens = data.get("gens", [])
    if not gens:
        console.print("[dim]Gen-база пуста[/dim]")
        return
    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim")
    t.add_column("Метка",  style="cyan")
    t.add_column("Sig",    justify="right")
    t.add_column("Chain",  justify="right")
    t.add_column("✓/✗",    justify="right")
    for g in gens:
        bar = "█" * min(10, int(g["sig"] * 10))
        t.add_row(
            g["label"],
            f"{g['sig']:.3f} [dim]{bar}[/dim]",
            str(g["chain"]),
            f"[green]{g['success']}[/green]/[red]{g['stop']}[/red]",
        )
    console.print(Panel(t, title="[bold]Топ Gen[/bold]", border_style="green"))


OUTCOME_STYLE = {
    "CONFIRMED":  ("✓", "green"),
    "COMPLETED":  ("◉", "bright_green"),
    "REFUTED":    ("✗", "red"),
    "EXPLORING":  ("?", "yellow"),
    "CYCLE_AVOIDED": ("↺", "cyan"),
}


def render_talk(steps: List[Dict], text: str) -> None:
    """Красивый пошаговый вывод InferencePeephole."""
    console.print(Panel(
        f"[dim]Текст:[/dim] [bright_white]{text}[/bright_white]",
        title="[bold cyan]🧠 Обработка модели[/bold cyan]",
        border_style="cyan",
    ))

    for step in steps:
        token   = step["token"]
        outcome = step["outcome"]
        sym, color = OUTCOME_STYLE.get(outcome, ("•", "white"))

        # Заголовок токена
        cascade_tag = " [red bold]⚡КАСКАД[/red bold]" if step["is_cascade"] else ""
        shift_tag   = " [cyan]↺СДВИГ[/cyan]" if step["is_shift"] else ""
        new_gen_tag = f" [green]+Gen[/green]" if step["new_gen"] else ""

        console.print(
            f"  [{color}]{sym}[/{color}] "
            f"[bold bright_white]«{token}»[/bold bright_white]  "
            f"[{color}]{outcome}[/{color}]"
            f"  [dim]act={step['n_active']} comp={step['n_competing']} "
            f"chain={step['max_chain']} {step['elapsed_ms']}ms[/dim]"
            f"{cascade_tag}{shift_tag}{new_gen_tag}"
        )

        # Активные Gen
        for g in step["active"]:
            bar_len = min(8, int(g["sig"] * 10))
            bar     = "█" * bar_len + "░" * (8 - bar_len)
            role    = "[dim](конкур.)[/dim]" if g["competing"] else ""
            sig_color = "green" if g["sig"] >= 0.5 else ("yellow" if g["sig"] > 0 else "dim")

            deep_str = ""
            if g["deep"]:
                deep_str = f"  [dim]знает: {', '.join(g['deep'])}[/dim]"

            console.print(
                f"     └ [{sig_color}]{g['label']:<16}[/{sig_color}] "
                f"sig=[{sig_color}]{g['sig']:.3f}[/{sig_color}] "
                f"[dim]{bar}[/dim] "
                f"ch={g['chain']} prog={g['progress']} {role}"
                f"{deep_str}"
            )

        if not step["active"]:
            console.print(f"     [dim](контекст пуст — исследование)[/dim]")

    console.print()


def show_corpus(client: ServerClient) -> None:
    data = client.get("/documents")
    if "_error" in data:
        console.print(f"[red]Ошибка: {data['_error']}[/red]")
        return
    docs = data.get("docs", [])
    console.print(Panel(
        "\n".join(f"  [cyan]{d}[/cyan]" for d in docs) or "[dim]Пусто[/dim]",
        title="[bold]Корпус[/bold]", border_style="yellow",
    ))


# ══════════════════════════════════════════════════════════════════════════════
# Фоновый поток: автообновление каждые 20 секунд
# ══════════════════════════════════════════════════════════════════════════════

_last_events: List[str] = []
_auto_update_interval = 20.0
_stop_flag = [False]


def _auto_update(client: ServerClient) -> None:
    """Периодически показывает новые события и краткий статус."""
    while not _stop_flag[0]:
        time.sleep(_auto_update_interval)
        if _stop_flag[0]:
            break
        try:
            data = client.get("/activity?n=5")
            events = data.get("events", [])
            new_events = [ev for ev in events
                          if ev["msg"] not in _last_events]
            if new_events:
                console.print()
                console.rule("[dim]── автообновление ──[/dim]")
                for ev in new_events:
                    icon  = ICONS.get(ev["kind"], "•")
                    color = COLORS.get(ev["kind"], "white")
                    console.print(
                        f"  [dim]{ev['ts']}[/dim] {icon} [{color}]{ev['msg']}[/{color}]"
                    )
                    _last_events.append(ev["msg"])
                # Краткий снапшот
                s = client.get("/stats")
                if "_error" not in s:
                    console.print(
                        f"  [dim]Gen: [bright_white]{s['gen_count']}[/bright_white]  "
                        f"loops: {s['cycle_count']}  "
                        f"LLM: {s['budget_used']}/{s['budget_limit']}[/dim]",
                    )
                console.print("  > ", end="")
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# Обработчик команд
# ══════════════════════════════════════════════════════════════════════════════

def handle(line: str, client: ServerClient) -> bool:
    line = line.strip()
    if not line:
        return True

    if line.lower() in ("/quit", "/exit", "/q"):
        return False

    if line.lower() == "/status":
        show_status(client)
        return True

    if line.lower().startswith("/top"):
        parts = line.split()
        n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
        show_top_gens(client, n)
        return True

    if line.lower() == "/corpus":
        show_corpus(client)
        return True

    if line.lower().startswith("/activity"):
        parts = line.split()
        n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 20
        show_activity(client, n)
        return True

    if line.lower() == "/pause":
        r = client.post("/loop/pause", {})
        console.print("[yellow]⏸ Цикл приостановлен[/yellow]" if not r.get("_error")
                      else f"[red]{r['_error']}[/red]")
        return True

    if line.lower() == "/resume":
        r = client.post("/loop/resume", {})
        console.print("[green]▶ Цикл возобновлён[/green]" if not r.get("_error")
                      else f"[red]{r['_error']}[/red]")
        return True

    if line.lower().startswith("/add "):
        rest = line[5:].strip()
        parts = rest.split(None, 1)
        if len(parts) < 2:
            console.print("[red]Использование: /add doc_id текст документа[/red]")
            return True
        doc_id, text = parts[0], parts[1]
        r = client.post("/documents", {"doc_id": doc_id, "content": text,
                                        "domain": "user", "title": doc_id})
        if r.get("_error"):
            console.print(f"[red]{r['_error']}[/red]")
        else:
            console.print(f"[green]✓ Документ «{doc_id}» добавлен "
                          f"(корпус: {r.get('corpus_size','')} doc)[/green]")
        return True

    if line.lower().startswith("/talk "):
        text = line[6:].strip()
        if not text:
            console.print("[red]Введите текст после /talk[/red]")
            return True
        console.print(f"[dim]Отправляю в модель...[/dim]")
        r = client.post("/talk", {"text": text, "learn": True})
        if r.get("_error"):
            console.print(f"[red]{r['_error']}[/red]")
        else:
            render_talk(r.get("steps", []), r.get("text", text))
            console.print(f"[dim]Gen: {r.get('gen_before','')} → {r.get('gen_before','')}+[/dim]")
        return True

    if line.lower().startswith("/ask "):
        question = line[5:].strip()
        if not question:
            console.print("[red]Введите вопрос после /ask[/red]")
            return True
        console.print(f"[magenta]❓ «{question}»[/magenta]")
        r = client.post("/ask", {"question": question})
        if r.get("_error"):
            console.print(f"[red]{r['_error']}[/red]")
        elif r.get("answer") and not str(r["answer"]).startswith("[wait"):
            console.print(f"[blue]💬 {r['answer']}[/blue]  "
                          f"[dim](Gen: {r.get('gen_count','')})[/dim]")
        elif r.get("answer"):
            console.print(f"[yellow]⏳ {r['answer']}[/yellow]")
        else:
            console.print("[dim]Ответа нет[/dim]")
        return True

    if line.lower().startswith("/voices"):
        parts = line.split()
        n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 5
        r = client.get(f"/voices?n={n}")
        voiced = r.get("voiced_questions", [])
        if not voiced:
            console.print("[dim]Персонажей пока нет — модель ещё обучается[/dim]")
        else:
            from rich.panel import Panel
            lines = "\n".join(f"  {q}" for q in voiced)
            console.print(Panel(lines, title="🎭 Голоса персонажей", border_style="magenta"))
        return True

    if line.lower() == "/reflect":
        r = client.get("/reflect")
        if r.get("_error"):
            console.print(f"[red]{r['_error']}[/red]")
            return True
        stats  = r.get("stats", {})
        traces = r.get("best_traces", [])
        from rich.table import Table
        from rich.panel import Panel
        console.print(Panel(
            f"  Всего: [bold]{stats.get('total', 0)}[/bold]  "
            f"Оценено: [bold]{stats.get('scored', 0)}[/bold]  "
            f"Ср. качество: [bold green]{stats.get('avg_quality', 0):.3f}[/bold green]  "
            f"Ср. Δgen: [bold]{stats.get('avg_gen_delta', 0):.1f}[/bold]  "
            f"Лучшая роль: [bold magenta]{stats.get('best_role') or '—'}[/bold magenta]",
            title="🔍 Рефлексия", border_style="cyan",
        ))
        if traces:
            tbl = Table(box=None, header_style="bold dim")
            tbl.add_column("Δgen", justify="right", style="green")
            tbl.add_column("q",    justify="right")
            tbl.add_column("Роль/Персонаж", style="magenta")
            tbl.add_column("Нарративная формулировка")
            for t in traces:
                tbl.add_row(
                    f"{t['gen_delta']:+d}",
                    f"{t['quality']:.2f}",
                    f"{t['role']}/{t['char']}",
                    t["narrative"][:55],
                )
            console.print(tbl)
        return True

    # Обычный текст → скормить модели
    r = client.post("/feed", {"text": line})
    if r.get("_error"):
        console.print(f"[red]{r['_error']}[/red]")
    else:
        console.print(f"[green]✓ +{r.get('tokens_fed',0)} токенов  "
                      f"Gen: {r.get('gen_count','')}[/green]")
    return True


# ══════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Интерактивный клиент FirstAGI Live Session"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8073)
    parser.add_argument("--no-auto", action="store_true",
                        help="Отключить автообновление")
    args = parser.parse_args()

    client = ServerClient(host=args.host, port=args.port)

    # Проверка соединения
    console.print(f"[dim]Подключение к {client.base}...[/dim]")
    if not client.ping():
        console.print(
            f"[red]Не удалось подключиться к {client.base}[/red]\n"
            f"[dim]Запустите сервер:[/dim]\n"
            f"  py -X utf8 -m training.live_session --port {args.port} --no-llm\n"
        )
        sys.exit(1)

    console.print(Panel(
        f"[bold cyan]🧠 FirstAGI — Интерактивное окно[/bold cyan]\n"
        f"Сервер: [link]{client.base}[/link]  "
        f"Docs: [link]{client.base}/docs[/link]\n\n"
        f"[dim]> текст           — скормить модели\n"
        f"/talk текст      — [bold]разговор[/bold]: пошаговый показ обработки\n"
        f"/ask вопрос      — задать вопрос через LLM-учителя\n"
        f"/status          — состояние модели\n"
        f"/top N           — топ-N Gen\n"
        f"/corpus          — список документов\n"
        f"/add id текст    — добавить документ\n"
        f"/voices N        — [bold]голоса персонажей[/bold]: вопросы модели от лица её героев\n"
        f"/reflect         — [bold]рефлексия[/bold]: какие формулировки работали лучше всего\n"
        f"/pause /resume   — управление циклом\n"
        f"/activity N      — последние события\n"
        f"/quit            — выход[/dim]",
        box=box.ROUNDED, border_style="cyan",
    ))
    console.print()

    # Начальный статус
    show_status(client)
    show_activity(client, n=8)

    # Запустить автообновление
    if not args.no_auto:
        t = threading.Thread(target=_auto_update, args=(client,), daemon=True)
        t.start()

    # REPL
    try:
        while True:
            try:
                line = input("  > ")
            except EOFError:
                break
            if not handle(line, client):
                break
    except KeyboardInterrupt:
        pass
    finally:
        _stop_flag[0] = True
        console.print("[dim]Клиент отключён[/dim]")


if __name__ == "__main__":
    main()
