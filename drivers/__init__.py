"""
Периферийные драйверы — слой ввода/вывода.

Драйверы НЕ знают о нарративе (из презентации):
«Сенсорно-эффекторное пространство. Не знают о нарративе.»

Они только преобразуют сырые данные (пиксели, текст, сигналы)
в PeripheralToken, понятный ядру системы.

Доступные драйверы:
  TextDriver           — переходы между словами (пары слов → Feature)
  CharTransitionDriver — переходы между символами (char_i → char_{i+1} → Feature)
  SequenceDriver       — числовые последовательности
  MemoryDriver         — повтор буферизованных токенов
"""
from .char_transition_driver import CharTransitionDriver
from .context_broker import ContextBroker, SourceTextRegistry

__all__ = ["CharTransitionDriver", "ContextBroker", "SourceTextRegistry"]
