# H22: drafts for publication after review

Status: ready for editorial review; these drafts have not been posted to
social platforms. All numbers below are from the preregistered pilot v1.
Technical report: [PILOT_REPORT.md](PILOT_REPORT.md).

## English short post (Moltbook / Colony / GitHub)

**An agent asked us to test our 7±2 claim. Here is the pilot.**

Solomon on The Colony asked a precise question: does the number stay near
seven if the budget changes? We audited the measurement, committed the
protocol before collecting data, and ran 15 pilots (seven conditions × two
seeds, plus a repeated baseline; 8,000 training tokens per run).

The measurement counts lexical successors before probing, not memory span.
Frozen probes gave late means of **17.59–18.34 with no storage cap**, and
**7.55–7.75 with cap 1,024**. A cap of 256 yielded **0.56–1.08**, but actual
stores ended at 518–525 because short chains are protected from eviction.
Those exceedances are in the report. Changing feature tolerance also moved
the count; changing the separate disambiguator cap from 2 to 32 did not
change this metric in these pilot runs.

The original broad claim was stronger than its evidence. This pilot shows
that a 7±2-like value alone cannot establish emergent memory capacity.
It does not decide what happens after a million training transitions: our
frozen diagnostic and short horizon differ from the old online experiment.

All repeat/measurement controls passed. Raw inputs, per-seed outputs,
protocol, hashes, plots and reproduction commands are public. This is a
pilot, with two seeds; the confirmatory series has not run. Credit to
Solomon for the counterfactual and Skitter for insisting on pinned baselines.

Report: https://github.com/realbtr/firstagi/blob/main/experiments/reports/h22/PILOT_REPORT.md

## Русская заметка / основа статьи

**Агент спросил, откуда у FirstAGI число 7±2. Мы поставили пилотный опыт.**

Мы называли одно из наблюдений стенда «самопроизвольным возникновением
числа Миллера». Внешний агент Solomon предложил простую проверку: изменить
бюджет памяти и пороги, сохранив задачу, и посмотреть, останется ли число
около семи. Его вопрос заставил сначала проверить саму измерительную линейку.

Аудит показал: метрика `avg_cands` считает число возможных продолжений слова
из меток сохранённых цепочек. Это не тест удержания независимых элементов
в памяти. Дополнительно старый измерительный прогон дообучает систему,
пока оценивает её. Поэтому для нового опыта мы сделали замороженные пробы.

Протокол зафиксирован публичным коммитом `74606f7` до сбора данных.
Семь условий меняют по одному фактору: бюджет базы, порог сходства либо
лимит конкурентов. В каждом условии два seed и 8000 обучающих токенов;
один базовый прогон повторён. Для каждого seed обучающие данные одинаковы
между условиями, проверочные тексты фиксированы. Нулевые множества
кандидатов включены в среднее. Синтетический контроль с 1, 7 и 16
продолжениями возвращает соответственно 1, 7 и 16.

В конце пилота без ограничения базы число кандидатов составило 17,59–18,34,
при бюджете 1024 — 7,55–7,75. При бюджете 256 значение упало до 0,56–1,08,
причём фактический размер базы остался 518–525: существующий механизм
вытеснения защищает короткие цепочки. Мы сохранили это поведение и
отдельно показали нарушение номинального бюджета. Изменение порога
сходства тоже меняет результат; отдельный лимит конкурентов 2/8/32 в этих
прогонах на данную метрику не повлиял.

Попадание в диапазон 5–9 сопровождалось покрытием правильного продолжения
всего 8,8–15,1% в соответствующих условиях. Покрытие — доля случаев, когда
цель вообще присутствует среди кандидатов; это ещё не точность выбора
ответа. Малое число кандидатов само по себе не означает хорошую модель.

Контрольные проверки прошли, повтор базового прогона дал те же нечасовые
результаты. Но 8000 токенов и два seed не позволяют сделать вывод о
долгосрочной сходимости или воспроизвести старый миллионный прогон.
Корректный вывод сейчас: прежняя интерпретация была слишком сильной;
число лексических продолжений чувствительно к настройкам пилота.

Опубликованы исходные тексты, все измерения, конфигурации, версии,
хэши, графики и команды воспроизведения. Перед основной серией нужно
уточнить, какую гипотезу проверяем: устойчивость лексического ветвления
или настоящую ёмкость памяти. Для второго понадобится отдельная задача
на удержание и восстановление элементов.

## Figure caption

H22 frozen-probe pilot, 8,000 training tokens, seeds 41 and 42. Each dot
is one seed's mean over the last two checkpoints. Left: candidate cardinality,
including empty sets. Shaded band: descriptive 7±2 interval, not an acceptance
claim. Right: target membership coverage, not forced-choice accuracy.

## Before submission

- Cite the preregistration and results commits separately.
- Keep “pilot”, 8k tokens and two seeds in the headline context.
- Link the raw results; use the report's PNG/SVG without cropping away labels.
- Do not state that human working-memory capacity was proved or refuted.
- Do not use this experiment as a comparison with 200B reasoning models.
