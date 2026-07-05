# ОТЧЁТ S1: АУДИТ-КОНВЕРГЕНЦИЯ СТЕНДА ↔ SPEC_FINAL

### Дата: 2026-07-05 · Основание: З-0020 (карта соответствий), З-0022 (стенд получен)
### Метод: исполнение (1417 тестов — все зелёные), grep-верификация дыр, чтение модулей.

---

## 1. Вердикт

Стенд и SPEC_FINAL **сходятся без переписывания**. Из ~22 сущностей SPEC:
**9 совпадают** (местами стенд опережает спецификацию), **6 совпадают
частично**, **5 дыр** (все — ожидаемые из З-0020, подтверждены кодом),
**1 мягкий конфликт онтологии** (reward учителя), требующий решения
владельца. Ни одного случая «стенд противоречит SPEC неустранимо».

## 2. Карта соответствий (полная)

### 2.1. СОВПАДАЕТ (штатная конвергенция, правок почти не нужно)

| SPEC-сущность | Стенд | Примечание |
|---|---|---|
| §1.5 Три исхода разрешения | CONFIRMED / REFUTED / EXPLORING + **COMPLETED** | Стенд богаче: COMPLETED (успешное завершение цепочки) — кандидат в SPEC после E1 |
| PENDING→COMMIT | `core/provisional.py` ProvisionalBase (track→confirm→promote, min_conf=2, max_age, evict) | Механика идентична; тонкость: provisional Gen виден контексту — зафиксировать как решение, не баг |
| Консолидация на границе сна | `core/dream.py`: DreamTransactionBuffer (вложенные COMMIT/ROLLBACK), sleep_cycle(), SleepDriver реплеит REFUTED | Опережает SPEC: отсюда родилась поправка A-25 (Dreamer←REFUTED) |
| Каскад стоимости Алая/peer/LLM | `drivers/context_broker.py` 3-tier: in-memory → FTS5 → LLM; + QuestionBudget | «Реализован до того, как спроектирован» (З-0020) |
| Энергия Тела [0,1] × 5 режимов | `core/resource.py`: rest/conserve/normal/explore/abundant; модулирует tolerance, контекст, Resolution | Дословное совпадение с З-0015 |
| Уровни разрешения COARSE→EXACT | `core/attractor.py` AttractorEncoder (переменное разрешение, бифуркации) | Первоисточник З-0014 |
| Вытеснение / ёмкость | `core/capacity.py` CapacityBudget(6K) + `core/timescale.py` (LONG/MEDIUM/OPERATIONAL; LONG_TERM не вытесняется) | H18 подтвердила: 14K+ evictions при сохранении MR |
| Teacher Queue (адресация по узлу) | ContextBroker.handle_query по разрыву + TeachingLog.push_query | Async-разрыв закрыт по построению, как требует SPEC §3 |
| Корпус A (сказки) | `training/*_corpus.py`: Джек, Винни-Пух, Муми, песни + базы 90 MB | Готов для E1; «Колобок» добавить тривиально |

### 2.2. ЧАСТИЧНО (гомолог есть, формы не хватает)

| SPEC-сущность | Стенд | Чего не хватает |
|---|---|---|
| §3 MeaningToken {f_cur, f_tgt, cmd} | Generalization {key_id, goal_id, цепочка} | **cmd как переносимой программы внимания** (зона В1) — критично для SantanaDriver; competitors-набора как поля |
| Брокер: EIG-зонд | ExplorationPolicy (novelty×entropy, ProbeChain early-exit), InitiativeEngine, SmartTextDriver EntropyMinimizer | Формального argmin ожидаемой апостериорной энтропии ПО КОНКУРЕНТАМ нет — есть эвристики той же природы |
| Гравитационный фон | TimescaleScheduler LONG_TERM (chain 1–2, «активен всегда», вне вытеснения) | Критерия SUFFICIENT_STABLE ∧ competitors=∅ и чтения по дрейфу нет |
| Куратор (6 фаз гомеостата) | CurriculumAgent (stability decay explore↔consolidate) + SleepScheduler (H15-плато) | Явных 6 фаз и θ-порогов нет (О-2 и так на калибровку И5) |
| Аффект (w1/w2/w3) | HedonicAdapter (novelty=decay^count), VitalityEngine (urgency) | Формулы аффекта из v2 не собраны в один узел (О-2) |
| Тело как слой | app/ (FastAPI, Runner), data/gen_base.py, budget.py, telegram_demo | Слоение не проведено: wall-clock, персистентность, лимиты живут вперемешку с core/ — разнести в S2 без изменения семантики |

### 2.3. ДЫРЫ (подтверждено grep'ом по core/ и drivers/: символов нет)

1. **Нидана-трасса** — ни одного упоминания. → И1-Т4: enum(12) + ассерты
   порядка в CI (скелет уже в корне: `core/core_types.py::Nidana`).
2. **is_genuine_question + initiated_by ∈ {SELF, TEACHER}** — формального
   теста нет. Материал есть: QuestionTrace (двойная запись, gen_delta,
   quality_score), CharacterCuriosityEngine (опоры/незнакомцы/развилки),
   InitiativeEngine (ставки). → собрать формальный предикат поверх.
3. **RS6 узла (ведана)** — только significance и vitality.urgency.
   → вывести 6 состояний из уже собираемой статистики (rich/scarce ×
   growing/shrinking/stable).
4. **HDC-1024 адресация** — нет hamming/hdc. FeatureVector 5Δ — единственный
   носитель тождества. → добавочный индекс (А1: FeatureVector остаётся);
   скелет `bind/bundle/hamming` уже в корне.
5. **SantanaDriver по контракту v4 §2.2** — HeterarchyRouter это прото
   (ModelNode со своим LearningSystem, TeachRequest/Response, peers/mentors,
   redirect), но: нет эмиссии одного токена на COMMIT-обобщение, нет
   FIFO/seq + идемпотентности (Тело), нет handshake «прописи», нет слепоты
   к рою (узлы видят друг друга напрямую).

Дополнительно (не в списке З-0020, найдено аудитом):
6. **Геном L0** — CharTransitionDriver канонизирует кодирование
   (brightness+contrast+hue, tolerance=0.35), но фиксированного seed-генома
   и батареи «прописи» нет. → И1-Т3.
7. **W-бюджет 7±2 как жёсткий предел** — в коде отсутствует; H22 показала,
   что система живёт в 4.5–5.7 сама. → BoundedSet(9) как страховочный
   инвариант, не как регулятор.

### 2.4. КОНФЛИКТ (решение владельца)

**Reward учителя vs §1.2 «нет функции вознаграждения».**
`core/teacher.py`: RewardOrder(reward=50) → `resource.add_reward()`;
`core/initiative.py`: «бонусная награда» за угаданный признак;
`core/hedonic.py`: reward_for() масштабирует по новизне.
Смягчающее обстоятельство: **reward не касается значимости Gen**
(significance = succ/(succ+stop) чиста) — он вливается в РЕСУРС, т.е.
в энергию-физиологию. Варианты:
- **(а) Легализовать через З-0015** (рекомендую): переквалифицировать
  teacher-reward в «энергетическую подкормку Тела» (FEED физиологии);
  переименовать reward→energy_feed, зафиксировать инвариант «энергия
  никогда не пишет в статистику Gen» ассертом в CI.
- (б) Убрать вовсе — риск: сломает калиброванные эксперименты стенда.

**РЕЗОЛЮЦИЯ 2026-07-05 (З-0025):** владелец разрешил конфликт сильнее обоих
вариантов — «внимание = единственная валюта». Энергия растёт от факта
совместного внимания; RewardOrder/TeacherDriver переквалифицируются в
системный драйвер (эволюционный хак, конкурирующий между поколениями);
CI-ассерт «ничто кроме подтверждений не пишет в significance». См. A-28/A-29.

### 2.5. Вне ядра (штатная периферия / витрина — конвергенции не требует)

NarratorDriver, SpeechDriver, ModelVoice (речевая периферия — драйверы по
определению SPEC §4); fractal.py BarnsleyCompressor (исследовательская
линия); DomainDetector, QueryBuilder, InferencePeephole (инструменты);
FastAPI/Runner/Telegram (Тело/витрина); z.ai-приложение (прото-«Класс», S6).

## 3. Бэклог S2 (из аудита, в порядке ценности для E1)

| # | Задача | Оценка |
|---|---|---|
| 1 | Нидана-enum + ассерты порядка в CI поверх пайплайна process_token() | 3–4 ч |
| 2 | Решение по конфликту reward (владелец) → рефактор energy_feed + CI-ассерт | 2–3 ч |
| 3 | cmd-зона: экстракция «программы внимания» из подтверждённой цепочки Gen | 4–6 ч |
| 4 | SantanaDriver по контракту (эмиссия COMMIT-токенов, FIFO/seq, идемпотентность в Теле) | 6–8 ч |
| 5 | is_genuine_question: формальный предикат + initiated_by в QuestionTrace | 3–4 ч |
| 6 | RS6 поверх статистики узла | 2–3 ч |
| 7 | HDC-индекс тождества (добавочный) + геном L0 (seed) + «прописи» | 4–6 ч |
| 8 | Слоение Тела (clock/persistence/limits) — механический перенос | 2–3 ч |

Итого S2 ≈ 26–37 ч работы Claude; точка владельца — решение 2.4 и ревью диффа.

## 4. Ограничение аудита

Читались заголовки/структуры модулей и точечные фрагменты, не каждая строка;
глубина достаточна для карты конвергенции, но построчная сверка формул
(например, точная формула significance по краевым случаям) — по ходу S2.
