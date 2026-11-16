"""Explain engineering limits without claiming a validated hardware design.

Rules are intentionally traceable: each message has a diagnostic code, severity,
measured value/condition and a concrete next step. The same diagnostics are
available from the GUI and CLI; new rules can be added without changing the GUI.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from engine import Settings, Candidate, optimize, validate


@dataclass(frozen=True)
class Advice:
    level: str  # ERROR / WARNING / INFO
    code: str
    title: str
    detail: str
    action: str


def _a(level: str, code: str, title: str, detail: str, action: str) -> Advice:
    return Advice(level, code, title, detail, action)


def inspect_settings(s: Settings) -> list[Advice]:
    """Report invalid fields as actionable errors rather than a popup only."""
    try:
        validate(s)
    except (ValueError, TypeError) as exc:
        return [_a("ERROR", "INPUT", "Некорректные входные данные", str(exc),
                   "Исправьте параметр, затем повторите расчёт.")]
    result = []
    p_out = sum(abs(o.voltage_v) * o.current_a for o in s.outputs)
    if s.vin_max_v / s.vin_min_v >= 4:
        result.append(_a("WARNING", "VIN_RANGE", "Широкий диапазон входа",
            f"Vin_max/Vin_min = {s.vin_max_v/s.vin_min_v:.1f}.",
            "Проверьте DCM, пиковый ток и доступное минимальное время включения при Vin_max."))
    if s.current_density_a_mm2 > 5:
        result.append(_a("WARNING", "CURRENT_DENSITY", "Высокая плотность тока",
            f"Задано {s.current_density_a_mm2:.1f} А/мм².",
            "Уменьшите допустимую плотность или подтвердите тепловой режим измерениями."))
    if s.frequency_khz > 200:
        result.append(_a("WARNING", "HIGH_FREQUENCY", "Высокая частота",
            f"Частота {s.frequency_khz:.1f} кГц. DC-оценка меди занижает AC-потери.",
            "Проверьте потери феррита, скин-эффект, proximity и нагрев."))
    if len(s.outputs) > 12:
        result.append(_a("INFO", "MANY_WINDINGS", "Много вторичных обмоток",
            f"{len(s.outputs)} обмоток, {len(set(o.group for o in s.outputs))} групп.",
            "Проверьте слой за слоем размещение, изоляцию и перекрёстное регулирование всех нагрузок."))
    if any(abs(o.voltage_v) <= 3 for o in s.outputs):
        result.append(_a("INFO", "LOW_VOLTAGE", "Низковольтные выходы",
            "Есть обмотки с |U| ≤ 3 В; ошибка даже одного витка может быть значительной.",
            "Увеличьте вторичное число витков или проверьте допустимую ошибку напряжения."))
    if s.core.name in {"ETD29", "ETD34", "ETD39", "ETD44", "ETD49", "E-Sh5x5"}:
        result.append(_a("INFO", "CORE_DATA", "Каталожные размеры приблизительные",
            f"Для {s.core.name} Ae, окно, MLT и μr зависят от конкретного изделия и каркаса.",
            "Сверьте данные по чертежу производителя или введите свои значения вручную."))
    result.append(_a("INFO", "MODEL_SCOPE", "Ограничения модели DCM",
        "Потери сердечника/AC-меди, трансформаторная изоляция, нагрев, EMI и перекрёстное регулирование не рассчитаны.",
        "Не используйте расчёт как окончательное разрешение на изготовление высоковольтного устройства."))
    if p_out <= 0:
        result.append(_a("ERROR", "POWER", "Отсутствует нагрузка", "Pout=0.",
            "Введите реальные токи вторичных выходов."))
    return result


def inspect_candidate(s: Settings, c: Candidate) -> list[Advice]:
    """Evaluate the supplied candidate against chosen *design* limits."""
    notes = []
    high_error = sorted((w for w in c.windings if abs(w.error_percent) > 5),
                        key=lambda w: -abs(w.error_percent))
    if high_error:
        sample = "; ".join(f"{w.name}: {w.error_percent:+.1f}%" for w in high_error[:4])
        notes.append(_a("WARNING", "VOUT_ERROR", "Ошибка вторичных напряжений >5%",
            sample + (f"; ещё {len(high_error)-4}" if len(high_error) > 4 else ""),
            "Увеличьте число витков опорной обмотки, измените целевое отражённое напряжение "
            "или используйте локальные стабилизаторы; проверьте нагрузочные комбинации."))
    if c.used_window_fraction >= 0.9 * s.window_utilization:
        notes.append(_a("WARNING", "WINDOW_NEAR_LIMIT", "Почти заполнено окно",
            f"{c.used_window_fraction:.1%} при лимите {s.window_utilization:.1%}.",
            "Рассмотрите больший каркас, тонкий провод в несколько жил или другую укладку; "
            "фактическая геометрия изоляции здесь ещё не учтена."))
    if c.bpk_t >= 0.9 * s.max_b_t:
        notes.append(_a("WARNING", "FLUX_NEAR_LIMIT", "Индукция близка к заданному пределу",
            f"Bpk={c.bpk_t*1000:.1f} мТл при лимите {s.max_b_t*1000:.1f} мТл.",
            "Проверьте Bsat(T) и потери феррита; при необходимости увеличьте Ae или витки."))
    if c.idle_fraction < s.min_demag_margin + 0.03:
        notes.append(_a("WARNING", "DEMAG_MARGIN", "Мал запас размагничивания",
            f"Доступный свободный период {c.idle_fraction:.3f}.",
            "Проверьте режим на Vin_min и максимальной нагрузке; уменьшите D или измените Vref."))
    if c.copper_losses_w > 0.12 * c.total_power_w:
        notes.append(_a("WARNING", "COPPER_LOSS", "Высокая оценка потерь меди",
            f"Потери по DC={c.copper_losses_w:.2f} Вт, Pout={c.total_power_w:.2f} Вт.",
            "Выберите больший сердечник или увеличьте сечение проводников; AC-потери ещё выше."))
    if c.total_gap_mm >= 0.9 * s.gap_max_mm:
        notes.append(_a("INFO", "GAP_NEAR_LIMIT", "Зазор близок к верхней границе",
            f"Полный зазор ≈{c.total_gap_mm:.3f} мм.",
            "Измерьте AL после сборки; учтите краевые поля зазора и локальный нагрев меди."))
    notes.append(_a("INFO", "MOSFET_VDS", "Напряжение силового ключа без выбросов",
        f"Vin_max + Vref ≈ {c.mosfet_vds_ideal_v:.1f} В (без выброса от Lрассеяния).",
        "Проверяйте запас Vds по реальной осциллограмме и схеме клампера, а не по этой сумме."))
    return notes


def no_solution_advice(s: Settings) -> list[Advice]:
    """Use bounded, one-at-a-time relaxed searches to locate blocking constraints.

    A relaxed search is *diagnostic*, never approval to exceed a real design limit.
    """
    proposals = [
        ("WINDOW", "Недостаточно места для обмоток",
         {"window_utilization": min(0.85, max(0.85, s.window_utilization))},
         "Возьмите сердечник/каркас с большим окном или пересмотрите провода и изоляцию. "
         "Не объявляйте заполнение 85% допустимым без проверки."),
        ("FLUX", "Лимит магнитной индукции",
         {"max_b_t": 0.44},
         "Используйте больший Ae, больше первичных витков или другой материал. "
         "Не превышайте Bsat(T) и допустимые потери феррита."),
        ("GAP", "Ограничение зазора",
         {"gap_max_mm": 9.0},
         "Пересмотрите сердечник, первичные витки и измеряемую величину AL."),
        ("DEMAG", "Недостаточный интервал размагничивания",
         {"min_demag_margin": 0.025},
         "Уменьшите D, пересмотрите Vref или смените режим работы."),
        ("WIRE", "Не подбирается провод по ограничению J",
         {"current_density_a_mm2": 14.0},
         "Нужен провод большего сечения или несколько жил; не повышайте J без оценки нагрева."),
    ]
    result = []
    for code, title, changes, action in proposals:
        if any(getattr(s, k) >= v for k, v in changes.items()):
            continue
        probe = replace(s, **changes)
        try:
            if optimize(probe, top=1):
                result.append(_a("WARNING", "BLOCK_" + code, title,
                    "Если временно ослабить только это ограничение, расчётный вариант находится.",
                    action))
        except ValueError:
            pass
    if not result:
        result.append(_a("WARNING", "NO_CANDIDATE", "Подходящих вариантов не найдено",
            "Не удалось выделить одну причину по тестовому ослаблению ограничений.",
            "Проверьте Vin_min, нагрузку, частоту, размер сердечника, диапазон Np "
            "и Vref; попробуйте сравнение сердечников."))
    return result


def inspect_design(s: Settings, candidates: list[Candidate] | None = None) -> list[Advice]:
    notes = inspect_settings(s)
    if any(item.level == "ERROR" for item in notes):
        return notes
    if candidates is not None:
        if candidates:
            notes.extend(inspect_candidate(s, candidates[0]))
        else:
            notes.extend(no_solution_advice(s))
    return notes


def advice_report(items: Iterable[Advice]) -> str:
    chunks = ["ДИАГНОСТИКА И РЕКОМЕНДАЦИИ", "=" * 72]
    for i, a in enumerate(items, 1):
        chunks.append(f"{i}. [{a.level}] {a.title} ({a.code})\n"
                      f"   Причина: {a.detail}\n"
                      f"   Рекомендация: {a.action}\n")
    return "\n".join(chunks)
