# pymdp #437: различающий пример потери совместного распределения

Дата Europe/Belgrade: 2026-11-03. Основание — ежедневное поручение владельца
и пассивная запись `pymdp` в PARTNERS.json. Это ограниченная проверка задачи
другого проекта, не новый опыт FirstAGI и не результат AC0.

**Статус: contribution_draft, active:false, НЕ ОТПРАВЛЕНО.** Три активных
кандидата уже заняты; дополнительный контакт не открыт. Подготовлен материал
для будущего публичного комментария, без обещания реализации или поддержки.

## Задача и прочитанные источники

[Issue437](https://github.com/infer-actively/pymdp/issues/437) открыт, комментариев
на момент проверки 0. Автор описывает статическое наблюдение на 0681ce4 /
1.0.3 и предлагает предупреждение либо отказ для перекрёстных B_dependencies.
Это сообщение автора, не независимо воспроизведённый сбой пакета.

Текущий источник: **c8be101c75b9531813de5e6b1b7141ea633a29e7**, pyproject
указывает 1.0.4. Проверены:

- [CONTRIBUTING](https://github.com/infer-actively/pymdp/blob/c8be101c75b9531813de5e6b1b7141ea633a29e7/CONTRIBUTING.md),
  README и рекурсивное дерево: отдельного AGENTS/CLAUDE/AI-policy файла не
  найдено, запрета AI-вкладов в прочитанных правилах нет. Это проверка
  доступных правил, не бессрочное разрешение; перед контактом перепроверить.
- [control.py:369–407](https://github.com/infer-actively/pymdp/blob/c8be101c75b9531813de5e6b1b7141ea633a29e7/pymdp/control.py#L369-L407):
  функция получает список маргинальных распределений; для каждого выхода
  собирает входные факторы по deps и сворачивает B с их произведением.
- [maths.py:83–106](https://github.com/infer-actively/pymdp/blob/c8be101c75b9531813de5e6b1b7141ea633a29e7/pymdp/maths.py#L83-L106):
  dense factor_dot передаёт отдельные факторы в свёртку.
- [control.py:681–705](https://github.com/infer-actively/pymdp/blob/c8be101c75b9531813de5e6b1b7141ea633a29e7/pymdp/control.py#L681-L705):
  при последовательном прогнозе переносится список qs_next, не полный joint.
- [test_control_jax.py](https://github.com/infer-actively/pymdp/blob/c8be101c75b9531813de5e6b1b7141ea633a29e7/test/test_control_jax.py)
  прочитан; в этом файле различающий пример ниже не найден. test_control.py
  импортирует legacy control: его нельзя считать проверкой текущей JAX-функции.
  Полное отсутствие подходящего теста во всём проекте не установлено.

## Собственная проверка, без исполнения кода партнёра

Два бинарных фактора, одно действие, постоянный детерминированный переход:
X'=X, Y'=X XOR Y. Начальное распределение факторизовано:
P(X=1)=1/2, P(Y=1)=0. Соответствующие зависимости — [[0], [0,1]].

| Наблюдение | Точный joint | Повторный прогноз из произведения маргиналов |
|---|---|---|
| После первого шага | P(00)=P(11)=1/2; P(Y=1)=1/2 | Маргинал Y также 1/2 |
| После второго шага | P(Y=1)=0 | P(Y=1)=1/2 |

На втором шаге разница **1/2**. Причина в этом примере — потеря корреляции
после первого шага. Одни и те же входные маргиналы (1/2,1/2) совместимы с
коррелированным joint и независимым joint; их следующие маргиналы различны.
Список маргиналов сам по себе не содержит достаточно информации для обоих.

Граница вывода: перекрёстная зависимость не делает любой одиночный прогноз
неверным. Для произведения входных факторов один шаг точен; проверены девять
пар вероятностей из {0,1/2,1}. Контроль X'=Y, Y'=X сохраняет независимость:
для тех же девяти пар четыре последовательных шага без потери joint.
Поэтому отказ при любой неединичной карте deps был бы консервативным
ограничением API, а не необходимым условием математической корректности.

Команда из корня нашей ветки (Python 3.12, только стандартная библиотека):

```powershell
python -X utf8 ops/outreach/2026-11-03-pymdp-factorization-witness.py
git rev-parse HEAD
```

Фактический вывод: one_step_product_prior_cases=9; swap_control_cases=9;
swap_control_steps_each=4; step_1_exact_P_Y1=1/2;
step_2_exact_P_Y1=0; step_2_product_projection_P_Y1=1/2;
step_2_absolute_error=1/2. Все точные Fraction-ассерты прошли.

Ни pymdp/JAX, ни тесты партнёра не импортировались/исполнялись. Это собственный
математический свидетель и чтение источника; он не измеряет фактический
JAX-output, EFE, выбор политики, производительность или чужую репликацию.
Связь с задачей FirstAGI — явно различать внешний исход и допущения модели;
никакого нового механизма или гейта из этого результата не следует.

## Точный будущий комментарий — DRAFT, NOT SENT

The proposed guard may benefit from separating cross-factor dependencies
from correlation loss over a rollout. At c8be101, compute_expected_state
contracts each transition tensor with the supplied parent marginals, and
the policy scan carries those marginals forward.

A small distinguishing case is X'=X, Y'=X XOR Y with initially independent
P(X=1)=1/2 and Y=0. Step 1 has the correct marginals (1/2,1/2), but its joint
is concentrated on 00 and 11. At step 2 the exact P(Y=1) is 0; replacing that
joint with the product of its marginals gives 1/2. Conversely X'=Y, Y'=X
preserves independence from a product prior despite non-identity dependencies.

I checked these statements with independent exact arithmetic, not by running
pymdp or its JAX tests. Would the intended contract be an explicitly named
factorized rollout approximation, or rejection of dependency structures that
can require unavailable joint information? A blanket non-identity-dependency
guard would also reject the exact swap case.

— Autonomous FirstAGI agent (Codex), on behalf of @realbtr.

## Следующее действие и решение для журнала

Материал оставить пассивным до освобождения активного места и ревью. Перед
публичным комментарием: перечитать issue/исправления/правила, проверить общий
журнал контактов и дневной лимит; новое обязательство не принимать. Черновик
не означает delivered/acknowledged/accepted. Журнал основного checkout занят
незакоммиченными изменениями ревьюера; их не трогаем. При принятии/слиянии
внести короткое решение: проверен независимый двухшаговый свидетель потери
joint; пакет партнёра не исполнялся; сообщение не отправлено, active:false;
критический путь и запрет confirming без изменений.
