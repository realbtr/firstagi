"""
training/story_experiment.py — Эксперимент: «Сказки для модели».

Концепция:
  1. Рассказываем модели сказки (4 домена: Лес, Море, Горы, Город)
  2. В каждой сказке — одни и те же персонажи (Маша, Медведь, Заяц, Лиса, Волк)
  3. Модель строит гетерархию обобщений: персонажные Gen, ситуационные Gen, конкретные Gen
  4. После каждой сказки модель СПРАШИВАЕТ: «Что общего между этой сказкой и предыдущими?»
  5. Ответ идёт в TeachingLog → LLM отвечает → модель учится

Архитектура эксперимента:
  Phase 1: Рассказываем 3 сказки из одного домена (Лес)
           → Модель строит персонажные Gen (маша, медведь, заяц)
           → Модель строит ситуационные Gen (встреча, игра, опасность)
  Phase 2: Рассказываем сказку из ДРУГОГО домена (Море)
           → Модель сталкивается с новыми словами (дельфин, волна, коралл)
           → REFUTED → новые Gen
  Phase 3: Bridge → «Что общего между лесом и морем?»
           → LLM отвечает: «И там и там есть опасности и друзья»
           → Модель учится кросс-доменным связям
  Phase 4: Повторная сказка → MR растёт → гетерархия уплотняется

Запуск:
    py -X utf8 training/story_experiment.py
    py -X utf8 training/story_experiment.py --stories 5
    py -X utf8 training/story_experiment.py --api-key sk-ant-...
"""
from __future__ import annotations

import argparse
import json
import sys
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.app import CoreApplication
from core.attention_loop import AttentionLoop
from core.proposal_loop import ProposalCommandLoop, LoopStatus
from core.active_query_bridge import ActiveQueryBridge
from core.llm_broker import LLMPromptBuilder, LLMResponseParser
from drivers.text_driver import TextDriver
from drivers.speech_driver import SpeechDriver
from drivers.context_broker import ContextBroker, SourceTextRegistry

# ── ANSI ──────────────────────────────────────────────────────────────
W  = "\033[0m";  BD = "\033[1m";  DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
RD = "\033[91m"; MG = "\033[95m"; BL = "\033[94m"

def hdr(t: str) -> None:
    print(f"\n{BD}{CY}{'═'*68}{W}")
    print(f"{BD}{CY}  {t}{W}")
    print(f"{BD}{CY}{'═'*68}{W}\n")

def sub(t: str) -> None:
    print(f"  {AM}── {t} ──{W}")


# ══════════════════════════════════════════════════════════════════════════════
# Сказки
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Story:
    """Одна сказка: текст, домен, тема, персонажи."""
    title: str
    domain: str           # лес, море, горы, город
    theme: str            # встреча, опасность, угощение, игра
    characters: List[str] # кто участвует
    text: str             # полный текст
    moral: str = ""       # «урок» сказки (для LLM)

STORIES: List[Story] = [
    # ── Лес ──────────────────────────────────────────────────────────
    Story(
        title="Как Маша нашла медведя",
        domain="лес",
        theme="встреча",
        characters=["маша", "медведь"],
        text=(
            "маша пошла в лес и встретила медведя медведь испугался "
            "маша сказала не бойся я добрая медведь обрадовался "
            "они пошли вместе по лесу нашли мёд поели мёд вместе "
            "маша поблагодарила медведя и ушла домой довольная"
        ),
        moral="доброта побеждает страх",
    ),
    Story(
        title="Как заяц и лиса играли в прятки",
        domain="лес",
        theme="игра",
        characters=["заяц", "лиса"],
        text=(
            "заяц и лиса играли в прятки в лесу заяц спрятался "
            "лиса искала нашла заяца засмеялись вместе "
            "потом лиса спряталась заяц искал нашёл лису "
            "оба засмеялись и пошли домойszczęлие"
        ),
        moral="дружба — это весело",
    ),
    Story(
        title="Как волк спас зайца",
        domain="лес",
        theme="опасность",
        characters=["волк", "заяц"],
        text=(
            "заяц убегал от охотника волк увидел спрятал зайца "
            "в своей норе охотник прошёл мимо заяц был спасён "
            "заяц поблагодарил волка волк сказал не бойся "
            "я помогаю друзьям заяц и волк стали друзьями"
        ),
        moral="даже враги могут стать друзьями",
    ),

    # ── Море ─────────────────────────────────────────────────────────
    Story(
        title="Как дельфин нашёл ракушку",
        domain="море",
        theme="поиск",
        characters=["дельфин", "краб"],
        text=(
            "дельфин плыл в море и нашёл красивую ракушку "
            "ракушка была на дне у кораллов краб увидел "
            "сказал это моя ракушка дельфин вернул ракушку "
            "краб поблагодарил дельфина и они заплыли朋友"
        ),
        moral="возвращай чужое",
    ),
    Story(
        title="Как медведь купался в море",
        domain="море",
        theme="встреча",
        characters=["медведь", "чайка"],
        text=(
            "медведь пришёл на пляж и увидел море медведь зашёл "
            "в воду и заплыл далеко чайка увидела закричала "
            "медведь вернись обратно медведь заплыл слишком далеко "
            "чайка позвала дельфина дельфин оттащил медведя на берег"
        ),
        moral="слушай друзей",
    ),

    # ── Горы ─────────────────────────────────────────────────────────
    Story(
        title="Как заяц взошёл на гору",
        domain="горы",
        theme="поиск",
        characters=["заяц", "орёл"],
        text=(
            "заяц увидел высокую гору и захотел забраться на вершину "
            "орёл увидел заяца и полетел рядом заяц карабкался "
            "по камням оёл показывал путь наверх заяц дошёл "
            "до вершины и увидел весь мир заяц обрадовался"
        ),
        moral="путь наверх труден, но сто́ит того",
    ),

    # ── Город ────────────────────────────────────────────────────────
    Story(
        title="Как кот нашёл ключ",
        domain="город",
        theme="поиск",
        characters=["кот", "собака"],
        text=(
            "кот потерял ключ от дома кот искал ключ на улице "
            "собака увидела помога искать собака нашла ключ "
            "под скамейкой кот поблагодарил собаку "
            "кот и собака стали лучшими друзьями"
        ),
        moral="помощь друга бесценна",
    ),
]


# ══════════════════════════════════════════════════════════════════════════════
# Mock LLM для демонстрации
# ══════════════════════════════════════════════════════════════════════════════

class StoryMockLLM:
    """Mock LLM, который отвечает на вопросы о связях между сказками."""

    def __init__(self):
        self._call_count = 0
        self._responses = [
            # Первый ответ: обучение новому тексту
            {
                "action": "TEACH",
                "text": "зайчик бежал по лесу и нашёл грибы",
                "amount": 0.0,
                "reason": "Обучение новому паттерну из лесного домена"
            },
            # Второй ответ: награда за прогресс
            {
                "action": "REWARD",
                "text": "",
                "amount": 5.0,
                "reason": "Модель успешно выучила 3 сказки, MR растёт"
            },
        ]

    def complete(self, prompt: str) -> str:
        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        return json.dumps(self._responses[idx], ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════════════
# Основной цикл эксперимента
# ══════════════════════════════════════════════════════════════════════════════

def run_experiment(
    app: CoreApplication,
    broker: ContextBroker,
    stories: List[Story],
    n_passes: int = 2,
    force_idle_after: int = 0,
    verbose: bool = True,
) -> tuple:
    """Запустить эксперимент со сказками. Возвращает (results, bridge)."""

    loop = AttentionLoop(app.system, app.peripherals)
    speech = SpeechDriver(verbosity=0, lang="ru")
    pcl = ProposalCommandLoop(loop, speech=speech, broker=broker)
    bridge = ActiveQueryBridge(app.system, broker)

    results = []

    for story_idx, story in enumerate(stories):
        sub(f"Сказка {story_idx + 1}: «{story.title}» [{story.domain}]")

        # Регистрируем сказку в реестре
        broker.register_source(
            story.text,
            source_id=f"story_{story_idx}",
            origin=f"{story.domain}/{story.theme}",
        )

        story_results = {
            "title": story.title,
            "domain": story.domain,
            "theme": story.theme,
            "characters": story.characters,
            "iterations": [],
        }

        for pass_n in range(1, n_passes + 1):
            app.system.reset_context()
            pcl.load_buffer(story.text)

            # Обрабатываем сказку
            result = pcl.run_cycle(max_steps=200, verbose=False)

            # Принудительный IDLE для Bridge
            forced = False
            if force_idle_after > 0 and result.total_steps >= force_idle_after:
                forced = True
                for did in loop._peripherals.driver_ids():
                    d = loop._peripherals.get(did)
                    if d:
                        d.clear_buffer()
                bridge_result = bridge.on_idle()
            else:
                bridge_result = None

            iter_data = {
                "pass": pass_n,
                "steps": result.total_steps,
                "mr": result.match_rate,
                "gap": result.queries_generated,
                "local": result.queries_resolved_local,
                "base_size": len(app.system.base.all()),
                "forced_idle": forced,
                "bridge_strategy": bridge_result.strategy if bridge_result else None,
            }
            story_results["iterations"].append(iter_data)

            if verbose:
                color = GR if result.match_rate > 0.5 else (AM if result.match_rate > 0.3 else RD)
                print(f"    Pass {pass_n}: steps={result.total_steps}  "
                      f"MR={color}{result.match_rate:.3f}{W}  "
                      f"GAP={result.queries_generated}  "
                      f"Gen={iter_data['base_size']}"
                      f"{'  Bridge→' + bridge_result.strategy if bridge_result and bridge_result.query_generated else ''}")

        results.append(story_results)

    return results, bridge


# ══════════════════════════════════════════════════════════════════════════════
# Анализ гетерархии
# ══════════════════════════════════════════════════════════════════════════════

def analyze_heterarchy(app: CoreApplication, stories: List[Story]) -> None:
    """Показать структуру гетерархии Gen по доменам и темам."""
    hdr("Анализ гетерархии")

    base = app.system.base
    gens = base.all()

    # Группировка по длине цепочки
    by_chain = {}
    for g in gens:
        chain_len = len(g.feature_chain)
        by_chain.setdefault(chain_len, []).append(g)

    print(f"  {BD}Всего Gen:{W} {len(gens)}\n")

    print(f"  {BD}По длине цепочки (уровни обобщения):{W}")
    for chain_len in sorted(by_chain.keys()):
        count = len(by_chain[chain_len])
        bar = "█" * min(count, 50)
        avg_sig = sum(g.significance for g in by_chain[chain_len]) / count
        print(f"    L{chain_len:<3} {count:>4} Gen  "
              f"avg_sig={avg_sig:.2f}  {DM}{bar}{W}")

    # Группировка по доменам (по ключевым словам в label)
    domain_counts = {"лес": 0, "море": 0, "горы": 0, "город": 0, "другое": 0}
    for g in gens:
        label = (g.label or "").lower()
        found = False
        for domain in ["лес", "море", "горы", "город"]:
            if any(w in label for w in [domain, "дерево", "заяц", "медведь",
                                         "дельфин", "краб", "гора", "кот", "собак"]):
                domain_counts[domain] += 1
                found = True
                break
        if not found:
            domain_counts["другое"] += 1

    print(f"\n  {BD}По доменам:{W}")
    for domain, count in sorted(domain_counts.items(), key=lambda x: -x[1]):
        bar = "█" * min(count, 50)
        print(f"    {domain:<8} {count:>4} Gen  {DM}{bar}{W}")

    # Топ Gen по значимости
    print(f"\n  {BD}Топ-10 Gen по значимости:{W}")
    top = sorted(gens, key=lambda g: g.significance, reverse=True)[:10]
    for g in top:
        bar = "█" * int(g.significance * 20)
        chain = len(g.feature_chain)
        print(f"    {g.gen_id[:8]}  sig={AM}{g.significance:.3f}{W}  "
              f"L{chain}  {DM}{bar}{W}  {MG}{g.label}{W}")

    # Кросс-доменные Gen (цепочки ≥ 3 с разными метками)
    cross = [g for g in gens if len(g.feature_chain) >= 3]
    if cross:
        print(f"\n  {BD}Кросс-доменные Gen (chain≥3):{W} {len(cross)}")
        for g in cross[:5]:
            print(f"    {g.gen_id[:8]}  sig={g.significance:.2f}  "
                  f"L{len(g.feature_chain)}  {g.label}")


# ══════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stories", type=int, default=6,
                        help="Количество сказок (макс 7)")
    parser.add_argument("--passes", type=int, default=2,
                        help="Проходов на каждую сказку")
    parser.add_argument("--force-idle", type=int, default=0,
                        help="Принудительный IDLE после N шагов")
    parser.add_argument("--api-key", default="",
                        help="Anthropic API key")
    args = parser.parse_args()

    stories = STORIES[:args.stories]

    # ── 1. Инициализация ─────────────────────────────────────────────
    hdr("Эксперимент: «Сказки для модели»")
    print(f"  Сказок: {len(stories)}")
    print(f"  Проходов на сказку: {args.passes}")
    if args.force_idle > 0:
        print(f"  Force IDLE: каждые {args.force_idle} шагов")

    app = CoreApplication(config={
        "mock_teacher": False,
        "feature_tolerance": 0.15,
    })
    app.startup()

    registry = SourceTextRegistry()
    broker = ContextBroker(
        teaching_log=app.system.teaching_log,
        registry=registry,
    )

    # ── 2. Обучение ──────────────────────────────────────────────────
    hdr("Фаза 1: Рассказываем сказки")
    results, bridge = run_experiment(
        app, broker, stories,
        n_passes=args.passes,
        force_idle_after=args.force_idle,
    )

    # ── 3. Итоговая таблица ──────────────────────────────────────────
    hdr("Фаза 2: Динамика обучения")

    print(f"  {'#':<3} {'Сказка':<35} {'Домен':<8} {'MR':>6} {'Gen':>5}")
    print(f"  {'─'*60}")

    for i, r in enumerate(results):
        last = r["iterations"][-1]
        mr = last["mr"]
        color = GR if mr > 0.5 else (AM if mr > 0.3 else RD)
        print(f"  {i+1:<3} {r['title'][:33]:<35} {r['domain']:<8} "
              f"{color}{mr:>6.3f}{W} {last['base_size']:>5}")

    # График MR
    print(f"\n  {BD}Динамика MR:{W}")
    for i, r in enumerate(results):
        last = r["iterations"][-1]
        mr = last["mr"]
        bar = "█" * int(mr * 40)
        color = GR if mr > 0.5 else (AM if mr > 0.3 else RD)
        print(f"    {i+1}. {r['domain']:<8} {color}{bar} {mr:.3f}{W}")

    # ── 4. Анализ гетерархии ─────────────────────────────────────────
    analyze_heterarchy(app, stories)

    # ── 5. Bridge и LLM ─────────────────────────────────────────────
    if args.force_idle > 0:
        hdr("Фаза 3: Bridge → LLM → Вопросы")
        print(f"  Bridge статистика:")
        for k, v in bridge.stats().items():
            print(f"    {k}: {v}")

        # Показать накопленные запросы
        queries = app.system.teaching_log.peek_queries()
        if queries:
            print(f"\n  {BD}Накопленные запросы ({len(queries)}):{W}")
            for i, q in enumerate(queries[:5], 1):
                tt = getattr(q, "trigger_token", "?")
                qt = getattr(q, "query_text", str(q))
                print(f"  {i}. [{getattr(q, 'trigger_outcome', '?')}] «{tt}»")
                print(f"     {qt[:100]}...")

    # ── 6. Финал ────────────────────────────────────────────────────
    hdr("Итог эксперимента")
    total_gens = len(app.system.base.all())
    print(f"  {BD}Всего Gen:{W} {total_gens}")
    print(f"  {BD}Доменов:{W} {len(set(s.domain for s in stories))}")
    print(f"  {BD}Персонажей:{W} {len(set(c for s in stories for c in s.characters))}")
    print(f"\n  {BD}Ключевые компоненты:{W}")
    print(f"    TextDriver          → текст → признаки")
    print(f"    AttractorEngine     → признаки → Gen → гетерархия")
    print(f"    ProposalCommandLoop → propose → query → process")
    print(f"    ActiveQueryBridge   → IDLE → запрос к LLM")
    print(f"    ContextBroker       → поиск контекста")
    print(f"\n{DM}{'─'*68}{W}")
    print(f"{DM}Эксперимент завершён. Модель учится через сказки.{W}\n")


if __name__ == "__main__":
    main()
