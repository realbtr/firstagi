# FirstAGI — Документ для участников проекта
> BTR R&D 2014–2026 · OpenTalks AI · Актуально: май 2026

---

## 1. Что это такое (за 5 минут)

**Прямое исчисление аттрактора** — архитектура когнитивной системы, которая учится без
предопределённых весов и слоёв. Вместо матриц — направленные переходы (признаки).
Вместо нейронов — обобщения (Gen). Вместо backprop — подтверждение/опровержение предсказаний.

### Ключевые примитивы

| Понятие | Определение |
|---------|------------|
| **Признак** | Направленный переход: Δsize, Δbrightness, Δcontrast, Δcolor, Δfractal_dim. Инвариантен к аффинным преобразованиям. |
| **Gen (Обобщение)** | Цепочка признаков с метрикой значимости = success / (success + stop). |
| **Гетерархия** | Плоская сеть Gen разных уровней (не пирамида). Gen не владеют друг другом, но влияют. |
| **Актуальный контекст** | Активные + конкурирующие Gen + история токенов. |
| **Консолидация** | Общие префиксы подтверждённых Gen → мета-Gen (сжатие опыта). |

### Главный алгоритм (на каждый токен)
```
1. Загрузить контекст (chain=1 Gen — долгосрочная основа)
2. Предсказать следующий признак (от активных Gen)
3. Получить токен:
   - CONFIRMED  → усилить Gen, продолжить цепочку
   - COMPLETED  → Gen завершён, зафиксировать витальность
   - REFUTED    → удивление, создать/уточнить Gen-кандидата
   - EXPLORING  → нет активных Gen, исследовать
4. Обновить контекст → повторить
```

---

## 2. Структура проекта

```
C:\AGIFirst\
│
├── core/          — ядро системы (35 модулей)
│   feature         — признаки (примитив)
│   generalization  — Gen и GeneralizationBase
│   algorithm       — GreedyGeneralizer (НЕ сбрасывать цепочку на COMPLETED!)
│   context         — актуальный контекст
│   attractor       — AttractorEngine (главный цикл step())
│   learning        — LearningSystem (интеграция всего)
│   vitality        — VitalityEngine + VitalityRecord (urgency/vitality)
│   timescale       — TimescaleScheduler (три пула: LONG/MEDIUM/OPERATIONAL)
│   capacity        — CapacityBudget (hard limit Gen + eviction)
│   provisional     — ProvisionalBase (испытательный срок для новых Gen)
│   dream           — SleepScheduler, ReplayEngine, DreamTransactionBuffer
│   proposal_loop   — ProposalCommandLoop (шаг 13, замкнутый цикл)
│   query_builder   — LeakyTemplate, QueryBuilder
│   heterarchy      — ModelNode, HeterarchyRouter
│   exploration     — ExplorationPolicy, ProbeChain
│   domain_detector — DomainDetector (TF-IDF-подобный)
│   llm_node        — LLMTeachNode
│   question_trace  — QuestionTrace + VoiceMemory
│   budget          — QuestionBudget (суточный лимит LLM)
│   dual_driver     — DualDriverMetrics (≡ CONV, ↺ RECALL, ✦ DISC)
│   inference_peephole — InferencePeephole
│   ... + fractal, hedonic, initiative, resource, narrative, session, scheduler
│
├── drivers/       — периферийные драйверы
│   base                — PeripheralDriver (интерфейс + буфер)
│   text_driver          — TextDriver (слова → признаки)
│   sequence_driver      — SequenceDriver (числовые последовательности)
│   memory_driver        — MemoryDriver (воспроизведение токенов)
│   char_transition_driver — символьные переходы (позиционно-инвариантно)
│   speech_driver        — SpeechDriver (канал B, интерпретация пути)
│   smart_text_driver    — SmartTextDriver (энтропийно-минимизирующий)
│   context_broker       — ContextBroker 3-tier (SourceText/FTS5/LLM)
│   narrator_driver      — NarratorDriver (WordGraph, генерация нарратива)
│   model_voice          — ModelVoice (двухканальное обучение, фаза 3)
│
├── app/           — оркестрация
│   server_api      — FastAPI HTTP (/search /probe /shift /documents /loop)
│   text_server     — ActiveTextServer
│   runner          — BackgroundRunner + RunnerConfig + RunnerStats
│   cli, server
│
├── data/          — персистентность
│   gen_base.py     — GenBaseDB (SQLite: gens, training_runs, snapshots, experiments, speech_log)
│   db_inspector.py — REPL CLI: --stats --top --search --chain --runs --experiments
│   gen_base.db     — база данных
│
├── training/      — скрипты обучения и экспериментов
│   vitality_experiments.py   — H1–H5
│   h6_h10_experiments.py     — H6–H10
│   h11_h15_experiments.py    — H11–H15
│   h26_sleep_driver_experiment.py — H26
│   scale_experiment.py       — H16–H25 (50K–1M)
│   winnie_run.py             — эталонный прогон (Винни-Пух)
│   moomin_run.py             — мумий тролли
│   live_session.py / live_connect.py — интерактивные сессии
│   narrator_demo.py, dual_channel_demo.py, active_server_demo.py ...
│
├── curriculum/    — агент-учитель
│   agent.py        — CurriculumAgent (stability decay: explore↔consolidate)
│   debug_session.py — DebugSession (интерактивная отладка)
│
├── tests/         — 1358 тестов
└── telegram_demo/ — Telegram-бот (демо)
```

---

## 3. Инварианты, которые нельзя нарушать

Это не рекомендации — это законы. Нарушение = непредсказуемое поведение.

1. **`step()` сразу сопоставляет** — при загрузке контекста не переходит в EXPLORING.
2. **GreedyGeneralizer: цепочка НЕ сбрасывается на COMPLETED**, только на REFUTED или явный `reset_chain()`.
3. **`process_token()` = 12-шаговый пайплайн**; шаг 6г записывает vitality при CONFIRMED/COMPLETED.
4. **`TextDriver.produce(text)`** — не `.tokenize()`.
5. **Импорты в `curriculum/` и `training/` абсолютные**: `from core.xxx import ...`.
6. **`_load_context_for_feature`** загружает ТОЛЬКО chain=1 Gen. chain≥2 при пустом контексте = «загрязнение» → REFUTED-каскады.
7. **`clear_completed()`** вызывается в начале каждого шага (проактивно).
8. **`startup(autoload)`** принимает `Optional[str]` — имя сессии, не bool.
9. **`CharTransitionDriver`**: кодирует brightness+contrast+color_hue (size=0, color_sat=0, fractal_dim=1). Tolerance=0.35 — минимальный с MR_test=1.0.
10. **`ProvisionalBase.max_age > corpus_cycle_len`**: для Винни (11 текстов × 8 слов = 88) → max_age=200.

---

## 4. Запуск и инструменты

```bash
# Тесты
py -m pytest tests/ -v                  # все 1358 тестов
py -m pytest tests/test_core.py -v      # один модуль

# Инспектор базы Gen
py -X utf8 data/db_inspector.py         # интерактивный REPL
py -X utf8 data/db_inspector.py --stats --top 20

# Эталонные прогоны
py -X utf8 training/winnie_run.py       # Винни-Пух (стабильная база ≤3K Gen)
py -X utf8 training/moomin_run.py       # Мумий тролли

# Эксперименты
py -X utf8 training/vitality_experiments.py         # H1-H5
py -X utf8 training/h6_h10_experiments.py --quick   # H6-H10 быстро
py -X utf8 training/h11_h15_experiments.py          # H11-H15
py -X utf8 training/scale_experiment.py --quick     # H16-H25 (100K, ~3 мин)
py -X utf8 training/h26_sleep_driver_experiment.py --transitions 15000 --replays 40

# HTTP API (FastAPI)
# POST /search /probe /shift /probe_chain /documents
# GET /read /stats
# POST /loop/start /loop/stop

# Интерактивная сессия
py -X utf8 training/live_session.py
```

---

## 5. Что уже реализовано (дорожная карта)

### Шаги 1–12: Ядро системы
| Шаг | Компонент | Ключевое |
|-----|-----------|---------|
| 1 | Feature | Направленный переход, 5 координат, аффинная инвариантность |
| 2 | Generalization + Algorithm | GreedyGeneralizer, значимость = success/(s+stop), гетерархия |
| 3 | Attractor + AttractorEncoder | Переменное разрешение (COARSE→EXACT), бифуркации, TrajectoryRecorder |
| 4 | Resource + Teacher | ResourceState[0,1], 5 режимов, OUTCOME_DELTA, TeachingLog |
| 5 | Fractal | BarnsleyCompressor (PIFS), FractalResolutionBridge |
| 6 | App Layer | PeripheralManager, SessionManager, CoreApplication, FastAPI server |
| 7 | Hedonic + Initiative | HedonicAdapter (novelty=decay^count), InitiativeEngine.propose() |
| 8 | LLM Broker | LLMTeacherWorker, BrokerLoop, rate-limiting |
| 9 | Telegram Demo | DemoConfig, BrainLoop, CommandRouter (/start /status /stats /teach /reset) |
| 10 | Inspector + Curriculum | GeneralizationInspector, PredictiveSimulator, CurriculumAgent (stability decay) |
| 11 | Attention Loop | PeripheralDriver.query(feature), AttentionLoop.step(), DebugSession |
| 12 | Vitality | VitalityRecord (urgency=elapsed/mean_interval), VitalityEngine, WakeUpRestorer |

### Компоненты поверх ядра (шаги 13+)
| Компонент | Файл | Описание |
|-----------|------|---------|
| ProposalCommandLoop | core/proposal_loop.py | Шаг 13; run_cycle()→step→observe→detect_gap→broker→resume; CycleResult.all_queries |
| TimescaleScheduler | core/timescale.py | LONG_TERM(chain 1-2) / MEDIUM(3-4) / OPERATIONAL(5+); classify, tick, eviction_candidates |
| CapacityBudget | core/capacity.py | Hard limit Gen (6K по умолч.); enforce()→eviction_candidates()→base.remove() |
| ProvisionalBase | core/provisional.py | Испытательный срок: track→confirm→tick; min_confirmations=2, max_age=30 |
| Sleep/Dream | core/dream.py | DreamTransactionBuffer, ReplayEngine, CrossDomainDetector, SleepScheduler, sleep_cycle() |
| CharTransitionDriver | drivers/char_transition_driver.py | Символьные переходы; tolerance=0.35; ~8× больше Gen чем TextDriver |
| ContextBroker | drivers/context_broker.py | 3-tier: in-memory / FTS5 / LLM; «поворот внимания» за горизонт |
| QuestionBudget | core/budget.py | Суточный лимит LLM; can_ask(), consume(), reset(), stats() |
| CurriculumIndex | drivers/context_broker.py | FTS5-поиск по корпусу через GenBaseDB.fts_search() |
| SmartTextDriver | drivers/smart_text_driver.py | EntropyMinimizer (5 фаз), ThemeRhemeRouter (CD Firbas), Contextualizer |
| BackgroundRunner | app/runner.py | run(max_transitions)→RunnerStats; доменная ротация; on_sleep/on_log callbacks |
| DualDriver (ModelVoice) | drivers/model_voice.py | Канал A (молчаливый) vs B (речевой); divergence_corrections→sig penalty |
| SpeechDriver | drivers/speech_driver.py | Интерпретация пути внимания ядра в читаемые наблюдения |
| GenBaseDB | data/gen_base.py | SQLite: gens, training_runs, run_snapshots, experiments, speech_log; fts_search() |
| NarratorDriver | drivers/narrator_driver.py | WordGraph (51 узел/256 рёбер), 4 режима генерации (RECALL→DREAM), CharacterVoice |
| QuestionTrace + VoiceMemory | core/question_trace.py | Двойная запись вопросов, quality_score, role_ranking; /reflect endpoint |
| Active Corpus Server | app/text_server.py + app/server_api.py | ActiveTextServer; FastAPI HTTP /search /probe /shift /loop |
| HeterarchyRouter | core/heterarchy.py | ModelNode, TeachRequest/Response; гетерархический роутинг запросов |
| ExplorationPolicy | core/exploration.py | novelty×entropy, ProbeChain с early-exit |
| DomainDetector | core/domain_detector.py | TF-IDF-подобный; build_from_corpus, to_dict/from_dict |
| QueryBuilder | core/query_builder.py | LeakyTemplate, TemplateSlot — шаблоны запросов с «утечками» |
| InferencePeephole | core/inference_peephole.py | Заглядывание в цепочку предсказаний |
| RunnerStats.match_rate | app/runner.py | Реальный MR = (CONFIRMED+COMPLETED)/transitions (не только snap-ключ) |

**Итого: 1358 тестов**

---

## 6. Экспериментальные результаты (все гипотезы)

### H1–H5: Vitality (training/vitality_experiments.py)

| # | Гипотеза | Результат | Инсайт |
|---|---------|-----------|--------|
| H1 | Ритм активаций = 13 | ОПРОВЕРГНУТА (avg=2.0) | VitalityRecord работает с токен-гранулярностью, не предложениями |
| H2 | WakeUp ускоряет обработку | ОПРОВЕРГНУТА (speedup=1.0×) | Нужна большая незнакомая база |
| H3 | Сторожок (knock_candidates) | **ПОДТВЕРЖДЕНА** | 13 кандидатов, max_urgency=10.0 |
| H4 | Рост базы стабилизируется | **ПОДТВЕРЖДЕНА** | plateau_ratio=0.00 с итерации 5 |
| H5 | Vitality ВНУТРИ предложений | ОПРОВЕРГНУТА (60% < 70%) | Направление верное; трансцендентные Gen мешают сигналу |

### H6–H10: Vitality расширенная (training/h6_h10_experiments.py)

| # | Гипотеза | Результат | Ключевой инсайт |
|---|---------|-----------|----------------|
| H6 | WakeUp на большой базе ускоряет | ОПРОВЕРГНУТА (1.0× даже на 1589 Gen) | WakeUp нужен для восстановления контекста после GAP, не для скорости |
| H7 | Knock-curriculum (худшие тексты первыми) | ОПРОВЕРГНУТА (−52.7% хуже random) | **Парадокс умного учителя**: худшие тексты → много REFUTED → шум. Правильно: сначала якорные (лёгкие) |
| H8 | mean_interval падает при перегибе | ОПРОВЕРГНУТА (mi растёт монотонно +911%) | Больше Gen → каждый активируется реже. Сигнал насыщения = d(new_gen)/d(pass) |
| H9 | vitality inside > vitality after для chain≥3 | ЧАСТИЧНО (60% vs порог 70%) | Для chain≥3 направление верное, нужно уточнение на более длинных Gen |
| H10 | urgency коррелирует с REFUTED | ОПРОВЕРГНУТА (r=+0.007) | urgency≠predictor REFUTED; urgency = predictor того, нужен ли WakeUp (context load) |

### H11–H15: CapacityBudget + архитектура (training/h11_h15_experiments.py)

| # | Гипотеза | Результат | Ключевой инсайт |
|---|---------|-----------|----------------|
| H11 | CapacityBudget поднимает avg_sig | ОПРОВЕРГНУТА (lift=−0.0005) | База 1013 << 5^5 «стены»; бюджет не давит |
| H12 | Anchor-first knock лучше random | ОПРОВЕРГНУТА (imp=+0.000) | Малый корпус — curriculum неразличим статистически |
| H13 | chain≥3 Gen домен-специфичны | **ПОДТВЕРЖДЕНА** (fraction_active=100%) | Конкретные Gen активируются только в своём домене |
| H14 | high-urgency → больше шагов без WakeUp | **ПОДТВЕРЖДЕНА** (ratio=1.33) | urgency = context_load predictor подтверждён |
| H15 | d(new_gen)/d(pass) плато + смена домена | **ПОДТВЕРЖДЕНА** | n_new плато на pass=4; mi растёт монотонно (шум). Смена домена восстанавливает рост |

### H16–H26: Масштаб и Sleep (training/scale_experiment.py + h26)

| # | Гипотеза | Результат | Ключевой инсайт |
|---|---------|-----------|----------------|
| H16 | MR transfer ухудшается при смене домена | НЕ ВИДНА (MR=1.0 везде) | TextDriver учит структуру (позиции слов), не семантику. Нужен корпус с разными грамматическими структурами |
| H17 | n_new монотонно убывает | ПЕРЕФОРМУЛИРОВАНА | n_new пилообразен: спад внутри домена, пик при смене — H17' |
| H18 | CapacityBudget держит базу в 6K при MR | **ПОДТВЕРЖДЕНА** | 14K+ evictions, MR сохранена |
| H19 | ThemeRheme улучшает probe | ⏳ нет данных | Нужен ThemeRhemeRouter в dual probe (открытая задача) |
| H20 | CONV растёт с опытом SmartDriver | КОСВЕННО | 1M-прогон покажет |
| H21 | DISC доминирует при смене домена | **ПОДТВЕРЖДЕНА** | пик DISC=0.54 при смене на город |
| H22 | avg_cands = число Миллера в знакомом домене | **ПОДТВЕРЖДЕНА** | avg_cands=4.5–5.7 в знакомом; 2.0–3.4 в незнакомом = «субъективная уверенность» |
| H23 | chain≥3 кросс-доменны | ЧАСТИЧНО | chain≥3=82-89% базы, но это «мемуары предложений»; нужен vocabulary span анализ |
| H24 | MR→сигмоида с доменными паузами | ПЕРЕФОРМУЛИРОВАНА | Не сигмоида, а «зубья пилы»: ↺+✦ пик при каждой смене, CONV растёт между пиками — H24' |
| H25 | ReplayEngine создаёт мета-Gen во сне | **ОПРОВЕРГНУТА** | Replay ожидаемого → всегда CONFIRMED → новых Gen нет. «Скучный сон» |
| H26 | SleepDriver воспроизводит НЕПОНЯТОЕ → инсайт | **ПОДТВЕРЖДЕНА** | REFUTED утром → COMPLETED ночью после обучения на другом домене. Meta-Gen chain=30 с domains=[горы,лес] |

### Итоги по гипотезам
- **Подтверждены**: H3, H4, H13, H14, H15, H18, H21, H22, H26
- **Опровергнуты**: H1, H2, H6, H7, H8, H10, H11, H12, H25
- **Переформулированы/Частично**: H5, H9, H17→H17', H23, H24→H24'
- **Открытые**: H19, H20

---

## 7. Архитектурная модель ёмкости (N^M)

Пространство Gen конечно и структурировано:

```
4^4 =       256  — базовая компетентность
5^5 =     3,125  — нижняя граница рабочей ёмкости
5^6 =    15,625  — типичный эксперт
6^6 =    46,656  — необычная экспертиза
7^7 =   823,543  — редкие единицы
8^8 = 16,777,216 — теоретический предел
```

**Временна́я архитектура (три пула, нырки):**
```
LONG_TERM  (chain=1–2, sig≈1.0)  → фундамент, фильтр восприятия, активен ВСЕГДА
    ↓ активирует
MEDIUM     (chain=3–4, sig=0.7–0.9) → текущая задача
    ↓ активирует
OPERATIONAL (chain=5+, sig=0.4–0.7) → момент-к-моменту, команды драйверам
    ↑ REFUTED поднимается вверх
```

**DualDriver метрики** (профиль знакомости домена):
- `≡ CONV` (convergence) — Gen системы предсказывает → SmartDriver согласен
- `↺ RECALL` — система знает слово, SmartDriver не предсказал
- `✦ DISC` (discovery) — ни система, ни SmartDriver не ожидали; пик при смене домена

**Инсайт H22**: avg_cands ≈ 4.5–5.7 в знакомом домене = число Миллера.

---

## 8. Архитектура сна (SleepDriver / H26)

**ContextQueryLog** = «лог удивлений дня» (REFUTEDEvent в LearningSystem.process_token):
- `feature_id` удивившего токена
- `removed_gen_ids` — нарушенные ожидания
- `token_label` — слово
- `chain_len` — глубина контекста

**SleepDriver.run()** = сенсорная депривация:
1. Захват внимания
2. Replay REFUTED-событий в сохранённом контексте
3. `urgency += 0.5` при повторном REFUTED → перенос на следующую ночь
4. `retain_unresolved(threshold=1.5)` — очищает объяснённые

**Результат H26**: событие «встретил лесу» было REFUTED утром → стало COMPLETED ночью после обучения на горах (где «встретил» тоже встречается). Meta-Gen chain=30 создан во сне.

---

## 9. Активное внимание (стратегическое видение)

**Сейчас (реактивная модель):**
```
Учитель → driver.produce(text) → токены → engine.step() → Gen
```

**Цель (активная модель):**
```
Контекст → InitiativeEngine.propose() → команда драйверу → токен → engine.step() → (цикл)
```

`InitiativeEngine.propose()` уже генерирует `Proposal(gen_id, next_feature_id, confidence)`.
**Не хватает одного звена**: proposal-execution bridge (перевод Proposal → driver.query()).

**Полный цикл (шаг 11 уже реализован частично):**
1. Активные Gen в контексте
2. propose() → ожидаемые признаки (приоритизированный список)
3. feature_id → запрос к драйверу ("покажи X")
4. Драйвер → токен (сенсорный ответ)
5. step(token) → CONFIRMED / REFUTED / EXPLORING
6. Обновлённый контекст → шаг 1

---

## 10. Что ещё нужно сделать / открытые задачи

### Верифицировать/доделать (ближайшая очередь)

| Задача | Приоритет | Где смотреть |
|--------|-----------|-------------|
| **H19**: ThemeRhemeRouter в dual probe → улучшает ли CONV? | Высокий | training/scale_experiment.py |
| **H20**: CONV растёт с опытом SmartDriver на 1M переходов? | Высокий | training/scale_experiment.py (1M, ~2ч) |
| **H23 уточнение**: vocabulary span анализ для кросс-доменности chain≥3 | Средний | новый скрипт analysis/ |
| **H9 уточнение**: vitality inside > after для chain≥3 конкретно | Средний | training/h6_h10_experiments.py |
| **H16 fix**: корпус с разными грамматическими структурами для MR transfer | Средний | training/rich_corpus.py |

### Архитектурные компоненты (задуманы, не реализованы)

| Компонент | Зачем нужен | Статус |
|-----------|------------|--------|
| **DegradationMonitor** | Sig-drop нижних Gen при росте верхних (слепые зоны) | Нет |
| **IntegrationMeter** | d(new_gen)/d(pass) — bandwidth и plateau | Частично в adaptive_counter.py |
| **SaturationDetector** | Сигнал перехода между уровнями N^M | Нет |
| **DepthProfile (для учителя)** | Карта N^M: где сейчас система, куда двигаться | Нет |
| **AttentionPoolManager (7±2)^N** | Многоуровневые пулы вместо плоского max_competing=8 | Нет |
| **TransactionBuffer COMMIT/ROLLBACK** | Локальная копия предполагаемой гетерархии | Нет |
| **SpeechDriver Фаза 2** | Система говорит сама → дивергенция каналов A↔B = тренировочный сигнал | Частично (ModelVoice есть, полный цикл нет) |

### Концептуальные открытые вопросы

1. **Gen labels из raw-слов**: TextDriver работает с feature vectors, не словами. Нужен маппинг feature_chain → word sequence для полноценного канала B.
2. **Query-capable drivers**: `PeripheralDriver.query(feature_id)` работает (шаг 11), но proposal-execution bridge не замкнут полностью.
3. **Парадокс умного учителя (H7)**: anchor-first-knock на малом корпусе неразличим (H12 опровергнута). Нужен большой корпус для проверки.
4. **Blind spots при высоком обобщении**: 16 слепых зон после Матрёшки — трансцендентный Gen с sig=1.0 «успокаивает» систему слишком рано.
5. **CapacityBudget churn**: при capacity=6000 за 1M переходов создаётся и выбрасывается 180–240K Gen. Это «нормально» или сигнал проблемы?

---

## 11. Как присоединиться к проекту

### Минимальный стек
- Python 3.12 (`py`, не `python`)
- pytest: `py -m pytest tests/ -v`
- SQLite (встроен)
- Опционально: `ANTHROPIC_API_KEY` для LLM-компонентов

### Рекомендуемый маршрут изучения

**День 1–2**: Понять примитивы
- Прочитать `core/feature.py` + `core/generalization.py`
- Запустить `py -m pytest tests/test_core.py tests/test_step2.py -v`
- Прочитать `core/algorithm.py` (GreedyGeneralizer) + `core/attractor.py`

**День 3–4**: Понять пайплайн
- `core/learning.py` — LearningSystem.process_token() (12-шаговый пайплайн)
- `training/run.py` — простейший обучающий цикл
- `py -X utf8 training/winnie_run.py` — живой прогон

**День 5–7**: Компоненты памяти и внимания
- `core/vitality.py` + `core/timescale.py` + `core/capacity.py`
- `core/provisional.py` + `core/dream.py`
- `py -X utf8 training/h26_sleep_driver_experiment.py --transitions 15000 --replays 40`

**День 8–10**: Активное внимание и Speech
- `drivers/smart_text_driver.py` + `drivers/narrator_driver.py`
- `drivers/model_voice.py` + `drivers/speech_driver.py`
- `training/live_session.py` — интерактивная сессия

### Ключевые точки для Code Review
При любом изменении проверять:
1. Не нарушен ли ни один из 10 инвариантов (раздел 3)
2. Тесты: `py -m pytest tests/ -v` — все 1358 зелёные
3. `py -X utf8 training/winnie_run.py` — база ≤ 3K Gen после прогона

---

## 12. Метрики производительности

| Метрика | Значение |
|---------|---------|
| Скорость (пустая база) | ~623 tok/s |
| Скорость (база 6K Gen) | ~115 tok/s (спад в 5.4×) |
| 1M переходов с dual | ~2 часа |
| 1M переходов без dual | ~74 мин |
| CharTransitionDriver vs TextDriver | ~8× больше Gen при той же информации |
| Рабочая ёмкость (CapacityBudget) | 6000 Gen (5^5–6^6 диапазон) |
| Churn при 1M (capacity=6K) | 180–240K Gen создано и выброшено |

---

*Документ создан автоматически из памяти проекта и актуального состояния кода. Дата: май 2026.*
