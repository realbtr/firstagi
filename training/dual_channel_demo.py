"""
dual_channel_demo.py — Демонстрация Phase 2: двухканальное обучение.

Два голоса, обучение на одних данных, тест на других:

  B_интерпретатор: "Ожидала маша→лес, получила маша→поле"
  B_модель:        «пошла» conf=0.71 → ↔ Ждала «пошла», получила «побежала» [div=0.80]

  Дивергенция = тренировочный сигнал:
    знакомые тексты → avg_div → 0  (система знает что ожидать)
    незнакомые      → avg_div → 1  (каждый токен — сюрприз)

Запуск:
    py -X utf8 training/dual_channel_demo.py
    py -X utf8 training/dual_channel_demo.py --passes 10 --verbose
    py -X utf8 training/dual_channel_demo.py --no-color
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict, List, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.app import CoreApplication
from drivers.model_voice import ChannelDivergence, ModelVoice, VoicePrediction
from drivers.speech_driver import Observation, SpeechDriver
from drivers.text_driver import TextDriver


# ── ANSI цвета ────────────────────────────────────────────────────────────────
_COLOR = True

W  = "\033[0m";  BD = "\033[1m";  DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
RD = "\033[91m"; MG = "\033[95m"; BL = "\033[94m"


def _c(code: str, text: str) -> str:
    return f"{code}{text}\033[0m" if _COLOR else text


def _hdr(title: str) -> None:
    bar = "═" * 70
    print(f"\n{BD}{CY}{bar}{W}")
    print(f"{BD}{CY}  {title}{W}")
    print(f"{BD}{CY}{bar}{W}\n")


# ── Корпус ─────────────────────────────────────────────────────────────────────

TRAIN_TEXTS = [
    "маша пришла в лес встретила медведя поздоровались",
    "волк увидел зайца заяц испугался убежал в лес",
    "маша нашла грибы набрала корзину пошла домой",
    "медведь шёл по лесу встретил лису поговорили",
    "заяц прыгал по полю увидел морковку обрадовался",
    "лиса поймала мышку съела пошла дальше",
    "маша и медведь подружились гуляли по лесу вместе",
    "волк завыл на луну все звери проснулись",
    "заяц и лиса поспорили кто быстрее побежали",
    "медведь нашёл мёд съел весь лёг спать",
]

TEST_FAMILIAR = [
    "маша пришла в лес встретила волка поздоровались",
    "заяц прыгал по лесу увидел лису испугался убежал",
]

TEST_NOVEL = [
    "корабль вышел в море поднялся шторм матросы испугались",
    "программист написал код запустил тесты всё прошло",
]


# ── Один прогон с двумя голосами ──────────────────────────────────────────────

def run_dual(
    system,
    driver: TextDriver,
    speech: SpeechDriver,
    voice: ModelVoice,
    text: str,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Прогнать текст с двумя голосами.
    Возвращает статистику: n_tokens, n_voice_matches, avg_divergence.
    """
    system.reset_context()
    speech.reset_session()
    voice.reset_history()

    rows: List[Tuple[str, str, str, str]] = []  # (токен, B_модель, B_интерпр, Δ)
    prev_label: str = ""

    for tok in driver.produce(text):
        tok_label = getattr(tok, "label", None) or "?"

        # ── B_модель: предсказание ДО токена ──────────────────────────
        pred = voice.predict(system)

        # ── Обработка ─────────────────────────────────────────────────
        result = system.process_token(tok)

        # ── B_модель: запись и дивергенция ПОСЛЕ токена ───────────────
        voice.record_feature(result.matched_feature_id, tok_label)
        if prev_label:
            voice.record_transition(prev_label, tok_label)
        prev_label = tok_label
        div = voice.diverge(pred, tok_label)

        # ── B_интерпретатор ────────────────────────────────────────────
        active = system.engine.context.active_gen_ids()
        obs = speech.observe(
            result, system.base, active,
            voice_prediction = pred.top_word,
            voice_divergence = div.divergence,
        )

        if verbose:
            # B_модель
            bm_str = pred.as_text() if pred.has_prediction else _c(DM, "~")
            # B_интерпр
            if obs:
                COLOR = {"CONFIRMED": GR, "COMPLETED": CY,
                         "REFUTED": RD, "EXPLORING": DM}
                c = COLOR.get(obs.outcome_tag, W)
                bi_str = f"{_c(c, f'[{obs.outcome_tag[:4]}]')} {obs.text[:40]}"
            else:
                bi_str = _c(DM, "[—]")
            # Δ
            delta_str = div.as_text()
            if div.match:
                delta_str = _c(GR, delta_str)
            elif not div.predicted_words:
                delta_str = _c(DM, delta_str)
            else:
                delta_str = _c(RD if div.divergence > 0.6 else AM, delta_str)

            rows.append((tok_label, bm_str, bi_str, delta_str))

    if verbose and rows:
        col_w = max(len(r[0]) for r in rows) + 2
        print(f"  {'Токен':<{col_w}} {'B_модель':<28} {'B_интерпр':<44} Δ")
        print(f"  {'─'*col_w} {'─'*27} {'─'*43} {'─'*30}")
        for tok_lbl, bm, bi, delta in rows:
            print(f"  {_c(BD, f'«{tok_lbl}»'):<{col_w+10}}  {bm:<38}  {bi:<54}  {delta}")
        print()

    vs = voice.stats()
    return {
        "n_tokens":       vs["total"],
        "n_matches":      vs["matches"],
        "match_rate":     vs["match_rate"],
        "avg_divergence": vs["avg_divergence"],
    }


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    global _COLOR, W, BD, DM, GR, CY, AM, RD, MG, BL

    parser = argparse.ArgumentParser(description="Phase 2: Dual-channel demo")
    parser.add_argument("--passes",  type=int, default=5,
                        help="Число проходов обучения")
    parser.add_argument("--verbose", action="store_true",
                        help="Показать таблицу токен/B_модель/B_интерпр на каждом тексте")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args()

    if args.no_color:
        _COLOR = False
        W = BD = DM = GR = CY = AM = RD = MG = BL = ""

    _hdr("Phase 2 — Двухканальное обучение: B_интерпретатор vs B_модель")

    print(f"Корпус:      {len(TRAIN_TEXTS)} обучающих текстов")
    print(f"Проходов:    {args.passes}")
    print(f"Тест знак.:  {len(TEST_FAMILIAR)} текста")
    print(f"Тест новых:  {len(TEST_NOVEL)} текста")
    print()

    # ── Компоненты ────────────────────────────────────────────────────
    app    = CoreApplication(config={"mock_teacher": False, "feature_tolerance": 0.15})
    app.startup()
    system = app.system
    driver = TextDriver("dual_demo")
    speech = SpeechDriver(verbosity=0, lang="ru")  # verbosity=0 — только сюрпризы
    voice  = ModelVoice()

    # ── Фаза 1: Обучение ──────────────────────────────────────────────
    _hdr(f"Фаза 1: Обучение ({args.passes} проходов × {len(TRAIN_TEXTS)} текстов)")
    t0 = time.monotonic()
    for p in range(args.passes):
        for text in TRAIN_TEXTS:
            system.reset_context()
            prev_label: str = ""
            for tok in driver.produce(text):
                result    = system.process_token(tok)
                tok_label = getattr(tok, "label", None) or "?"
                # Обучаем voice одновременно с системой
                voice.record_feature(result.matched_feature_id, tok_label)
                if prev_label:
                    voice.record_transition(prev_label, tok_label)
                prev_label = tok_label

    elapsed = time.monotonic() - t0
    base_sz = len(system.base.all())
    print(f"  База:    {_c(CY, str(base_sz))} Gen")
    print(f"  Словарь B_модель: feature={_c(AM, str(voice.vocab_size))}  "
          f"bigrams={_c(AM, str(voice.bigram_vocab_size))}")
    print(f"  Время:   {elapsed:.1f} с")
    print()

    # ── Фаза 2: Тест на знакомых текстах ─────────────────────────────
    _hdr("Фаза 2а: Знакомые тексты (варианты обучающих)")
    familiar_stats = []
    for text in TEST_FAMILIAR:
        short = (text[:55] + "…") if len(text) > 55 else text
        print(f"  {_c(BL, '►')} «{short}»")
        s = run_dual(system, driver, speech, voice, text, verbose=args.verbose)
        mr  = s["match_rate"]
        div = s["avg_divergence"]
        mr_color  = GR if mr  >= 0.5 else AM
        div_color = GR if div <= 0.3 else (AM if div <= 0.6 else RD)
        print(
            f"    B_модель: mr={_c(mr_color, f'{mr:.2f}')}  "
            f"avg_div={_c(div_color, f'{div:.2f}')}  "
            f"n={s['n_tokens']}"
        )
        familiar_stats.append(s)

    if familiar_stats:
        avg_mr  = sum(s["match_rate"]     for s in familiar_stats) / len(familiar_stats)
        avg_div = sum(s["avg_divergence"] for s in familiar_stats) / len(familiar_stats)
        print()
        print(f"  Итог знакомые:  mr={_c(GR, f'{avg_mr:.2f}')}  "
              f"avg_div={_c(GR if avg_div <= 0.3 else AM, f'{avg_div:.2f}')}")

    # ── Фаза 2: Тест на новых текстах ────────────────────────────────
    _hdr("Фаза 2б: Незнакомые тексты (новая тематика)")
    novel_stats = []
    for text in TEST_NOVEL:
        short = (text[:55] + "…") if len(text) > 55 else text
        print(f"  {_c(RD, '►')} «{short}»")
        s = run_dual(system, driver, speech, voice, text, verbose=args.verbose)
        mr  = s["match_rate"]
        div = s["avg_divergence"]
        mr_color  = GR if mr  >= 0.5 else AM
        div_color = GR if div <= 0.3 else (AM if div <= 0.6 else RD)
        print(
            f"    B_модель: mr={_c(mr_color, f'{mr:.2f}')}  "
            f"avg_div={_c(div_color, f'{div:.2f}')}  "
            f"n={s['n_tokens']}"
        )
        novel_stats.append(s)

    if novel_stats:
        avg_mr  = sum(s["match_rate"]     for s in novel_stats) / len(novel_stats)
        avg_div = sum(s["avg_divergence"] for s in novel_stats) / len(novel_stats)
        print()
        print(f"  Итог незнакомые: mr={_c(AM, f'{avg_mr:.2f}')}  "
              f"avg_div={_c(RD if avg_div > 0.6 else AM, f'{avg_div:.2f}')}")

    # ── Фаза 3: Демонстрация на одном тексте подробно ────────────────
    _hdr("Фаза 3: Детальный прогон (--verbose автоматически включён)")
    demo_text = TEST_FAMILIAR[0]
    print(f"  Текст: «{demo_text}»\n")
    run_dual(system, driver, speech, voice, demo_text, verbose=True)

    # ── Итог ─────────────────────────────────────────────────────────
    _hdr("Итог: Сигнал дивергенции двух голосов")

    all_familiar_div = (
        sum(s["avg_divergence"] for s in familiar_stats) / len(familiar_stats)
        if familiar_stats else 0.0
    )
    all_novel_div = (
        sum(s["avg_divergence"] for s in novel_stats) / len(novel_stats)
        if novel_stats else 0.0
    )
    delta = all_novel_div - all_familiar_div

    print(f"  Знакомые тексты:   avg_div = {_c(GR, f'{all_familiar_div:.2f}')}")
    print(f"  Незнакомые тексты: avg_div = {_c(RD if all_novel_div > 0.5 else AM, f'{all_novel_div:.2f}')}")
    print(f"  Разница Δ:         {_c(AM, f'+{delta:.2f}')}")
    print()
    print(f"  {BD}Вывод:{W}")
    if delta > 0.15:
        print(f"  {GR}✓{W} B_модель хорошо различает знакомые и незнакомые тексты.")
        print(f"    Дивергенция — рабочий тренировочный сигнал Phase 2.")
    else:
        print(f"  {AM}~{W} Различие невелико — увеличьте --passes для лучшего обучения.")

    print()
    print(f"  Словарь B_модель: {voice.vocab_size} признаков")
    print(f"  База Gen:         {len(system.base.all())}")


if __name__ == "__main__":
    main()
