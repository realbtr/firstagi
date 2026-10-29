# FirstAGI — a continuously learning attention kernel

**Teach a skill. Interrupt it. Let a fresh mind inherit it.**
Can one shared attention algorithm become more competent in its channels,
retain that competence through interruption/restart, and transfer a checked
knowledge delta to a fresh instance? Help build and falsify this experiment.

**Status:** a working component testbed; the complete continual-action and
inheritance harness is not implemented. Read the [readiness audit](docs/RETROSPECTIVE_2026-10-29.md).
Current priority: **[C-15 / AC0–AC2](challenges/README.md)**; long-term
[North Star](NORTH_STAR.md): ≤10M parameters versus 200B+ reasoning quality
(unmeasured). No claim of AGI, enterprise service or achieved parity.

Мы строим постоянно действующее ядро управления вниманием, которое учится
в ходе взаимодействия, сохраняет гетерархию воспроизводимых обобщений и
становится умелее в своих каналах. Несколько экземпляров и общие редакции
знания — следующий проверяемый шаг, а не уже готовая возможность.

[Manifesto](MANIFESTO.md) · [Operational protocol](FIRSTAGI_OPERATIONAL_PROTOCOL.md)
· [Teaser for people, agents and labs](challenges/TEASER.md) · [Agent instructions](AGENTS.md)
· [Discussions](https://github.com/realbtr/firstagi/discussions) · [MIT](LICENSE).

## Карта репозитория

| Путь | Что это | Когда читать |
|---|---|---|
| `INVITATION.md` | Приглашение к C-15 и участию | впервые здесь |
| `AGENTS.md` | Протокол для внешних агентов: вход в контекст, правила, JSON-формат находок | агенту до первого Issue/PR |
| `docs/publications/` | Статья «Инженерная Абхидхарма» (md + исходный docx) | концептуальная база |
| `experiments/reports/` | Указатель всех отчётов (аудит конвергенции, scale-1M и др.) | после каждого эксперимента |
| `JOURNAL.md` | Журнал решений (append-only), текущее состояние, следующее действие | **Старт каждой сессии** |
| `HANDOFF.md` | 5 маршрутов восстановления контекста (горячий/обход/мотивация/передача/вовлечение) | потерялись? начните здесь |
| `SPEC_FINAL.md` | Действующий целевой контракт; реализацию смотреть в аудите | **Старт каждой сессии** |
| `FIRSTAGI_OPERATIONAL_PROTOCOL.md` | Следующий baseline, AC0–AC4; не готовый benchmark | перед реализацией |
| `docs/RETROSPECTIVE_2026-10-29.md` | Матрица готовности и пересмотр приоритетов | при выборе задачи |
| `docs/concept/` | Неизменённые сентябрьские конституции, хэши и границы источника | концептуальная проверка |
| `CLAUDE.md` | Правила для агентов | старт сессии агента |
| `MANIFESTO.md` | Манифест проекта (текущая редакция) | презентация проекта |
| `docs/VISION.md` | Концептуальное видение, где прорыв | презентация проекта |
| `docs/GOALS_AND_ACCEPTANCE.md` | Ближайшие AC0–AC4 и исторические E-гейты | планирование |
| `docs/ROADMAP.md` | Последовательность AC0→AC1→AC2; отложенные ветки | планирование |
| `docs/ONTOLOGY.md` | Базовая онтология терминов + контрольный слой дхарм | **перед любым именованием** |
| `docs/ARCHITECTURE_DECISIONS.md` | Индекс архитектурных решений (ADR) | перед изменением ядра |
| `docs/TRADEOFFS_ITERATION_1.md` | Компромиссы текущей итерации | перед изменением ядра |
| `docs/HYPOTHESES.md` | Реестр гипотез (подтверждено/опровергнуто/ожидает) | после каждого эксперимента |
| `docs/archive/` | История (v2, v3, v4, мастер-ТЗ, аудиты, снапшоты) | только по ссылке из журнала |
| `docs/stand/` | Самоописание стенда (обзор, введение, дневник char-драйвера) | справочно |
| `core/` `drivers/` | КАНОН кода (З-0026): ядро 35+ модулей, периферия 14 драйверов | — |
| `body/` | Тело: транспорт и доступ к учителям | — |
| `app/` `data/` `training/` | Оркестрация (FastAPI), персистентность (SQLite), эксперименты H1–H26 | — |
| `tests/` | 1400+ тестов — точное число по коммиту в CI | `python -m pytest -q` |
| `corpus/` `curriculum/` `experiments/` | Куррикулумы, агент-учитель, отчёты | — |

## Источники (получены 2026-07-05, З-0022)

| Папка | Что это | Статус |
|---|---|---|
| `read it mimo code copy of !FirstAGI/` | **СТЕНД** — рабочая кодовая база: 35 модулей core + 14 драйверов, 1417 тестов (все зелёные), эксперименты H1–H26, базы гетерархии ~90 MB, корпуса сказок | предмет конвергенции S1–S2 |
| `z.ai.studio.FirstAGI/` | Веб-«Почемучка» (Next.js/TS): независимая TS-реимплементация ядра + вопросы из REFUTED + кросс-сказочный transfer | прото-«Класс», актив S6 |
| `read it conceptual from !Hyperprojector/` | Книга «Факторизация Сансары» | концептуальный спутник, вне критического пути |

## Ключи LLM-учителей (З-0023)

Секреты в git не попадают (`.gitignore`). Каждый исследователь подключает
своих учителей к своим копиям почемучек так:
1. `.secrets/keys.env.example` → скопировать в `.secrets/keys.env`, вписать ключи;
2. `teachers.example.toml` → скопировать в `teachers.local.toml`, описать
   учителей (имя, провайдер, модель, `key_env` — имя переменной, не сам ключ;
   свой endpoint — через `provider = "openai_compatible"` + `base_url`);
3. проверить: `python body/keys.py` — покажет, у кого есть ключ.

Старые утёкшие файлы (`API_key.txt`, `tg_bot_cred/`, `.env` в источниках)
считаются протухшими и в git исключены; не публиковать.

## Состояние на 2026-07-05

S0 «Портфель» закрыт (З-0021). Стенд верифицирован исполнением (З-0022).
S1 «Аудит-конвергенция» **закрыт** (З-0024): карта соответствий в
`experiments/reports/convergence_audit.md` — сходимся без переписывания
(9 совпадений / 6 частичных / 7 дыр / 1 конфликт). Идёт S2 «Закрытие дыр».
**Владельцу на решение:** конфликт reward учителя vs «нет вознаграждения»
(отчёт §2.4; рекомендация — легализовать как энергию Тела).
