"""Generic, preliminary single-section bobbin winding-layer geometry.

This checks axial packing and estimated radial build only. It does NOT prove
insulation, creepage, clearance, dielectric strength or safe manufacturing.
All bobbin dimensions and dielectric allowances must be user supplied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math


@dataclass(frozen=True)
class Bobbin:
    name: str = "User-defined bobbin"
    winding_width_mm: float = 30.0
    mean_turn_length_mm: float = 70.0
    available_radial_mm: float | None = None


@dataclass(frozen=True)
class Packing:
    end_margin_mm: float = 1.5
    enamel_allowance_mm: float = 0.04
    wire_pitch_factor: float = 1.05
    interlayer_tape_mm: float = 0.05
    interwinding_tape_mm: float = 0.07
    intergroup_tape_mm: float = 0.15
    base_wrap_mm: float = 0.07
    final_wrap_mm: float = 0.13
    radial_reserve_mm: float = 0.5


@dataclass(frozen=True)
class Winding:
    name: str
    group: str
    turns: int
    bare_wire_mm: float
    strands: int = 1


@dataclass(frozen=True)
class Layer:
    group: str
    winding: str
    index: int
    turns: int
    capacity_turns: int
    occupied_width_mm: float
    radial_start_mm: float
    radial_end_mm: float
    wire_length_m: float


@dataclass
class Layout:
    layers: list[Layer] = field(default_factory=list)
    active_width_mm: float = 0
    radial_used_mm: float = 0
    radial_available_mm: float | None = None
    fits: bool | None = None
    wire_length_m: float = 0
    warnings: list[str] = field(default_factory=list)


def from_candidate(candidate) -> list[Winding]:
    """Convert electric candidate into a winding stack in the same order."""
    winds = [Winding("PRIMARY", "PRIMARY",
                     candidate.primary_turns,
                     candidate.primary_wire_mm,
                     candidate.primary_strands)]
    winds.extend(Winding(w.name, w.group, w.turns, w.wire_mm, w.strands)
                 for w in candidate.windings)
    return winds


def calculate_layout(windings: list[Winding], bobbin: Bobbin,
                     packing: Packing = Packing()) -> Layout:
    """Pack one whole winding after another in a single axial bobbin section.

    Parallel strands are approximated as a rectangular bundle. Turns include
    neither lead routing nor non-uniform layer crossover geometry.
    """
    if not windings:
        raise ValueError("Требуется хотя бы одна обмотка")
    if not bobbin.name.strip():
        raise ValueError("Введите название каркаса")
    if not math.isfinite(bobbin.winding_width_mm) or bobbin.winding_width_mm <= 0:
        raise ValueError("Ширина каркаса должна быть положительной")
    if not math.isfinite(bobbin.mean_turn_length_mm) or bobbin.mean_turn_length_mm <= 0:
        raise ValueError("Средняя длина витка должна быть положительной")
    if bobbin.available_radial_mm is not None:
        if not math.isfinite(bobbin.available_radial_mm) or bobbin.available_radial_mm <= 0:
            raise ValueError("Доступная радиальная толщина должна быть > 0")
    for attr in ("end_margin_mm", "enamel_allowance_mm", "interlayer_tape_mm",
                 "interwinding_tape_mm", "intergroup_tape_mm", "base_wrap_mm",
                 "final_wrap_mm", "radial_reserve_mm"):
        value = getattr(packing, attr)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{attr} должен быть неотрицательным")
    if not math.isfinite(packing.wire_pitch_factor) or packing.wire_pitch_factor < 1:
        raise ValueError("Коэффициент шага провода должен быть >= 1")
    width = bobbin.winding_width_mm - 2 * packing.end_margin_mm
    if width <= 0:
        raise ValueError("Поля по краям занимают всю ширину намотки")
    result = Layout(active_width_mm=width, radial_available_mm=bobbin.available_radial_mm)
    radial = packing.base_wrap_mm
    previous = None
    for winding in windings:
        if not winding.name.strip() or not winding.group.strip():
            raise ValueError("Для каждой обмотки нужны название и группа")
        if (not isinstance(winding.turns, int) or winding.turns < 1 or
                not isinstance(winding.strands, int) or winding.strands < 1 or
                not math.isfinite(winding.bare_wire_mm) or winding.bare_wire_mm <= 0):
            raise ValueError(f"Некорректные данные обмотки {winding.name}")
        if previous is not None:
            radial += (packing.intergroup_tape_mm if previous.group != winding.group
                       else packing.interwinding_tape_mm)
        cols = math.ceil(math.sqrt(winding.strands))
        rows = math.ceil(winding.strands / cols)
        pitch = (winding.bare_wire_mm + packing.enamel_allowance_mm) * packing.wire_pitch_factor
        turn_pitch = cols * pitch
        turns_per_layer = math.floor((width + 1e-9) / turn_pitch)
        if turns_per_layer < 1:
            raise ValueError(f"{winding.name}: пучок {turn_pitch:.2f} мм шире "
                             f"доступного пространства {width:.2f} мм")
        n_layers = math.ceil(winding.turns / turns_per_layer)
        if n_layers > 10000:
            raise ValueError("Слишком много слоёв; проверьте исходные данные")
        remaining = winding.turns
        for i in range(1, n_layers + 1):
            if i > 1:
                radial += packing.interlayer_tape_mm
            turns = min(remaining, turns_per_layer)
            thickness = rows * pitch
            # Mean turn length increases with layer radius; approximation.
            mean_turn = bobbin.mean_turn_length_mm + 2 * math.pi * (
                radial + thickness / 2)
            wire_length_m = turns * winding.strands * mean_turn / 1000
            result.layers.append(Layer(
                winding.group, winding.name, i, turns, turns_per_layer,
                turns * turn_pitch, radial, radial + thickness, wire_length_m))
            result.wire_length_m += wire_length_m
            radial += thickness
            remaining -= turns
        previous = winding
    radial += packing.final_wrap_mm
    result.radial_used_mm = radial
    if bobbin.available_radial_mm is None:
        result.warnings.append("Радиальный размер НЕ проверен: задайте его по чертежу каркаса.")
    else:
        result.fits = radial + packing.radial_reserve_mm <= bobbin.available_radial_mm
        if not result.fits:
            result.warnings.append(
                f"НЕ ПОМЕЩАЕТСЯ: нужно {radial + packing.radial_reserve_mm:.2f} мм "
                f"с запасом, доступно {bobbin.available_radial_mm:.2f} мм. "
                "Выберите каркас с большей высотой/шириной либо измените провод.")
    if any(w.strands > 1 for w in windings):
        result.warnings.append("Многожильный пучок приближён квадратом; укладку проверить.")
    if len(set(w.group for w in windings)) > 1:
        result.warnings.append("Изоляционные ленты не подтверждают электрическую прочность между группами.")
    result.warnings.append("Выводы, переходы, изоляционные расстояния и реальные размеры слоёв не проверены.")
    return result


def layout_report(layout: Layout) -> str:
    parts = [
        "РАСКЛАДКА ОБМОТОК / ТОЛЬКО ГЕОМЕТРИЧЕСКАЯ ОЦЕНКА",
        "=" * 78,
        f"Активная ширина: {layout.active_width_mm:.2f} мм",
        f"Радиальная толщина намотки: {layout.radial_used_mm:.2f} мм",
        f"Доступная толщина: "
        + ("не указана" if layout.radial_available_mm is None
           else f"{layout.radial_available_mm:.2f} мм"),
        f"Влезает с указанным резервом: "
        + ("неизвестно" if layout.fits is None else ("ДА*" if layout.fits else "НЕТ")),
        f"Количество слоёв: {len(layout.layers)}; "
        f"суммарная длина всех жил ≈ {layout.wire_length_m:.2f} м",
        "",
        "Группа | Обмотка | Слой | Витки | Ширина | Радиус начала..конца | Провода, м",
    ]
    for x in layout.layers:
        parts.append(
            f"{x.group} | {x.winding} | {x.index} | {x.turns} | "
            f"{x.occupied_width_mm:.2f} | {x.radial_start_mm:.2f}.."
            f"{x.radial_end_mm:.2f} | {x.wire_length_m:.2f}")
    parts.extend(["", "ПРЕДУПРЕЖДЕНИЯ:"])
    parts.extend(f"- {x}" for x in layout.warnings)
    parts.append("* Только по упрощённой модели слоёв, без подтверждения изоляции.")
    return "\n".join(parts)
