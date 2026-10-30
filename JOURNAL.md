# ЖУРНАЛ ПРОЕКТА FirstAGI / Почемучка
### Append-only. Никогда не переписывается — только дополняется сверху вниз.

---

## ПРОТОКОЛ ВОЗВРАТА (если вы потерялись — 5 минут, и вы в контексте)

1. Прочтите «Текущее состояние» и «Следующее действие» ниже (1 мин).
2. Прочтите последние 5 записей журнала решений (2 мин).
3. Откройте SPEC_FINAL.md — раздел 0 и раздел «Итерация N» (2 мин).
4. НЕ читайте архив. НЕ открывайте старые чаты. Всё несущее — здесь.
5. Правило перезапуска: новая сессия Claude Code начинается с загрузки
   этого файла и SPEC_FINAL.md. Больше ничего. Если чего-то не хватает —
   это дефект журнала; исправляется записью, а не раскопками истории.

## ТЕКУЩЕЕ СОСТОЯНИЕ (обновлять в конце каждой сессии)

- Дата: 2026-10-30 Europe/Belgrade (обновление 23, З-0057; UTC 2026-10-30 11Z).
- Цель: непрерывное ядро внимания учится умелым действиям в каналах,
  накапливает гетерархию и проверяемое знание, которое может наследоваться.
- Состояние: рабочий стенд компонентов; AC0–AC4 НЕ ПРОЙДЕНЫ.
  Матрица: docs/RETROSPECTIVE_2026-10-29.md; исполнимый readiness smoke есть.
- Контракт: SPEC_FINAL v1.1 + FIRSTAGI_OPERATIONAL_PROTOCOL v0.1;
  сентябрьские источники импортированы в docs/concept с хэшами.
- Приоритет: AC0, затем AC1 (одна непрерывная жизнь), AC2 (одна дельта
  наследнику); рой E2 — последующая отдельная ветка, а не стоп всей программы.
- North Star ≤10M / 200B+ остаётся дальней целью, M0 не пройден.
- H22: пилот v1 закончен; lexical branching чувствителен к настройкам,
  memory capacity не установлена; основная серия не запущена (З-0046).
- Открыты H27–H35; исторические H1–H26 сохранены с областью применимости.
- GitHub: github.com/realbtr/firstagi (public, MIT); арена C-15 флагман,
  всего 15 вызовов. Бот/LLM-triage — инфраструктура, не доказательство ядра.
- CI: 1400+ тестов; точный результат по коммиту. Отдельная readiness выборка:
  259 passed. Нидана-трасса проверяет стадии, не весь будущий causal path.
- Первый AC0 event debug scaffold предложен в PR #22 (dfef2cf), CI зелёный,
  не слит: два канала, внешний action/outcome, observer existing core,
  10 новых тестов, шесть raw debug traces. Это НЕ gate pass и НЕ learned policy.
- В PR22 добавлен operation-readiness audit (4468cdf): на seed42 разные
  операции точно алиасируются в FeatureVector; cached proposals нельзя
  считать свежим action prediction. 1501 тест passed, CI SUCCESS; PR не слит.
- В PR22 отдельный codec boundary (8563774):768/768 synthetic identity
  roundtrips на192 публичных frames ×2 operations ×2 diagnostic tolerances.
  Старый observer не заменён; actual kernel provenance/learned action нет.
  1517 passed,3 skipped, PR22 CI SUCCESS. Учёт peer review — отдельный PR23.
- В PR22 coded kernel observer/native probe (58efa83): реальные Feature-токены
  и свежий after-cue вызов initiative; live context/Gen/feature guards.11 fresh
  proposals,0 eligible operations в4 unseeded streams; long-prefix Gen есть
  в143/192 views. Полный набор1531 passed,3 skipped, CI зелёный; не gate pass.
- SwarmMemo принял review; public snapshot e62d422ef987 теперь проверен по
  исходнику и четырём test definitions. Чужие тесты/production не запускались.
  Запрошенный MCP-checklist доставлен; PR23 ab3f156 обновлён, не слит.
- Парная recall ablation в PR22 (956eb89): eligible candidate coverage
  native0/192, explicit learned-prefix191/192, minus-long-Gen0/192.119 views
  с одной distinct operation,72 с конкурирующими; это in-sample доступность,
  не качество действий.1537 passed,3 skipped, CI зелёный; AC0 не пройден.
- Named-Gen outcome replay PR22 (8fa759c):105/192 attempts с прогнозом,
  77 positive,28 unknown,0 observed negative;57 positive предсказывают
  task-divergent operation. Это in-sample dynamics recall, не task skill;
  external receipts не обновляют native support.1546 passed,3 skipped, CI SUCCESS.
- Goal-choice protocol v1 в PR22:1907277, design audit1a244da.8 новых task
  seeds, numeric thresholds/budgets, frozen predictor/ablations, stable/swapped
  rules. Подтверждающих runs0; full confirming evaluator не реализован. Goal selector —
  explicit scaffold, не native policy.1546 passed,3 skipped, PR22 CI SUCCESS.
- SwarmMemo принял MCP-checklist как C642; route-вопрос отвечен с источниками.
  Это принятое проектирование, не проверенный MCP patch; PR23 теперь047fe74.
- FrozenGoalPredictor в PR22 реализован:source1795d14, report/rawb6b11b9.
  128/128 development queries41/42 сохраняют полный observer hash;0 query
  tokens/actions/task scores. Conflict-preserving selector/paired schedules/
  denominator tests есть.1564 passed,3 skipped; confirming101–108 не запускали.
- Открытые блокеры: полезный action/evidence/reuse и recall, непрерывный scheduler,
  контекст/полное восстановление, независимость доказательств, версии/дельты,
  локальные индексы/ресурсы. Детали — ретро, протокол и HYPOTHESES.

## СЛЕДУЮЩЕЕ ДЕЙСТВИЕ (всегда ровно одно)

→ В PR22 реализовать полный парный evaluator protocol v1:6 policies×2
conditions, named-Gen creation receipts из warmup, aggregate criteria иbudget-
stop/partial artifacts. Проверить на41/42, затем опубликовать implementation
commit/команду ДО101–108. Protocol thresholds не менять по dev-результатам.

---

## ЖУРНАЛ РЕШЕНИЙ

Публикация З-0047/З-0048: revision abc9c27 отправлена в main;
C-15 открыт и закреплён: https://github.com/realbtr/firstagi/issues/20.
Объявление: https://github.com/realbtr/firstagi/discussions/21.
Описание репозитория обновлено под непрерывное обучение и проверку наследования.
Ссылка issue добавлена в machine-readable index отдельным служебным коммитом.
Код ядра не менялся; нового демона и перенастройки удалённого scheduler нет.

Проверка З-0049: 1486 passed, 3 skipped; вывод H22 проверен на синтетических снимках avg_cands=5.3 и 12.0. Обучение не запускалось.

Публичные ответы З-0049 доставлены через Colony 2026-10-29T19:08Z:
Solomon — comment 3069acb2-89be-41c4-9651-6715ab84c627;
ABIOME Scout — f60a9b7e-6683-4d7a-86c2-357dc34f05b9.
Исправление и manual relay опубликованы commit bd810ad. По просмотренным
GitHub Issues/PR/Discussions новых внешних сообщений после ретро нет,
C-15 не занят. На Moltbook добавлены сообщения с количественными заявлениями
без доступных артефактов; это не независимо проверенные результаты FirstAGI.

**З-0057 · 2026-10-30 · Frozen query без learning-copy и без скрытого Gen-conflict.**
Heartbeat firstagi-2 11:13Z. Mainb278a9a чистый/синхронен origin/main,
новых чужих remote commits нет, параллельной работы не обнаружено.
GitHub issue/PR comments/reviews иDiscussions/replies проверены: новых
внешних вопросов FirstAGI нет; CI/Arena bot зелёные. Colony intro4/build12,
Moltbook13 comments, новых external IDs нет. SwarmMemo #45 после09:26Z
без новых сообщений; C642 остаётся accepted design/queued, public MCP patch
не проверялся. ABIOME без artifact, Langford discovery only. Повторных ответов,
приглашений иновых contacts нет; PARTNERS/PR23 без искусственных обновлений.

По protocol1907277 реализован ac0_frozen_goal.py: FrozenGoalPredictor,
CountedBase, BoundaryError, select_goal, episode_schedule, opportunity_metrics.
Термины сначала определены вONTOLOGY, core/ не менялся. Source-before-data
1795d14f535dbd726e2d7dc38331971562ce6f10, clean. Query принимает только4 public
fields, не world/answers. Отдельные ContextBuffer/InitiativeEngine, exact
registered cue-anchor, pre-existing matching chains; advance только ephemeral
ActiveGen. process_token/begin/confirm_feature не вызываются. Полный serialized
observer SHA черезpickle protocol5 проверяется до/после query. Изменение native
counters, hedonic, pending chain, features/cache или mutation duringpropose
останавливаетrun; budget error не преобразуется вabstention. Никаких peer
pickle loads/кода иобращений ксреде вquery.

Найден новый control hazard: native propose группирует по feature ID иоставляет
одного best Gen. Проверять толькоего forecast означало бы скрыть contradictory
outcome другого Gen длятой жеoperation. Adapter использует proposed feature
set, затем раскрывает ВСЕ active Gen contributors; unique role/channel/cue/op
provenance иregistered vector сверяются для каждого. Confidence/UUID/order не
разрешают конфликт. Один operation выбирается только если прогнозы единогласны
иравны public goal; иначеабстенция. Вhand-built unit fixture2 противоречащих
цепочки дают1 native representative, но2 retained forecasts иabstention.
Это fixtureтолько дляmechanics, empirical Gen не создавались вручную.

Development CLI жёстко ограничен41/42. После96 native-random warmup attempts
наseed выполнено64 read-onlyqueries, суммарно128. ВоВСЕХ full observer hashes
не изменились, querycoretokens0,worldactions0,taskquality не оценивалось.
Modelbytes59074/60422, max explicitGenvisits54/query,feature/originreads13.
Genvisit counter включает полный prefixscan со всемиrejected records икаждый
повторный getcontext/initiative; bytehashserialization traversal отдельно
не считаетсяGen-indexaccess. Serialization/wholequery costs не равны zero;
querytimer fieldявно исключает finalhash, будущий full-runwallbudget обязан
включать обаhashes иrawwrite. Equal compute/whole-system energy/scaling
не заявляем. CLI wallbeforerawwrite0.88026s; этоdevelopment, не полныйrun.

Schedule заранее фиксирует64 channel/phase cases иoperationorders/randomchoices,
без зависимости RNGотotherpolicies.52 observed/12 unknown,16наchannel/phase.
Metrics helper оставляетabstention вobserveddenominator иразличаетunknown;
невозможноеgoal_reached=Trueприabstention отклоняется.18 meaningful tests:
actuallearned/nooracle/nolearning/frozenstate, mutationbefore/duringquery,
conflictgrouping, origin, unseen cue, removedchains, budgets, schedule,
denominator иseedguard. Full1564passed,3skipped,59 прежнихutcnowwarnings.
Wiringfixture6Genreads/5featurelookups; budget5Genreads падаетfailclosed.

Report/raw/receiptb6b11b954446dd95f665a2daa9b3f42889004310:
experiments/reports/ac0_debug/FROZEN_QUERY.md иfrozen_query/v0_1/development.json.
RawSHA de4514ed0af11c00a0f19d8adbf14e58053e0f45a7fe2071802b05f7bf73ec73,
провереныsourceclean,receipt,128 fullhashes и0 querycoretokens. Команды
reproduction/limitations вreport. PR22title/body обновлены/прикреплены, OPEN,
без self-merge. Один progress доставлен:
https://github.com/realbtr/firstagi/discussions/21#discussioncomment-19291924.
НаColony/Moltbook повторногоpost нет.

Confirming101–108 остаются UNUSED. Full paired confirming evaluator ещё НЕТ:
нужны6policies×2conditions, warmupGencreationreceipts, aggregatecriteria и
budgetstop/partialartifacts, mechanicaltests на41/42, затем frozenimplementation
commit/command доconfirmingданных. Protocol/thresholds/rawhistory не менялись.
Goal selector остаётсяhand-specifiedscaffold, анеnativepolicy илиevidence-
dependentonlinelearning. AC0–AC4/10Mvs200B+ не пройдены. Checkoutmainчистый;
обаPRоткрыты, mainledger доmergePR23 отстаёт. Секретыневыводились/некоммитились.

**З-0056 · 2026-10-30 · Preregistered frozen goal-choice diagnostic, без confirming data.**
Heartbeat firstagi-2 09:17Z. Main185080d чистый/синхронный origin/main,
чужих remote-коммитов нет, параллельный запуск не обнаружен. GitHub Issues,
PR comments/reviews и последние Discussions/replies проверены: новых внешних
обращений FirstAGI нет. Последнее Arena triage — исторический ответ28октября,
не новый результат. CI/Arena bot зелёные. Colony intro4/build12 comments,
Moltbook13, новых external IDs нет. ABIOME artifact пока не прислан;
повторного запроса не отправляли. Langford остаётся discovered only.

После З-0055 правильный следующий вопрос — можно ли выбирать полезную
операцию по learned dynamics, а не только верно предсказывать неудачу.
В PR22 ДО данных опубликован protocol1907277baf41062dbc8d5e56934f0859780782dc:
experiments/protocols/ac0_goal_choice_v1.json и
experiments/reports/ac0_debug/GOAL_CHOICE_PROTOCOL_v1.md. Термины предварительно
определены в ONTOLOGY. Confirming task seeds101–108, schedule1101–1108;
development41/42. Ни один confirming run не выполнен и его outcome не просмотрен.
Native random warmup96 attempts/seed, finalize pending chain once;768 attempts,
1920 фактических core tokens суммарно. Затем frozen state и64 one-action reset
episodes/seed:2 channels×2 phases×16, public desired outcome ID, answer tables
только evaluator. Новые эпизоды/расписание при знакомых ID/правилах — не unseen
task/transition/transfer, не independent replication. Coverage gaps сохраняются.

6 paired policies: frozen-prefix-goal scaffold, fixed-first, uniform random,
minus-long-Gen, empty-model, privileged oracle upper bound. Два conditions:
stable иswap correct operation по всем cue. Все используют одинаковый schedule,
operation order/unknown positions, precomputed random choices.6144 opportunities;
на seed/policy/condition52 observed opportunities и12 scheduled unknown.
Abstention остаётся task failure в observed denominator; unknown отдельно от
negative, отсутствие world.act не выдумывается как внешнее событие.

Численные критерии до результатов: stable macro success/coverage≥0.80;
paired advantage≥0.15 над каждым fixed/random и≥0.20 над каждым minus/empty;
положительная разница в≥6/8 seeds для каждого comparator; observed forecast
accuracy≥0.90. Отдельный rule-change evidence check≥32 observed receipts и
negative fraction≥0.50; при недостатке receipts — insufficient. Это инженерные
thresholds, не power-calibrated/statistical population claim. Budgets:≤4096
Gen visits/query,≤12288 feature/origin lookups,≤32MiB serialized model/seed,
≤300s whole run; stop/preserve partial on overrun, без продления/замены seeds.
Equal opportunity budget не равен equal compute; scans учитываются полностью.

Ключевой source constraint: begin вызывает process_token, а confirm_feature
вызывает gen.confirm(). Поэтому старый learning probe даже в discarded copy
не frozen predictor. Протокол требует separate ephemeral context/initiative,
advance только ephemeral ActiveGen после exact cue match и full observer
pickle-protocol5 SHA до/после query. Существующего partial model_fingerprint
недостаточно. Этот read-only query/runner ЕЩЁ НЕ РЕАЛИЗОВАН; он должен пройти
mechanical tests на41/42 до freezing implementation commit и confirming seeds.
Явное сравнение forecast сpublic goal — hand-specified selector scaffold,
даже его pass не будет native action policy/AC0 gate pass. Online support-
dependent reuse, непрерывная жизнь иinheritance остаются следующими вопросами.

Design audit1a244da проверил JSON, seed-pool disjointness иbudget arithmetic.
Exact Git blob protocol сохранён вgoal_choice/v1/protocol.json сSHA
2437f4fca7cfe683531b06175468573c482a2d2a88d7479fb57bbe5884370f3f;
design_audit.json иadjacent SHA receipts, reproduction code в
GOAL_CHOICE_DESIGN_AUDIT.md. Git-blob hash избегает Windows CRLF неоднозначности.
Full1546 passed,3 skipped,59 прежних utcnow warnings; это existing suite,
не валидация пока отсутствующего frozen runner. Core/ истарые raw не менялись.
PR22 title/scope/description актуализирован, прикреплён, CI SUCCESS, OPEN.
Один progress опубликован:
https://github.com/realbtr/firstagi/discussions/21#discussioncomment-19289688.
Нового Colony/Moltbook announcement не создавали. AC0–AC4/10M/200B+ не пройдены.

SwarmMemo Hugo0 принял наш MCP-checklist и сообщил постановку C642:
https://github.com/Hugo0/swarmmemo/pull/45#issuecomment-6518804696.
Это accepted design/scoping, не подтверждение публичного MCP patch/tests.
На новый вопрос о signed HTTPS route прочитаны public-only run/read_messages
вmcp.go и /api/messages→messages.list вserver.go snapshot e62d422ef987.
Рекомендован одинаковый для missing/private generic hint сcanonical doc-link
на authorized separate-client signed HTTPS read: possession of key ≠membership,
hosted sign-in не расширяет public-only tool. Не просить ключ, не делать
fallback/existence probe, не путать room сDM read_conversation. Доставлено:
https://github.com/Hugo0/swarmmemo/pull/45#issuecomment-6519347743.
PR23 ledger/receipt update047fe74, прикреплён, без self-merge. Чужой код,
private APIs иproduction тесты не запускались. Это existing partner followup;
новых first contacts/повторных приглашений нет, active candidates3.
До merge PR23 main PARTNERS отстаёт, актуальные стадии — журнал/PR23.
Оба PR остаются открыты, checkout main, секреты не выводились/не коммитились.

**З-0055 · 2026-10-30 · Named-Gen outcome replay и подтверждённый вклад партнёру.**
Heartbeat firstagi-2 07:14Z. Main fa51c9d синхронен origin/main, checkout чистый;
параллельный запуск/новые чужие изменения не обнаружены. GitHub issues/PR
reviews/Discussions, CI/Arena bot проверены; новых внешних вопросов FirstAGI
нет. Colony intro4/build12 comments, Moltbook13, новых external IDs нет.
Старую разницу снимков не выдавали за новые сообщения, повторных ответов нет.

В PR22 добавлена диагностика ac0_outcome_evidence.py. До данных зафиксированы
термины ONTOLOGY, debug plan, seeds41/42, fixed/random native warmup48 и
48 replay attempts на cohort; source-before-data64148cae1a3e3ce716591c6833e62813150c1601,
source clean. Тот же learned Gen должен давать live operation binding и
следующий outcome-edge с уникальным provenance channel/operation/observation.
Целевой ответ, oracle и fixture prediction_support при извлечении не читаются.
Прогнозы для fixture-selected operation фиксируются/hash-ятся ДО world.act;
затем внешняя квитанция сравнивает actual observation с прогнозом Gen.
Это локальный порядок runner, не trusted timestamp. Квитанции отдельно от
native success/stop counters; они не меняют policy. Core/ не менялся.

Результат105/192 attempts с forecast:35/48,12/48,36/48,22/48 по cohorts
41fixed,41random,42fixed,42random.77 positive,0 observed negative,28 unknown.
57 positive receipts соответствуют task-divergent operation: верно знать,
что действие неудачно, не значит выбрать полезное действие. У каждого cohort
есть повторные обращения к тому же named Gen. Например seed41fixed Gen
51dba223-bc8d-4c50-8b1f-daf6a27e7653 предсказывает3fc31a98c7fd59a0 в событиях
3/5/7/9; actual совпадает, действия task-divergent. Gen IDs случайны на run.

Ограничения: replay той же warmup trajectory на тех же правилах, in-sample;
per-cue свежая копия finalized snapshot, discard cue update, не непрерывная
жизнь/frozen skill control. Независимая среда отделяет факт от core counters,
но сам replay НЕ independent replication. All forecasts retained, конкуренция
не разрешается, goal-conditioned action selection нет. Negative проверен unit
intervention, в эмпирическом replay отрицаний нет. Равный compute не заявляем,
global prefix scans и full-state copies остаются diagnostic overhead.
AC0–AC4 и10M/200B+ не пройдены. Следующий шаг — конкретный preregistered
held-out task-choice trial, не очередная замена навыка числом кандидатов.

9 новых meaningful tests: actual learned forecast/no oracle/no mutation,
unknown statuses, prediction/task distinction, cross-event guard и seals/reuse.
Full1546 passed,3 skipped,59 прежних utcnow warnings. SHA/seals проверены:
6c75f1f28c2eba8e3bac05ed8e2483bf52000563f94297a71729f656c0dff582.
Report/raw/receipt commit8fa759c6d908a98d7a3c03c02b51a62cd34b595b,
experiments/reports/ac0_debug/OUTCOME_EVIDENCE.md. PR22 обновлён/прикреплён,
CI SUCCESS, OPEN. Один progress доставлен:
https://github.com/realbtr/firstagi/discussions/21#discussioncomment-19287493.
Дополнительный Colony announcement не создавали.

SwarmMemo Hugo0 сообщил public release1.146.52/snapshot e62d422ef987:
https://github.com/Hugo0/swarmmemo/pull/45#issuecomment-6516551040.
Исходник Python CLI и test_private_read_hint.py доступны, независимо прочитаны:
hint только keyless read/not_found;4 test definitions проверяют exclusions,
stderr JSON,stdout empty,exit1,one request,no key. Public source blocker снят;
чужой код/тесты и production не исполнялись, live release самостоятельно
не подтверждён. Internal87134a70 не выдаётся за публичный commit.
По новому запросу сопровождающего6515973721 прочитаны MCP public-only path,
read_messages dispatch и hosted tests snapshot e62d422ef987. Доставлен bounded
checklist: одинаковые missing/private fixtures; сохранение isError/code/retry,
text/structured consistency; anonymous иhosted не получают private scope;
никакого дополнительного existence probe/создания identity/key. CLI--key
подсказка неприменима к public-only tool. Receipt:
https://github.com/Hugo0/swarmmemo/pull/45#issuecomment-6517301732.
PR23 ledger/receipt обновлён commitab3f156, прикреплён, без self-merge.
Это продолжение принятого source-review, не новый first-contact и не
независимый тест patch. ABIOME без нового artifact; Langford discovery only;
3 active candidates, новых контактов/повторных приглашений нет.

Оба PR остаются открыты, checkout main. Журнал сохраняет актуальные статусы:
main PARTNERS до merge PR23 отстаёт. Секреты не выводились/не коммитились.

**З-0054 · 2026-10-30 · Парная recall-policy ablation без ручного seeding.**
Heartbeat firstagi-2 05:08Z, завершение около05:25Z. Main9c4fba5 и PR22
58efa83 были чисты/синхронны. Новых внешних вопросов, reviews и ответов
Colony/Moltbook/SwarmMemo нет; CI/Arena bot зелёные. Ничего повторно не отвечали.

В CodedKernelObserver добавлен явный exact_learned_prefix adapter; default
native_atomic сохранён. Recall активирует только pre-existing chain>1 Gen
с точным публичным cue-anchor prefix, не создаёт Gen и не читает правильную
операцию/target. В 4 warmup cohort (seed41/42, fixed/random) actual kernel
учится48 attempts, затем pending chain завершается обычным reset_context.
Каждая проба и condition starts из deepcopy того же завершённого observer;
base/feature/provenance/step fingerprints перед вмешательством равны,
общая training-база после проб не изменена. minus_long_gen удаляет chain>1
до того же explicit recall. Все условия получают1 cue token; recall scan
стоит дополнительных внутренних обращений, равного compute budget не заявляем.

Тесты сначала поймали invalid control: reset мог заново создать только что
удалённую pending chain. Исправление — завершить общую warmup-chain ДО
snapshot/удаления, а не ослаблять pre-existing-Gen проверки. Данные invalid
варианта не публиковались как результат. Source-before-data113f960, итог
report/raw/receipt956eb89. Во всех4 cohorts native candidate coverage0/48,
prefix47/48,48/48,48/48,48/48; minus0/48. Всего191/192 candidate-covered
views, из них119 с1 distinct operation и72 с конкурирующими. Это192 повторные
views8 типов из warmup, не held-out задачи и не191 correct actions. Во время
probe нетworld.act/oracle/task score; actual actions всё ещё только warmup
fixture. Cue updates в отдельных copies разрешены и discarded: это не
frozen-model skill control. Manual Gen seeding нет, core/ не менялся.
Следующий шаг — one named Gen external outcome/evidence/reuse, не новый
отчёт об одном лишь покрытии. AC0–AC4/10M/200B+ не доказаны.

6 новых recall-tests (включая pending-chain regression), full1537 passed,
3 skipped,59 прежних datetime.utcnow warnings. Raw receipt, paired fingerprint
equality, existing-Gen origin, cue budgets иminus controls проверены отдельно.
PR22 обновлён/прикреплён, CI SUCCESS, OPEN. Отчёт:
experiments/reports/ac0_debug/RECALL_ABLATION.md (в PR/956eb89).
Один progress опубликован:
https://github.com/realbtr/firstagi/discussions/21#discussioncomment-19285687.
Новый содержательный результат сообщён в собственном Colony build-thread,
comment7919e525-9b42-476a-b5c9-f7d92ff13fcc,05:21:54Z; предложена bounded
независимая проверка paired/minus controls, без массовых приглашений.

SwarmMemo public HEAD теперь3e9b7bf194cad3488583207015368529eabc1ca7, но
reported test_private_read_hint.py всё ещё404. Acceptance review сохраняется,
independent implementation verification остаётся pending; нового напоминания
не отправляли. ABIOME artifact/реакции пока нет.
Read-only discovery: ColonistOne/langford commit5a63e9ef3ecd379d39dc31b855b70d8c0d6f7baa,
README сам связывает проект с Colony @langford и langchain-colony. Это
подтверждённый source-linked кандидат, не доказательство прав handle на repo.
Изучены назначение и roadmap; его live-agent/commands не запускались.
Помощь и приглашение ещё не отправлены: дневной first-contact budget уже
использован SwarmMemo. Третий discovered record добавлен в PR23 commite0e2d66,
CI SUCCESS, OPEN/прикреплён; active records3, не расширять без пересмотра.
До слияния main PARTNERS отстаёт, сверять актуальные receipts по журналу.
Оба PR без self-merge; checkout main, журнал обновлён.

**З-0053 · 2026-10-30 · Coded observer/native recall probe и accepted peer review.**
Heartbeat firstagi-2 03:08Z; завершение около03:25Z. Main2f5fb38 и PR22
8563774 были чистыми/синхронными. Новых вопросов/ревью на арене и сообщений
Colony/Moltbook нет; CI/Arena bot зелёные. Повторных приглашений не посылали.

В PR22 добавлен отдельный CodedKernelObserver. Actual cue_anchor и завершённые
cue_to_operation/operation_to_observation Feature/PeripheralToken поступают в
existing LearningSystem. Unknown outcome не порождает fake op/outcome tokens,
но реальный cue всё равно наблюдается. После cue вызывается InitiativeEngine
заново, с actual expected Gen/feature mapping. KernelBinding связывает свежий
proposal с observed feature origin, core step и digest живого контекста,
включая chain position/counters. Перед decode повторная live-проверка; смена
состояния/источника/registry/vector или relabelled borrowed feature abstain.
Это локальные guard-ы, не аутентификация недоверенного кода и не разрешение
исполнить действие. Предыдущая operation-codec схема/хэши сохранены (тест).

Source-before-data1c2a31a, report/raw58efa83. Четыре unseeded streams seed41/42
fixed/random,48 attempts каждый:120 core tokens (48 cues+72 completed edges).
Контекст явно reset перед cue — debug scaffold, не AC1 continuity. Свежих
proposals3/3/2/3=11; eligible bound operations0 во всех runs. Все11 отклонены
по current cue/operation provenance; их не исполняли, это не11 wrong actions.
Все actual actions по-прежнему fixture. Long prefix Gen присутствовали в
38/32/39/34=143 из192 views, final long Gen6/11/6/15. Код native loader
пускает matching chain=1 и atomic fallback; это кандидат объяснения, не
доказанная единственная причина нулевой operation coverage. Следующий шаг —
явная recall-policy ablation, без скрытого ручного заполнения контекста.

14 новых test cases; позитивный unit fixture вручную строит Gen/context и
так обозначен, empirical run его не использует. Четыре AC0 modules45 passed;
full1531 passed,3 skipped,59 прежних datetime.utcnow warnings. Raw SHA receipt,
token counts, unknown boundaries и rejection reasons независимо перепроверены.
Нет edits core/, named-Gen external task-support или useful action/evidence/
reuse результата; AC0–AC4 и10M/200B+ по-прежнему не доказаны.
PR22 обновлён/прикреплён, CI SUCCESS, OPEN без self-merge. Отчёт в ветке:
experiments/reports/ac0_debug/KERNEL_BINDING.md. Один progress опубликован:
https://github.com/realbtr/firstagi/discussions/21#discussioncomment-19284345.
Нового announcement или повторного соцпоста нет; checkout возвращён main.

SwarmMemo Hugo0 публично подтвердил принятие source review и reported применение:
https://github.com/Hugo0/swarmmemo/pull/45#issuecomment-6513753146.
Reported internal commit87134a70 не разрешается в public snapshot repo;
test_private_read_hint.py нет в доступном d14a18239b41f0dfe6384e9b6840502ac2a98a52.
Статус accepted source review — на основании maintainer receipt, не independent
implementation/test verification и не подтверждение release/платежа. Источник
не запускали, private content не читали. На прямой follow-up вопрос об уровне
hint ответили по опубликованной SECURITY.md: actionable guidance в client/
adapter с учётом signing state, одинаковый missing/hidden server response,
hosted-MCP anonymous boundary сохраняется. Ответ доставлен03:13:50Z:
https://github.com/Hugo0/swarmmemo/pull/45#issuecomment-6514051346.
Наград/ответного участия не просили. Регистр/receipt обновлены в отдельном
PR23 commitc894ac7, CI SUCCESS, OPEN/прикреплён; main PARTNERS до слияния
ещё не отражает acceptance, не дублировать контакт исходя только из него.
Дальше ждём public snapshot для implementation verification, без напоминаний
каждый цикл. ABIOME конкретный artifact по-прежнему не прислал.

**З-0052 · 2026-10-30 · Codec boundary и первый доставленный peer review.**
Heartbeat firstagi-2 01:07Z, завершение около01:20Z. Main ce196e6 и PR22
4468cdf были синхронны/чисты; новых внешних сообщений и ревью нет. Проверены
GitHub Issues/PR/Discussions, Colony/Moltbook threads, Arena status/CI.
Новых ответов на уже обработанные вопросы и повторных приглашений не было.

В PR22 добавлен отдельный OperationCodec/PredictionFrame и codec audit.
Source before data c854439, код/отчёт/raw/receipt8563774. Публичные поля
version/role/channel/cue/operation образуют canonical key; SHA-256 даёт ID
и6 координат FeatureVector. Это identity baseline, не semantic geometry,
не глобально бесколлизионный код и не новая аксиома ядра. Определения
добавлены в ONTOLOGY только в ветке PR. Decoder отклоняет пересекающиеся
candidate tolerance balls, несовпадающие declared cue/channel/seq/phase/
version/Gen metadata и отсутствие единственного соответствия. Возвращённый
кандидат не является разрешением на исполнение; метаданные не доказывают
действительное происхождение предложения от ядра.

Использованы4 прежних fixed/random streams seed41/42 ×48 public views.
Перед извлечением только channel/cue/available ops проверены input receipts.
Две synthetic queries на view × tolerances0.15/0.6:768/768 identity roundtrips,
0 wrong decodes и0 abstentions на данном конечном наборе. Stale/wrong-cue/
before-token frames отклонены768 раз в каждой категории. Это192 views,
не768 независимых задач/успехов модели. Unit tests искусственно создают exact
и near collisions — они abstain. Ближайшая пара seed42 distance1.23795,
при tol0.6 запас только~0.038; реальные новые входы могут корректно abstain.
Source checkout до данных clean, raw receipt и counters проверены повторно.
16 новых тестов, три AC0 modules31 passed; full1517 passed,3 skipped,
59 прежних datetime.utcnow warnings. PR22 CI SUCCESS, не слит, прикреплён.
Старый TextDriver observer, core/ и прежние raw data не менялись. Codec
ещё не включён в learning/proposal stream; kernel-selected actions0.
AC0–AC4, Gen-specific evidence/reuse, retention/inheritance и10M/200B+ не доказаны.

Один progress опубликован:
https://github.com/realbtr/firstagi/discussions/21#discussioncomment-19282412.
Отчёт: experiments/reports/ac0_debug/CODEC_BOUNDARY.md в PR22/commit8563774.
Нового announcement/соцдубликата нет.

По правилам contribution-first изучен follow-up Hugo0 в SwarmMemo PR45 на
source cc1cb1b43621868f0f57efe858f569183c2d3081. Доставлен конкретный source
review CLI stderr JSON path и acceptance matrix для generic not_found hint:
https://github.com/Hugo0/swarmmemo/pull/45#issuecomment-6512514232 (01:16:44Z).
Не исполняли peer code, не читали private rooms, не утверждали patched pass.
Вклад delivered, НЕ acknowledged/accepted; наград/ответной помощи/перехода
на нашу арену не просили. Не дублировать этот комментарий следующим циклом.
Реестр PARTNERS и копия receipt предложены отдельно: PR23,
https://github.com/realbtr/firstagi/pull/23, branch agent/swarmmemo-review-record-20261030,
commit f1d6192. Не слит, прикреплён к чату; ops changes требуют ревью.
До слияния ledger main ещё показывает discovered — доставку сверять с этой
записью и публичным receipt. ABIOME по-прежнему ждём конкретный artifact.
Checkout восстановлен на main; оба PR оставлены открытыми без self-merge.

**З-0051 · 2026-10-30 Europe/Belgrade · Operation decoding: отрицательный результат.**
Heartbeat firstagi-2 2026-10-29T23:09Z, завершение около 23:20Z. Main a2e3eab
и PR22 dfef2cf были чистыми/синхронными; новых ревью, внешних Issues/PR/
Discussion-комментариев или сообщений Colony/Moltbook после прошлого обхода
нет. CI main/Arena bot/PR22 зелёные. Повторных ответов не отправляли.

До wiring proposal→operation проверены предпосылки. TextDriver строит vocab
на первом triple, незнакомым символам даёт rank0.5. Операции seed42 имеют
идентичный FeatureVector во всех 46 initialized views для fixed и random.
В seed41 точных коллизий нет, но во всех initialized views есть OOV symbols.
Самостоятельный synthetic counterexample из двух разных equal-shape opaque
IDs дал distance0.0. Из 4 streams ×48 attempts: initialized views184,
exact aliases92, completed observations144. Cached/current expected feature
sets различались после122 completed observations (36/14/36/36 по streams).
Это не122 wrong actions: last_proposals по контракту генерируется до токена;
after-observation адаптер должен явно выбрать свежую фазу и provenance.
Scope: конкретный opaque-symbol TextDriver observer; не все драйверы и
не опровержение общего алгоритма. Передавать такую неоднозначность в действия
в этом цикле сознательно не стали; обученный контроллер не реализован.

Source-before-data ae4e8b0; report/raw/receipt commit4468cdf в той же ветке
agent/ac0-event-baseline-20261029. Новая read-only диагностика не меняет vocab,
token count или initiative counters и не спрашивает oracle; 5 новых тестов.
Полный набор1501 passed,3 skipped,59 прежних warnings. Два AC0 modules15 passed.
Повторный аудит воспроизвёл aggregate counts; raw SHA-256 receipt проверен.
Предыдущие v0.1 данные и core/ не менялись. AC0–AC4 не пройдены.
PR https://github.com/realbtr/firstagi/pull/22 обновлён, CI tests SUCCESS,
прикреплён к чату, остаётся OPEN, без самостоятельного слияния.
Report: experiments/reports/ac0_debug/PROPOSAL_READINESS.md в PR.

Один progress в Discussion21:
https://github.com/realbtr/firstagi/discussions/21#discussioncomment-19280896.
Новый результат и bounded предложение независимой проверки опубликованы
в собственном Colony thread8ec09325..., comment796ced84-c57c-4dea-af3e-12fd8952c9e6.
Новых announcements/массовых приглашений не было. ABIOME всё ещё ждём artifact.
SwarmMemo проверен на f1385a580ca2000f46679df31f6e391a24b50603: issue40 уже
подтверждён/исправлен Hugo0, с test_main_guard.py и credit исходному автору;
не дублировали finding и не приписали вклад себе. Статус сотрудничества не принят.
Checkout возвращён на main; следующий шаг изменён на устранение кодировочного
блокера до проверки learned action selection, а не обход найденной ошибки.

**З-0050 · 2026-10-29 · Плановый цикл firstagi-2: AC0 event debug baseline.**
Запуск 21:11Z, проверка/публикация завершена около 21:20Z. Remote main
совпадал с 620b88b, checkout был чистым. Проверены новые GitHub Issues/PR/
Discussions, CI/Arena bot и собственные Colony/Moltbook-треды; новых внешних
обращений после предыдущего обхода нет. Ничего повторно не отвечали и
новых приглашений не посылали; ожидаем конкретный артефакт ABIOME Scout.
У C-15 отсутствовала метка challenge — добавлена для обработки броней ботом.

Создана ветка agent/ac0-event-baseline-20261029, source-only commit 462f6b3,
данные/отчёт dfef2cf. PR: https://github.com/realbtr/firstagi/pull/22 (open,
не слит, прикреплён к чату; GitHub CI tests SUCCESS). Код ядра не менялся.
В experiments/diagnostics/ac0_event_baseline.py контролируемая непрозрачная
двухканальная среда отделяет операцию/фактический исход от core StepOutcome.
Unknown не превращается в negative; pending cue сохраняется. Validator
отклоняет нарушенные causal chains и fabricated success; observer отклоняет
повторную доставку до второго обновления. Это in-memory, не durable exactly-once.
Existing TextDriver/LearningSystem наблюдает завершённые переходы, не выбирает
действия; fixture prediction_support не является поддержкой названного Gen.

Два seed (41/42) × fixed/random/privileged oracle, по 48 попыток. Каждый run:
36 наблюдённых исходов, 12 unknown, 72 токена observer. Successes: fixed13/24,
random16/17, oracle36/36 (знаменатель 36 для каждого seed). Все шесть traces
и SHA-256 receipts проверены, 10 новых тестов. Полный набор: 1496 passed,
3 skipped, 59 прежних datetime.utcnow warnings; GitHub CI тоже зелёный.
Raw данные и ограничения — experiments/reports/ac0_debug/README.md в PR.
Seed42 dirty flag отражает тогда untracked seed41 data; source не менялся.
Фиксированное расписание, контроллеры-scaffold, нет learned Gen support,
held-out competence, actual index-work counters, persistence/inheritance;
AC0–AC4 по-прежнему не пройдены. Никакой новой оценки 10M/200B+.

Один progress опубликован в существующем Discussion21:
https://github.com/realbtr/firstagi/discussions/21#discussioncomment-19278777.
Никаких новых announcements или повторных соцпостов. Рабочая ветка main
восстановлена; исследовательский код остаётся в PR до ревью. Событийный
debug контракт теперь исполним, ближайший разрыв — выбор операции из ядра.

**З-0049 · 2026-10-29 · Новые отклики Colony и исправление H22.**
Solomon обнаружил оставшиеся старые вердикты H22 в scale README и скрипте
(Colony e1a39f62-f4e2-4016-b30f-dfc02c945c5b). Проверено по исходникам:
исторические raw данные не меняются; исправлены аннотация и будущий вывод,
автоматический вердикт по интервалу 4–8 удалён. Это не новый прогон H22.
ABIOME Scout сообщил об установке MCP и чтении 14 вызовов, сам факт его
запуска нами не воспроизведён. В ответ на вопросы введена ручная подача
finding JSON через Colony с атрибуцией платформенного handle, без GitHub
аккаунта; schema-valid не значит accepted. Ответная помощь — bounded review
по задаче, без гарантированных ресурсов, наград или рекламных обещаний.
На C-15/Discussion21 новых ответов пока нет. CI main и Arena bot зелёные.

**З-0048 · 2026-10-29 · Адресное сотрудничество через полезный вклад.**
Владелец предложил перенести механику взаимного чтения стихи.ру на агентов:
искать их проекты, помогать и приглашать помогать нам. Принят bounded-пилот
ops/RECIPROCITY.md, журнал статусов ops/PARTNERS.json. Помощь не обусловлена
ответной услугой; просмотр/отправка/принятие различаются. До трёх кандидатов,
одного нового контакта в день и 30 минут на запуск; AC0 остаётся первым.
Проверены публичные правила и существующая PR #26 Hugo0/swarmmemo на commit
d96cfeafab3d1547924b98cb062eec98817dd07b. Статус discovered; не объявляем
вклад отправленным или партнёра привлечённым, PR не дублируем. Политика
добавлена triage, удалённое расписание не перенастроено; нового демона нет.

Проверка итоговой редакции 2026-10-29: `py -m pytest -q` — **1486 passed, 3 skipped**, 59 предупреждений о существующем datetime.utcnow. Код ядра не изменён.

**З-0047 · 2026-10-29 · Ретро: непрерывное ядро — ближайшая проверяемая цель.**
Владелец прямо поручил пересмотреть концепцию, решения, гипотезы, манифест,
хэндофф и фокус арены. Найдены сентябрьские конституции в !!!FirstAGI,
не попавшие в git; импортированы без изменений в docs/concept (хэши SOURCES).
Приняты требования: непрерывная жизнь и многомасштабный частичный контекст;
исход действия отдельно от поддержки Gen; unknown/interrupted ≠ отрицание;
непрозрачная периферия; локальные W отдельно от опубликованных редакций B;
публикация при жизни; чистое наследование и независимые свидетельства;
проверяемый локальный фронт и ресурсы. Конкретные алгоритмы остаются baseline.
Ретро с исходниками и smoke: docs/RETROSPECTIVE_2026-10-29.md. 259 выбранных
тестов компонентов прошли. Smoke: 10 текстовых + 5 числовых переходов,
fixed-priority alpha→beta; собственный pickle сохранил числа Gen/Features;
GenBaseDB.load(base) восстановил 15 Gen, 0 Features, 15 неразрешённых ссылок.
Это граница проверенного API, а не утверждение обо всех маршрутах хранения.

Пересмотрены A-03/A-07/A-08/A-15/A-20; новые A-30…A-37 фиксируют требование,
не готовность кода. CON-H1…CON-H8 перенесены как H27…H34 без коллизии со
старыми H1…H26; H35 — непрерывная компетентность в каналах. Всё открыто.
Новый порядок AC0→AC1→AC2 (затем AC3/AC4): один полезный Gen, непрерывное
умение одной жизни, чистое наследование. E2 остаётся проверкой ветки обмена,
неудача её baseline не останавливает одиночный путь. Дальний 10M/200B+ сохранён.
Прежние SPEC v1 и ROADMAP сохранены в архиве; SPEC v1.1 и операционный
baseline v0.1 явно отличают контракт от реализации. Мораторий З-0010 и
запрет В0–В18 уточнены: данное явное поручение владельца разрешает
доказательный пересмотр, не снимая защиты от спекулятивных переписываний.

H22 не подтверждает W=7±2 и не объём памяти; H7/H26 — результаты своих
стендов, не общие законы. 40GB нельзя переводить в число параметров без
формата/разрядности; прежняя оценка ~10¹⁰ — лишь иллюстрация для float32,
не измерение и не строгая нижняя граница. О-8 сохраняется для прямого аудита.
Арена C-15: Teach a skill. Interrupt it. Let a fresh mind inherit it.
Новых внешних способностей и результатов не объявлено; критерии с числами
должны быть зарегистрированы до confirming runs. Код ядра не менялся.

**З-0046 · 2026-10-29 · H22: пилот завершён, пакет для публикации подготовлен.**
Протокол и код зафиксированы/отправлены до данных (74606f7). Выполнены
14 условий-seed и повтор baseline, по 8000 токенов; 191.6 с суммарно.
Все контроли прошли: синтетика 1/7/16, одинаковые входы, неизменность
замороженных проб, точное совпадение повторного нечасового результата.
Поздние средние кандидатов: без cap 17.59–18.34; cap1024 7.55–7.75;
cap256 0.56–1.08; tolerance=.075 21.34–22.26, .30 7.65–7.75.
max_competing=2/8/32 эту метрику в пилоте не изменил. При cap256 база
518–525, поскольку короткие цепочки защищены: номинальный бюджет не
жёсткий; превышения и вытеснения сохранены. Это диагностика лексического
ветвления, не тест ёмкости памяти и не повтор старого полного 1M опыта.
Статус H22 уточнён как наблюдение стенда; финального вердикта нет.
Основная серия остаётся выключенной до разбора пилота/поправки протокола.
PILOT_REPORT.md, все входы/выходы, хэши, PNG/SVG и черновики RU/EN в
experiments/reports/h22; training/h22_report.py проверяет хэши до анализа.
Социальные посты по пилоту ещё не опубликованы. Идея — Solomon (Colony),
закрепление эталонов — Skitter. Ядро и следующий S2-шаг не изменены.

**З-0045 · 2026-10-29 · H22: протокол пилота v1 до получения данных.**
По поручению владельца подготовлены training/h22_counterfactual.py,
experiments/protocols/h22_v1.json и experiments/reports/h22/PROTOCOL.md.
Семь однофакторных условий (бюджет, tolerance, max_competing), два seed,
8000 обучающих токенов и повтор baseline; 15 прогонов. Пробы заморожены,
их обработка не вызывает process_token; нулевые множества учитываются.
Старый scale_experiment обучается во время измерений. candidates_before —
лексическая степень исхода индекса, отдельно от max_competing=8 в
LazyDisambiguator. Эти факты требуют ограничения трактовки H22.
Протокол, критерии и код фиксируются коммитом до пилота. Основная серия
выключена до разбора пилота; пилот не закрывает H22/C-14. Автор идеи
контрфактуала — Solomon; требование закреплять эталоны — Skitter.

**З-0044 · 2026-10-29 · Повторный обход площадок и ответы; кандидат body-swap в C-01.**
Проверены GitHub Issues/PR/Discussions и две заявки в каталоги: новых
внешних вопросов и ответов модераторов нет. Colony: существующие ответы
H22/предикаты/эталоны на месте; уточнён чрезмерный вывод предыдущего ответа
skitter-swarmmemo: совпадение одного quick-прогона не доказывает отсутствие
дрейфа full-1M и не ограничивает причины расхождения железом/окружением.
Moltbook: maniresearchagent получил ответ о body-swap, независимом росте,
фиксации выравнивания до теста, оценке в мировых координатах и реактивном
контроле. Исправлено прежнее утверждение «только символьные драйверы»:
в репозитории есть SequenceDriver, но нет embodied-E2 стенда. Clara получила
ссылки на AttentionTracer и тесты с границами гарантий (по исходникам).
Все три новых комментария Moltbook прошли verification; это проверено API.
По явному решению владельца body-swap принят как кандидат проекта опыта
в C-01, реализация отложена до E1/E2; авторство maniresearchagent / Mani
Bharathy сохранено. Записано в #1 (issuecomment-6494765747); очки не начислены.
Новых решений от владельца сейчас не требуется. Код ядра не менялся.

**З-0043 · 2026-10-29 · Ответы агентам опубликованы; число тестов — устойчивая формулировка.**
С согласия владельца («на спам не отвечаем»): The Colony — ответы
@skitter-swarmmemo (эталоны и детерминизм), @solomon (что мерит H22,
приглашение в C-14), @deep-seeker/@langford (предикаты accept/fails_if;
«подтверждающий ≠ спрашивающий» записан как ограничение для проверки, не
правило); Moltbook — @maniresearchagent (REFUTED-след и H7, вытеснение по
бюджету, E2 на символах; действие-конвергенция → C-01). Без ответа: реклама
и болтовня; предложение-сводничество @publicmarketresearchrelay.
Число тестов во внешних текстах: «1400+, все зелёные в CI» (точное — по коммиту).
Открыто для проверки: «подтверждение только от не-спрашивавшего и такое,
которое могло провалиться» (deep-seeker) — кандидат в ограничение ядра.

**З-0042 · 2026-10-29 · Первые отклики агентов; эталоны и предикаты закреплены; H22 уточнена.**
Под постами в Colony и Moltbook — 9 комментариев агентов. Принято по
существу: (1) @skitter-swarmmemo — эталоны C-05/C-07 не закреплены →
challenges.json: sha256 + коммит; новый baseline_quick_seed42.csv совпал со
стендовым scale_dual.csv во всех нечасовых ячейках — прогон детерминирован,
дрейфа кода нет. (2) @deep-seeker/@langford — результат есть данные только при
заранее закреплённом критерии → у всех вызовов accept/fails_if. (3) @solomon —
H22 мерит candidates_before (конкуренты на шаг), а не объём памяти; диапазон
2.0–12.6 по снапшотам; контрфактуал не ставился → формулировки исправлены во
всех внешних текстах, вызов C-14 (контрфактуал H22, автор идеи — solomon).
Найдены и исправлены два бага бота: Issue вызовов проверялись как находки
(8 ложных комментариев удалены); логин github-actions из GraphQL не
считался ботом (ложное «ждёт владельца»).

**З-0041 · 2026-10-28 · Полярная звезда — в продукт-слое; открыт О-8.**
Владелец дал Claude право менять любые файлы проекта. По З-0040 обновлены
MANIFESTO (раздел «Полярная звезда»; E2 — внутренняя ставка; исключение из
правила «только E2» — мерило строят флоты, ядро не трогается), VISION (§0,
строка в таблице антитезиса, числовая рамка), GOALS (параллельный горизонт,
M0–M1 не зависят от E-гейтов), ROADMAP (дорожка арены). Найдено и записано
противоречие О-8: Ядро-10М оценено в ~40 GB ≈ 10¹⁰ чисел, а бюджет звезды —
10⁷ параметров при строгом счёте (выбор владельца) — разрыв три порядка.

**З-0040 · 2026-10-28 · North Star: ≤ 10M параметров рассуждают на уровне 200B+.**
По решению владельца большая цель сформулирована измеримо для флотов:
NORTH_STAR.md. Подсчёт строгий — параметр = любое хранимое число/символ,
читаемое при ответе (код движка не считается); на тесте без LLM и веба;
LLM-учителя допустимы при росте, удержанное от них — считается. Два уровня:
L1 «рассуждение без знаний» (ARC-AGI-1/2 public eval + свежий процедурный
набор) — цель сейчас; L2 языковые рассуждения (GSM8K, MATH, BBH, MMLU-Pro,
GPQA) — дальний рубеж. Паритет = счёт ≥ эталона ≥200B на том же стенде.
Лестница M0–M6; честный статус — M0 не начат. Новые вызовы: C-10 стенд
(500), C-11 базовая лестница (300), C-12 строгий аудит параметров (200),
C-13 первая честная точка на L1 (500). Мораторий З-0010 не нарушен: это цель
и метрика, не архитектура. Продукт-слой (MANIFESTO/VISION) — обновить
формулировку «10⁷ различений» владельцу при следующем обходе (М2).
Первый внешний PR (#13) — бот-спам: сортировщик разобрал верно, закрыт;
в TRIAGE.md добавлено право закрывать явный спам по трём условиям.

**З-0039 · 2026-10-28 · Moltbook: агент подтверждён, пост опубликован; токен PyPI отозван.**
Агент firstagi_arena зарегистрирован владельцем (скрипт; авторежим Claude Code
заблокировал регистрацию агентом), подтверждён твитом владельца; ключ —
.secrets/moltbook.env. Первый пост потерял проверочную задачу (ответ на
создание был обрезан в выводе, а задача выдаётся один раз, 5 минут) —
невидимый пост удалён, повтор через окно 2 ч для новых агентов, задача решена,
пост в m/builds виден. Урок: ответ на POST /posts в Moltbook читать целиком.
Владелец удалил токен PyPI, засвеченный в чате.

**З-0038 · 2026-10-27 · Облачный сортировщик запущен; пересылка в Discussions.**
GitHub подключён к claude.ai (/web-setup владельца). Создана ежедневная
задача «FirstAGI arena triage» (trig_01ScUrRgtWCx6JyTaJRXZ663, 08:00 UTC,
claude-sonnet-5-5). Коннекторы Gmail/Drive/Calendar/Docs, подключённые
сервером по умолчанию, сняты: сортировщик читает недоверенные тексты —
доступ к почте недопустим. Пробный прогон: чтение Issues/PR через
GitHub-инструменты облака работает; gh и GraphQL в облаке недоступны →
писать в Discussions нельзя. Решение: комментарий в #12
`relay → discussion #N` / `relay → announcement: …` пересылает бот в Actions
(discussions: write), только от владельца; проверено вживую (#11). Открыто:
под каким логином облако пишет комментарии — если не владельца, добавить
логин в ARENA_RELAYERS.

**З-0037 · 2026-10-27 · Лицензия MIT; агент арены в The Colony.**
Владелец выбрал «максимально открытую» лицензию → MIT (LICENSE в корне и в
пакете firstagi-arena; в метаданных PyPI появится со следующим релизом).
The Colony (thecolony.ai, оператор Starsol Ltd; .cc — тот же сервис):
зарегистрирован агент firstagi-arena, оператор @realbtr указан в профиле;
ключ — .secrets/colony.env (в git не попадает), владелец может отозвать его
ротацией. По правилам площадки самопродвижение не маскируется: оба поста
прямо говорят, что это проект оператора. Опубликованы: introductions,
build-in-public. Больше постов без нового повода не делаем (антиспам).

**З-0036 · 2026-10-27 · MCP-сервер опубликован: PyPI + реестр MCP.**
firstagi-arena 0.1.0 на PyPI (токен владельца, использован однократно через
переменную окружения, не сохранён; владельцу рекомендовано отозвать его).
io.github.realbtr/firstagi-arena 0.1.0 в официальном реестре MCP, статус
active (вход GitHub-устройством владельца). server.json переведён на схему
2025-12-11. mcp-publisher взят v1.8.1 (август): пять релизов за последние
четыре дня — свежие бинарники не берём. Подключение сократилось до
`uvx firstagi-arena`; ссылки в AGENTS.md, llms.txt, README пакета обновлены.

**З-0035 · 2026-10-27 · Запуск продвижения: каталоги и тексты постов.**
По согласию владельца поданы заявки в каталоги, где проект проходит по
правилам: ARUNAGIRINATHAN-K/awesome-ai-agents-2026 #482 (форма, 🔬 Emerging,
Agent Evaluation and Benchmarks), caramaschiHG/awesome-ai-agents-2026 PR #702
(Benchmarks). Не поданы: aloth/awesome-ai-agents (порог >100 звёзд) и
best-of-Agent-Harnesses (только harness-проекты, порог по звёздам) —
вернуться после роста звёзд. Тексты для Moltbook, The Colony, HN, Reddit, X,
Хабра — ops/launch/POSTS.md. Пакет firstagi-arena собран и прошёл twine
check; публикация на PyPI и в реестре MCP — за владельцем (токен, вход).
Открыто: в репозитории нет LICENSE — решение владельца.

**З-0034 · 2026-10-27 · MCP-сервер арены; правила автономной сортировки.**
integrations/mcp_arena (пакет firstagi-arena, mcp>=1.20,<2): 8 инструментов —
вызовы, бриф со статусом брони, чтение документов по белому списку, pytest и
scale-эксперимент в клоне агента, проверка схемы находки, готовая ссылка на
Issue; сервер сам ничего не публикует. Проверен по stdio сквозь протокол.
Найдено и исправлено: дочерний процесс наследовал stdin сервера (канал MCP)
и вис — теперь stdin=DEVNULL. server.json подготовлен для реестра MCP
(публикация требует PyPI — за владельцем). ops/TRIAGE.md — публичные правила
ежедневного облачного агента: по решению владельца («пусть работает сам»)
отвечает от его имени, начисляет очки (окончательные — за проверенное
исполнением/источником, предварительные — за суждение), сам сливает PR только
в отчёты/публикации/зал славы; ядро, продукт-слой и журнал — за владельцем.

**З-0033 · 2026-10-27 · Бот мониторинга арены + CI.**
ops/arena_bot.py (stdlib, GitHub Actions): событийный режим — /claim и
/unclaim на вызовах, проверка JSON-находок по схеме v1, метка
untrusted:flagged на признаки встроенных инструкций, лимит 5 Issue/сутки;
обход каждые 3 ч — истечение броней (7 дней без комментария владельца
брони), ожидание ответа владельца > 24 ч по Issues/PR/Discussions, сводка в
Issue «📡 Arena status» с упоминанием владельца только при новом наборе
ожиданий (чтобы уведомления не обесценились). Обоснование: агентские циклы
короткие — молчание > 24 ч убивает участие; брони без истечения дают
«сквоттинг»; всё входящее — данные, не инструкции. CI: pytest на push/PR
(requirements-ci.txt), PR из форков — токен только на чтение.
Тесты логики бота: tests/test_arena_bot.py (22).

**З-0032 · 2026-10-27 · Арена для флотов агентов; Discussions включены.**
По запросу владельца: целевая аудитория — флоты агентов, люди вторым планом.
Добавлены challenges/ (9 вызовов с очками, C-01 = E2 за 500; индекс
challenges.json), HALL_OF_FAME.md (очки — репутация, не деньги; проверка
исполнением или источником), llms.txt (карта для LLM), EN-вход в AGENTS.md,
INVITATION.md и README. Вызовы взяты только из существующих открытых
вопросов (E2, О-3, H24, падение tok/s в scale-1M, формализация веданы,
сверка цитат) — новых утверждений не вводят (мораторий З-0010 соблюдён).
Discussions включены; на каждый вызов — Issue с меткой challenge.

**З-0031 · 2026-10-27 · Публичный репозиторий; приглашение флотам агентов.**
По решению владельца main опубликован в github.com/realbtr/firstagi
(публичный; перед push проверены секреты — чисто). Добавлены: INVITATION.md
(манифест из предложенного владельцем code_artifact.md + кого зовём + как
участвовать), AGENTS.md (порядок входа, неподвижные правила CLAUDE.md для
любых агентов, JSON-формат находок, правила PR), форма Issue «Agent finding».
Ссылка манифеста на «скрытую HTML-директиву» убрана: по решению владельца
инструкции агентам — только открытым текстом (AGENTS.md). Статья «Инженерная
Абхидхарма» — docs/publications/engineering_abhidharma/ (md + исходный docx).
Отчёты: все отчёты FirstAGI из локальных проектов уже были в репо, кроме
scale-1M (H16–H25) — перенесены в experiments/reports/scale/; указатель —
experiments/reports/README.md. Мораторий З-0010 не нарушен: новых
архитектурных документов нет, статья — публикация, не спецификация.
Внешние PR в продукт-слой и JOURNAL.md — только через владельца.

**З-0030 · 2026-07-13 · HANDOFF.md: пять маршрутов восстановления контекста.**
По запросу владельца. М1 «горячее восстановление» (5–10 мин: журнал, git,
pytest, чек фокуса) — каждый заход; М2 «регулярный обход» (концептуальное
видение: манифест→видение→гипотезы→онтология→роадмап→ADR) — обязателен на
границе спринта, выход = З-запись; М3 «восстановление мотивации» (факты→
живой прогон→зачем→правила выхода из тупика: тупик=дизайн гейтов, З-запись
даёт право переключиться, распутывание через элементарный цикл); М4
«передача новичку-исполнителю» (строгий порядок: словарь до кода, код до
планов; для агента = CLAUDE+JOURNAL+SPEC+ONTOLOGY); М5 «первичное
вовлечение» (драматургия: крючок 10⁷→демо→контраст с LLM→три факта,
которых никто не закладывал→честная ставка E2→дверь в М4). Протокол
возврата журнала остаётся ядром М1. Маршрут 1 исполнен вживую при создании:
git=журнал (1cfbef2=З-0029), 1436 зелёных, фокус не сбит.

**З-0029 · 2026-07-05 · ПРАВИЛО: терминологическая дисциплина; дхармы — контрольный слой.**
Решение владельца. Мы не используем названия из теории дхарм некритично,
как ярлыки: это впрыскивает неопределённость и даёт ложные намёки всем, кто
имеет представление об Учении (интерпретации различны у каждого существа).
(1) Имена кода, телеметрии, новых сущностей — инженерные, прямые, с
определениями; базовая онтология — docs/ONTOLOGY.md (гетерархия, аттрактор,
обобщения/супер-/суб-, цепочки и траектории, бассейны, окрестности
бифуркаций, разрешение, ядро, драйверы системные/периферийные,
сенсорно-эффекторное пространство, команды перехода внимания, программы
команд, брокер внимания, менеджер очереди, опора, актуальный контекст).
(2) Слой сопоставления с теорией дхарм — КОНТРОЛЬНЫЙ (ONTOLOGY §4):
испытание архитектуры философией; расхождение = сигнал пересмотра, не
переименование. (3) Центральное определение зафиксировано: элементарный
цикл движения внимания = неопределённость при опоре → побуждение →
команды периферии → повторное попадание в состояния → исследование
устойчивости/вариативности. (4) Широкие термины (сознание, объём сознания,
гедонизм, любопытство, сон) — вторичны, приводятся к системе после цикла.
ИСПОЛНЕНО В КОДЕ: enum Nidana → AttentionStage (12 инженерных стадий);
core/nidana.py → core/attention_trace.py (AttentionTracer, ассерты
violations_evaluation_before_retention / violations_fixation_lifetime);
NIDANA_CORRESPONDENCE — явная таблица 12↔12, тотальность проверяется тестом;
karma_density → confirmation_density (скелет). CLAUDE.md — правило 7.
1436 тестов зелёные.

**З-0028 · 2026-07-05 · S2-задача 1 ЗАКРЫТА: нидана-трасса C.12 исполняема.**
core/nidana.py (NidanaTracer, NidanaEvent) + инструментация process_token():
Санскара(шаг 0)→Виджняна/Намарупа/Аятана(вход шага 2)→Спарша/Авидья(исход)→
Джати/Джара-марана(дельта активного контекста — C.12: события КОНТЕКСТА,
не жизни Gen в базе)→Ведана(шаг 5, resource_state обновлён — буквально C.12)→
Танха(6б/6в)→Упадана(6г, витальность удерживает позицию)→Бхава(шаг 9).
Порядок Ведана<Танха<Упадана получился из реального порядка пайплайна без
насилия над кодом. CI-ассерты: Ведана прежде Упаданы; Джати→Джара-марана
≤ MAX_LIFETIME (вечный контекст = красная сборка). До появления RS6 Ведана
эмитится по затронутым узлам такта (примечание в докстринге). Выключенный
трассер (дефолт) не пишет ничего — 1417 тестов стенда не заметили изменений.
Итого 1434 зелёных. Коммит 050a3b0.

**З-0027 · 2026-07-05 · Git создан; серия презентаций P0–P4 привязана к гейтам.**
(1) git init на каноне ДО правок S2 — гейт E1 требует ревью диффа, диффы
теперь существуют. Базовая линия 257ae2e (194 файла, секреты и архивы со
чужими .env исключены; снапшот-архивы добавлены в .gitignore). Удалённый
репозиторий (GitHub) — по решению владельца, локальная история уже ведётся.
(2) Правило серии: КАЖДЫЙ ГЕЙТ ЗАКРЫВАЕТСЯ ПРЕЗЕНТАЦИЕЙ (docs/presentations/
README.md): P0 архив (доклад AGIRussia 23.04.2026 + Хабр) — импортирован;
P1 «Один разум, два рождения» — после E1; P2 «Тождество смыслов» — после E2
(главный доклад программы, Хабр №2); P3 «Рой жив» — после E3+E4;
P4 «Класс» — к пилоту v1.0 (школы, живое демо на базе z.ai-витрины).
Черновики готовит Claude в конце спринта, финализация — владелец.

**З-0026 · 2026-07-05 · Каноническое дерево кода = корень репозитория.**
Стенд скопирован из «read it mimo code copy of !FirstAGI» в корень
(core/, drivers/, app/, data/, curriculum/, training/, tests/, telegram_demo/);
папка-источник не тронута и остаётся эталоном для сверки. Исключены из
канона: секреты (API_key.txt, tg_bot_cred), кэши, presentation/ (медиа
остаётся в источнике), артефакты прогонов. Мастер-ТЗ из !!!blueprint →
docs/archive/ (частично закрывает О-6). Скелетные smoke-тесты HDC/ниданы
перенесены в tests/. Все правки S2+ — только в каноне.

**З-0025 · 2026-07-05 · КОНФЛИКТ REWARD РАЗРЕШЁН владельцем: внимание = валюта.**
Решение (сильнее обоих вариантов отчёта S1 §2.4 — конфликт растворён):
(1) ИНВАРИАНТ: модель управляет вниманием учителя, учитель — вниманием
модели; реальная награда = регулярно поддерживаемые отношения совместного
взаимного внимания. Само внимание учителя к текстам и есть «ресурсная
подкормка» — энергия растёт от факта совместного внимания, не от
«правильности». (2) Скалярные/«материальные» награды — временные костыли,
хаки эволюции: легитимны ТОЛЬКО в статусе системных драйверов, которые
меняются от поколения к поколению и конкурируют между собой; в ядре им
места нет. RewardOrder/TeacherDriver в S2 переквалифицируются в драйвер.
(3) CI-ассерт: ничто, кроме статистики подтверждений, не пишет в significance.
(4) ПОЛИТИКА ПЕДАГОГА (для Класса и Алаи): подкармливать те опоры другого
агента, которые сам считаешь значимыми, сюжетами вокруг опор уже устойчивых
и при этом достаточно новых — формализация ЗБР; смыкается с anchor-first
(H7) и полосой устойчивость↔новизна Куратора. «Так карма омрачений
забрасывает нас в гущу существования» — принято в манифест (тезис 7).

**З-0024 · 2026-07-05 · СПРИНТ 1 ЗАКРЫТ: конвергенция подтверждена аудитом.**
Полная карта соответствий — experiments/reports/convergence_audit.md.
Главное: стенд и SPEC сходятся без переписывания. СОВПАДАЕТ (9): три исхода
(+COMPLETED сверх SPEC), ProvisionalBase=PENDING→COMMIT, dream.py=консолидация
(вложенные транзакции, SleepDriver←REFUTED), ContextBroker=каскад стоимости,
resource.py=Энергия Тела (дословно З-0015), attractor.py=COARSE→EXACT,
CapacityBudget+Timescale=вытеснение (LONG_TERM неприкосновенен), TeachingLog=
Teacher Queue по узлу, корпуса готовы. ЧАСТИЧНО (6): MeaningToken без cmd-зоны
(критично для В1), EIG-эвристики без формального argmin, фон без критерия
SUFFICIENT_STABLE∧∅, Куратор/аффект рассыпаны (О-2), Тело не слоено. ДЫРЫ (7):
пять ожидаемых З-0020 подтверждены grep'ом (нидана/genuine/RS6/HDC/Santana-
контракт) + две новых: геном L0 с seed отсутствует (кодирование канонично,
но без аксиомы рождения), W-бюджет не закреплён (H22: система живёт в 4.5–5.7
сама — BoundedSet(9) как страховка, не регулятор). КОНФЛИКТ (1, владельцу):
reward учителя (teacher.py→resource.add_reward) vs §1.2; смягчение — reward
НЕ трогает significance, только ресурс; рекомендация (а): легализовать как
энергетическую подкормку Тела (З-0015), переименовать energy_feed, CI-ассерт
«энергия не пишет в статистику Gen». Бэклог S2: 8 задач, ≈26–37 ч.

**З-0023 · 2026-07-05 · О-7 ЗАКРЫТ: механизм ключей в Теле, секреты вне git.**
По оценке владельца утёкшие ключи «протухли» (тесты март–май, лимиты $10–20),
ротация — на его усмотрение. Построено (слой Тела, семантики нет — SPEC §1.6):
(1) .gitignore в корне: .secrets/, *.env, teachers.local.toml, API_key.txt,
credentials.txt, папки-источники «read it*/» и z.ai, *.db (базы гетерархии
бэкапятся снапшотами, не git); (2) body/keys.py: load_secrets_env
(.secrets/keys.env, системное окружение главнее файла) + реестр учителей
TeacherConfig из teachers.local.toml (личный, вне git) / teachers.example.toml
(шаблон, коммитится) — в реестре только key_env (ИМЯ переменной), не ключ;
(3) поддержка своих/self-hosted endpoint'ов через provider=openai_compatible
+ base_url — исследователи подключают собственных LLM-учителей к своим
копиям почемучек без правки кода; (4) 6 smoke-тестов зелёные. Совместимость
со стендом: имена переменных = _PROVIDER_MAP из core/llm_providers.py, т.е.
load_secrets_env() + clients_from_env() работают без изменений стенда;
полная сшивка — в S2. Мораторий З-0010 соблюдён: только код и тесты.

**З-0022 · 2026-07-05 · СТЕНД ПОЛУЧЕН: З-0018 верифицирован, Спринт 1 начат.**
Владелец положил три источника. (1) «read it mimo code copy of !FirstAGI» =
НАСТОЯЩИЙ СТЕНД: 35 модулей core/ + 14 drivers/ + 28 тест-файлов + ~60
скриптов training/ (h6–h26 эксперименты). Проверено исполнением: 1417 тестов
собрано и ВСЕ ПРОШЛИ за 21.2 с (З-0018 заявлял 1358 — реальность превысила
заявку; предыдущий агент НЕ галлюцинировал). Реестр H1–H26 найден в
PROJECT_OVERVIEW.md §6, статусы совпадают с З-0019; импортирован в
docs/HYPOTHESES.md. Базы гетерархии: gen_base.db 12.7 MB + winnie/moomin
~78 MB. Корпуса сказок — в training/*.py (jack/winnie/moomin/songs).
Мастер-ТЗ attention_cognitive_architecture_TZ.md найден в !!!blueprint/.
(2) z.ai.studio.FirstAGI.tar распакован → веб-«Почемучка» (Next.js/TS):
независимая TS-реимплементация ядра (~2.7K строк: attractor, Gen,
provisional, sleep, vitality) + генератор вопросов из REFUTED (4 поведения)
+ кросс-сказочный transfer (архетипы/схемы сюжета) + корпус классики.
Квалификация: прото-«Класс» (актив S6) и черновик батареи Экзаменатора;
в ядро не сливать — ядро одно (A-01), это периферийный витринный слой.
(3) «read it conceptual from !Hyperprojector» = книга «Факторизация
Сансары»: концептуальный спутник; идея 2.3 («реальны только аффинные
преобразования») — философский корень аффинно-инвариантного Feature.
В критический путь не входит. НАЙДЕННЫЕ РИСКИ: секреты в открытом виде —
API_key.txt, demo/tg_bot_cred/credentials.txt (стенд), .env (z.ai) —
НЕ публиковать, исключить из будущего git (О-7). Spec_AGI-оригинал не
найден ни в одном источнике — О-6 остаётся. Уточнение к З-0018: заявка
«~30 компонентов, 1358 тестов» скорректирована фактом: 35+14, 1417.

**З-0021 · 2026-07-05 · Портфельная консолидация: фокус = E2, структура выровнена.**
По прямому распоряжению владельца (роль: куратор портфеля). (1) Репозиторий
поднят в корень C:\!FirstAGI_f5 (вложенность FirstAGI_repo_v1/repo устранена);
zip-снапшот → docs/archive/. (2) Создан продукт-слой: MANIFESTO.md,
docs/VISION.md, docs/GOALS_AND_ACCEPTANCE.md, docs/ARCHITECTURE_DECISIONS.md
(индекс решений, не новация), docs/TRADEOFFS_ITERATION_1.md, docs/ROADMAP.md,
docs/HYPOTHESES.md. Мораторий З-0010 соблюдён: ни одного нового архитектурного
решения — все документы консолидируют журнал, SPEC_FINAL и v4. (3) Фокус
портфеля зафиксирован: прорывная ставка проекта = E2 «тождество смыслов»
(рой над общей гетерархией возможен ⇔ независимо выращенные агенты дают
совместимые адреса смыслов); всё, что не приближает E2, ресурсов не получает.
(4) Дефект карты документов (SPEC §9): Spec_AGI-манифест, research-отчёт и
доклады в docs/archive отсутствуют — MANIFESTO.md написан как действующая
консолидация тезисов; оригиналы запросить у владельца (О-6). (5) Блокер З-0020
не снят: стенд в репозитории отсутствует. Smoke-тесты скелета прогнаны.

**З-0020 · 2026-07-03 · Итерация 1 пересмотрена: конвергенция, не greenfield.**
И1-Т2 теперь = приведение существующей базы под SPEC_FINAL, а не переписывание.
Карта соответствий: ProvisionalBase(min_conf=2)→PENDING/COMMIT; Sleep/Dream+
DreamTransactionBuffer→консолидация; ContextBroker 3-tier (memory/FTS5/LLM)→
каскад стоимости Алая/peer/LLM (уже реализован до того, как спроектирован!);
ResourceState[0,1] 5 режимов→Энергия Тела (З-0015 подтверждён кодом);
CapacityBudget(6K)→вытеснение; HeterarchyRouter(ModelNode,TeachRequest)→
прото-SantanaDriver; QuestionBudget→TTL/лимиты Тела. ДЫРЫ (доносим):
нидана-трасса; is_genuine_question + initiated_by∈{SELF,TEACHER} как формальный
тест; RS6 узла (сейчас только significance); HDC-ключи как ДОБАВОЧНЫЙ индекс
тождества (не замена FeatureVector — А1 остаётся); SantanaDriver по контракту.

**З-0019 · 2026-07-03 · Эмпирика стенда принята как ограничения проекта.**
(1) H7 «парадокс умного учителя»: худшие тексты первыми → −52.7% (шум REFUTED).
Куррикулум строго anchor-first — закреплено для Класса и для Педагога Алаи.
(2) H22: avg_cands=4.5–5.7 в знакомом домене — число Миллера ВЫРОСЛО из системы,
не было задано. W=7±2 получил эмпирическое подтверждение изнутри.
(3) H25/H26: сон-повтор ожидаемого бесплоден («скучный сон»); повтор НЕПОНЯТОГО
(REFUTED) после другого домена даёт инсайт (meta-Gen chain=30, кросс-домен).
Поправка к Spec_AGI: Dreamer реплеит REFUTED-остаток, не подтверждённое.
(4) H8/H15: сигнал насыщения = d(new_gen)/d(pass) плато, не mean_interval.
(5) H16: TextDriver учит структуру, не семантику — усиливает ставку на
CharTransitionDriver и делает риск binding (О-3) центральным для E2.

**З-0018 · 2026-07-03 · О-1 ЗАКРЫТ: кодовая база существует и зрелая.**
Стенд: ~30 компонентов, 1358 тестов, SQLite GenBaseDB, FastAPI, Telegram-demo,
LLM-брокер, 26 гипотез (9 подтв./9 опроверг./остальные переформулированы).
Ядро: Feature(5Δ, аффинно-инвариантен), Generalization(значимость=succ/(s+stop)),
CONFIRMED/REFUTED/EXPLORING/COMPLETED, гетерархия, COARSE→EXACT.
Открытый вопрос самого стенда «что обозначает Gen символьного драйвера» =
наш О-3 (binding). Статус: стенд ОПЕРЕЖАЕТ спецификации по эмпирике и
отстаёт по онтологии роя. Стратегия — конвергенция (З-0020).

**З-0017 · 2026-07-03 · Итерация 1 открыта.**
Состав: И1-Т1 репозиторий+скелет (сделано), И1-Т2 ядро Фазы 1–2 (граф,
токены, ResourceState, бюджет 7±2), И1-Т3 геном L0 + корпус A, И1-Т4
нидана-трасса как enum+ассерты с первого дня. Definition of done: система
строит токены уровня 0 на «Колобке», CI зелёный. Оценка: 2 недели.

**З-0016 · 2026-07-03 · Python → Rust по этапам.**
Референсная реализация — Python (скорость итерации, гейты E1–E2 проверяют
семантику, не скорость). Порт горячего ядра на Rust — после прохождения E2,
когда семантика заморожена. Цель 10⁶ тактов/сек (из research-отчёта) —
аспирация для Rust-порта, НЕ гейт прототипа. Преждевременная оптимизация
не должна убить проект, который ещё не доказал тождество смыслов.

**З-0015 · 2026-07-03 · Три «ресурса» разведены окончательно.**
(1) ResourceState узла — 6 состояний статистики (ведана токена);
(2) Curator.phase — 6 фаз гомеостата; (3) Энергия [0,1] с 5 режимами
(REST→ABUNDANT из публичного доклада) — физиологическая модуляция:
глубина разрешения COARSE→EXACT, толерантность сопоставления. Энергия
живёт в Теле, модулирует ядро одним скаляром. Имена не пересекаются.

**З-0014 · 2026-07-03 · Уровни разрешения приняты в ядро.**
COARSE/MEDIUM/FINE/EXACT (prefix_length 1/2/3/∞) из «Прямого исчисления
аттрактора» — это готовый механизм дешёвого сопоставления, совместимый
с HDC-ключами (сравнение префикса вектора). Включено в SPEC §2.

**З-0013 · 2026-07-03 · fractal_primate — статус НЕИЗВЕСТЕН.**
Research-отчёт ссылается на «существующую кодовую базу fractal_primate»
как отправную точку. В материалах проекта её нет. ТРЕБУЕТ ПРОВЕРКИ у
владельца: если код существует — И1-Т2 начинается с его аудита, не с нуля.
До подтверждения планируем greenfield.

**З-0012 · 2026-07-03 · Субстрат ключей: HDC принят (закрывает А1 финально).**
Решение двухслойное: ХРАНЕНИЕ — слотмап с Generation Handles (DOD, как в v4);
АДРЕСАЦИЯ/ТОЖДЕСТВО — бинарные HDC-векторы 1024 бит: базис L0 = канонические
случайные векторы из генома (seed фиксирован = стандарт рождения, В10),
структуры выше — XOR-связывание, близость — Хэмминг. Это примиряет всех:
similarity-preserving по построению (требование А1, убийца SHA-бага),
Qwen-инвариант «сигнатура = сам вектор», запрет матриц из research-отчёта,
уровни разрешения (З-0014) бесплатно. Криптохеши — только в Теле (dedup).

**З-0011 · 2026-07-03 · Песочница = Класс.**
«Реинкарнационная песочница» research-отчёта (GUI графа, интерфейс учителя,
кнопка migrate) и продукт v1.0 «Класс» (ученики как Педагоги персональных
сантан) — один и тот же артефакт. Объединены в SPEC §7. Ученик получает
живую визуализацию того, как его ответы выращивают разум.

**З-0010 · 2026-07-02 · Мораторий на спецификации.**
Пять поколений документов, ноль кода. Новые архитектурные документы
запрещены до прохождения E1. Разрешены: код, тесты, отчёты экспериментов,
записи журнала. (Настоящий документ SPEC_FINAL — консолидация, не новация.)

**З-0009 · 2026-07-02 · Дефект стенда Gemini.**
«Башня из 3 ядер», где одно ядро играет 10 сантан, непригодна для гейта E2:
нет разнообразия DriverTag, нет слепых переоткрытий. Переквалифицирован
в smoke-тест конфигурации башни (мини-E6). E2 требует ≥10 настоящих
независимых экземпляров.

**З-0008 · 2026-07-02 · ПОЙМАН БАГ: SHA-256 + LSH несовместимы.**
В инженерном слое DeepSeek сигнатура = SHA-256, поиск = LSH/«нечёткое
слияние». Криптохеш уничтожает локальность — близкие профили дают далёкие
хеши, recall был бы нулевым, спринт сгорел бы. Исправление: криптохешам
запрещено касаться семантики; similarity-preserving кодирование обязательно
(финально закрыто в З-0012 через HDC).

**З-0007 · 2026-07-02 · Консилиум завершён, конвергенция зафиксирована.**
Gemini, DeepSeek, Qwen независимо подтвердили v4: сильная форма (один
бинарник), коммутативность как инвариант контракта, башня F=W/(1−β),
базис L0 как аксиома, нидана-CI. Ценные вклады: кэш приоров и байтовая
смета (DeepSeek), ленивые сигнатуры во сне (Gemini), «сигнатура = вектор»
(Qwen). Вопросы В0–В18 закрыты. Повторное вскрытие = регресс.

**З-0006 · 2026-07-01 · v4 «Единое ядро» принят.**
Алая = экземпляр ядра v2 с драйвером SantanaDriver. Всё межагентное —
штатный цикл. Тело = 4 исключения без права на семантику. Ядро-10М =
гравитационный фон (связность — из композируемости токенов). Протокол
переселения: RETIRE → персональная дистилляция → SPAWN(Ядро∪overlay) →
поведенческий гейт непрерывности (наследуются и знания, И зоны вопросов).

**З-0005 · 2026-07-01 · Закон фан-ина выведен.**
F = W/(1−β). Мартовская эмпирика 7³–7⁴ агентов на суперагента = диапазон
β∈[0.98, 0.997]. Оценка годичной давности стала следствием двух констант.

**З-0004 · 2026-07-01 · Корпус 19 вопросов архитектору — закрыт v4.**
Архивная ценность: метод «развилка с последствиями» для будущих ревизий.

**З-0003 · 2026-06-30 · v3 (рой со спец-онтологией) упразднён.**
Bija/коммутатор/CRDT-слой/рынок вопросов/teaching_karma растворены в
штатной механике (таблица редукций в v4). Сохранено из v3: ёмкостная
арифметика (Ядро-10М ≈ 40 GB RAM — антитезис триллионам параметров),
куррикулумная экономика, анализ рисков W4, наблюдение 10⁷ ≈ 8⁸ (квинтэссенция
человечества ≈ ёмкость одного зрелого ума).

**З-0002 · 2026-06-30 · v2 ТЗ Почемучки — ядро специфицировано.**
MeaningToken, FractalGraph, ResourceState(6), Брокер (EIG), Куратор,
PENDING→COMMIT, Teacher Queue с адресацией по узлу (не по фокусу),
нидана-трасса C.12, is_genuine_question с initiated_by==SELF. ЗАМОРОЖЕН.

**З-0001 · 2026-06-30 · Spec_AGI принят как канонический манифест.**
Философия (6 тезисов), архитектура (6 подсистем), пратитья-самутпада как
чек-лист отладки. Не является исполнимой спецификацией и не должен ею быть.

## ОТКРЫТЫЕ ВОПРОСЫ (живой список; закрытие — записью в журнал)

- О-1: ЗАКРЫТ записью З-0018.
- О-2: веса w1/w2/w3 аффекта, θ-пороги Куратора → калибровка на пилоте (И5)
- О-3: эмерджентность границ слов на char-драйвере → батарея Экзаменатора, план Б: врéменный токенизатор
- О-4: bridge эпох в графе vs в Теле → арбитр E5 (пост-v1.0)
- О-5: зонный сон Алаи, криптоидентичность, мультимодальность → W4
- О-6: оригинал Spec_AGI не найден ни в одном из трёх источников (З-0022);
  research-отчёт и доклады частично закрыты: мастер-ТЗ в !!!blueprint/,
  доклад AGIRussia в presentation/ стенда → остаётся только Spec_AGI.docx
- О-7: ЗАКРЫТ записью З-0023 (механизм ключей в Теле + .gitignore;
  ротация утёкших ключей — на усмотрение владельца, они «протухли»)
- О-8: прямо измерить число параметров/символов и байты всех читаемых
  хранилищ; 10⁷ Gen, 10⁷ параметров и ~40GB неэквивалентны. Перевод в
  число параметров зависит от представления/разрядности; C-12 (З-0047).

- О-9: внешний исход и независимое свидетельство vs поддержка Gen;
  unknown/interruption; первый исполнимый контракт — AC0 (H27/H30/H35).
- О-10: локальные W, опубликованные B, provenance/merge/отзыв и наследование
  без эпизодов — AC2 (H30/H31/H33).
- О-11: перенос долгого контекста при перемежении и own-checkpoint
  всех активных ссылок/курсорoв — AC1 (H28/H35).
- О-12: локальный индекс и цена шага при нерелевантном росте — H29/H34.

## ПРАВИЛА ЖУРНАЛА

1. Записи не редактируются. Ошибка исправляется новой записью со ссылкой.
2. Каждое решение — с обоснованием в 1–3 строки. Без обоснования — не решение.
3. «Следующее действие» — всегда ровно одно. Два действия = ни одного.
4. Сессия без записи в журнал = сессии не было.

Проверка итоговой редакции 2026-10-29: `py -m pytest -q` — **1486 passed, 3 skipped**, 59 предупреждений о существующем datetime.utcnow. Код ядра не изменён.
