"""Multi-winding flyback transformer designer: preliminary DCM model.

NOT a safety-qualified transformer design tool. The algorithm ignores core loss,
AC copper/proximity loss, fringing, cross-regulation, layer geometry, thermal
behavior and mandatory isolation distances. Verify physical prototypes.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, replace
import json
import math
from pathlib import Path

MU0 = 4 * math.pi * 1e-7
CU_RESISTIVITY_20 = 0.01724  # ohm*mm2/m
CU_TEMPERATURE_COEFFICIENT = 0.00393
DIAMETERS_MM = (0.10, 0.125, 0.15, 0.20, 0.25, 0.28, 0.30, 0.35, 0.40, 0.45, 0.50)


@dataclass
class Core:
    name: str
    ae_mm2: float
    aw_mm2: float
    le_mm: float
    mur: float
    mlt_mm: float


# Geometry is approximate. Confirm the exact material, bobbin, and datasheets.
CORES = {
    "ETD29": Core("ETD29", 76.0, 97.0, 70.4, 1610, 57),
    "ETD34": Core("ETD34", 97.1, 122.0, 78.6, 1670, 65),
    "ETD39": Core("ETD39", 125.0, 178.0, 92.2, 1600, 74),
    "ETD44": Core("ETD44", 173.0, 210.0, 103.0, 1650, 86),
    "ETD49": Core("ETD49", 211.0, 269.4, 114.0, 1630, 95),
    "E-Sh5x5": Core("E-Sh5x5", 30.09, 40.0, 43.15, 1400, 38),
}


@dataclass
class Output:
    name: str
    group: str
    voltage_v: float
    current_a: float
    diode_v: float = 0.7


def demo_outputs() -> list[Output]:
    """Demonstration pre-regulator voltages, not guaranteed UCC21750 loads."""
    return [
        Output(f"{rail} {group}", group, voltage, current)
        for group in ("Upper A", "Upper B", "Upper C", "Lower")
        for rail, voltage, current in (("+18 V", 18.0, 0.08), ("-11 V", -11.0, 0.03))
    ]


@dataclass
class Settings:
    vin_min_v: float = 10.0
    vin_max_v: float = 30.0
    frequency_khz: float = 120.0
    duty_max: float = 0.42
    efficiency: float = 0.8
    vref_target_v: float = 20.0
    max_b_t: float = 0.16
    current_density_a_mm2: float = 4.0
    window_utilization: float = 0.35
    window_reserved: float = 0.10
    min_demag_margin: float = 0.10
    gap_min_mm: float = 0.05
    gap_max_mm: float = 1.50
    winding_temp_c: float = 80.0
    core: Core | None = None
    outputs: list[Output] | None = None

    def __post_init__(self) -> None:
        if self.core is None:
            self.core = replace(CORES["ETD39"])
        if self.outputs is None:
            self.outputs = demo_outputs()


def validate(s: Settings) -> None:
    checks = [
        (0 < s.vin_min_v <= s.vin_max_v, "Vin: 0 < min <= max"),
        (5 <= s.frequency_khz <= 2000, "Frequency: 5..2000 kHz"),
        (0.1 <= s.duty_max < 0.8, "Duty: 0.1..0.8"),
        (0.3 <= s.efficiency <= 1, "Efficiency: 0.3..1.0"),
        (0 < s.vref_target_v <= 500, "Reflected voltage: 0..500 V"),
        (0.02 < s.max_b_t < 0.45, "Design flux density: 0.02..0.45 T"),
        (0.2 < s.current_density_a_mm2 <= 15, "Current density: 0.2..15 A/mm2"),
        (0.01 < s.window_utilization <= 0.85, "Window utilization: 0.01..0.85"),
        (0 <= s.window_reserved < s.window_utilization, "Window reserve exceeds limit"),
        (0.02 <= s.min_demag_margin < 0.8, "Demagnetization margin: 0.02..0.8"),
        (0 <= s.gap_min_mm < s.gap_max_mm < 10, "Invalid gap bounds"),
        (-40 < s.winding_temp_c <= 180, "Winding temperature: -40..180 C"),
    ]
    for ok, message in checks:
        if not ok:
            raise ValueError(message)
    if s.core is None or min(s.core.ae_mm2, s.core.aw_mm2, s.core.le_mm,
                             s.core.mur, s.core.mlt_mm) <= 0:
        raise ValueError("Invalid magnetic core geometry")
    if not s.outputs:
        raise ValueError("At least one secondary winding is required")
    for o in s.outputs:
        if (not o.name.strip() or not o.group.strip() or
                o.voltage_v == 0 or o.current_a <= 0 or o.diode_v < 0):
            raise ValueError(f"Invalid output winding: {o.name}")


def save_project(s: Settings, filename: str | Path) -> None:
    Path(filename).write_text(json.dumps(asdict(s), indent=2, ensure_ascii=False),
                              encoding="utf-8")


def load_project(filename: str | Path) -> Settings:
    data = json.loads(Path(filename).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    data["core"] = Core(**data["core"])
    data["outputs"] = [Output(**entry) for entry in data["outputs"]]
    s = Settings(**data)
    validate(s)
    return s


def choose_wire(current_rms_a: float, max_density: float,
                freq_hz: float) -> tuple[float, int, float, float]:
    """Return (bare diameter, parallel strands, copper area, packed area).

    Estimates enamel thickness as 40 micrometers of diameter. Real enamel grade
    and proximity losses must be checked before a final winding layout.
    """
    required_area = current_rms_a / max_density
    skin_depth_mm = math.sqrt(1.724e-8 / (math.pi * freq_hz * MU0)) * 1000
    options = []
    for d in DIAMETERS_MM:
        if d > 2 * skin_depth_mm:
            continue
        single_area = math.pi * d * d / 4
        count = max(1, math.ceil(required_area / single_area - 1e-10))
        if count > 100:
            continue
        copper = count * single_area
        packed = count * math.pi * (d + 0.04)**2 / 4
        options.append((packed * (1 + 0.002 * count), d, count, copper, packed))
    if not options:
        raise ValueError("No wire choice available at selected frequency/current")
    _, diameter, count, copper, packed = min(options)
    return diameter, count, copper, packed


@dataclass
class WindingResult:
    name: str
    group: str
    turns: int
    target_v: float
    predicted_v: float
    current_a: float
    rms_a: float
    wire_mm: float
    strands: int
    current_density: float
    copper_loss_w: float
    window_area_mm2: float
    error_percent: float


@dataclass
class Candidate:
    core: str
    primary_turns: int
    lp_uh: float
    al_nh: float
    total_gap_mm: float
    bpk_t: float
    duty: float
    demag_duty: float
    idle_fraction: float
    vref_v: float
    input_peak_a: float
    input_rms_a: float
    primary_wire_mm: float
    primary_strands: int
    total_power_w: float
    predicted_input_power_w: float
    primary_copper_loss_w: float
    copper_losses_w: float
    used_window_fraction: float
    mosfet_vds_ideal_v: float
    max_vin_limited_duty: float
    score: float
    windings: list[WindingResult]


def optimize(s: Settings, top: int = 5) -> list[Candidate]:
    """Enumerate discrete preliminary DCM candidates for one core.

    Secondary currents are approximate triangular currents. Multiple output
    cross-regulation, layer placement and core loss are not modeled.
    """
    validate(s)
    if top <= 0:
        return []
    core = s.core
    f = s.frequency_khz * 1000
    ae = core.ae_mm2 * 1e-6
    le = core.le_mm * 1e-3
    mlt_m = core.mlt_mm * 1e-3
    copper_rho = CU_RESISTIVITY_20 * (
        1 + CU_TEMPERATURE_COEFFICIENT * (s.winding_temp_c - 20))
    p_out = sum(abs(o.voltage_v) * o.current_a for o in s.outputs)
    p_in = p_out / s.efficiency
    main = s.outputs[0]
    v_main = abs(main.voltage_v) + main.diode_v
    candidates = []
    duty_values = sorted({round(s.duty_max * x, 3)
                          for x in (0.58, 0.70, 0.82, 0.92, 1.0)})
    for d in duty_values:
        if d + s.min_demag_margin >= 1:
            continue
        peak_a = 2 * p_in / (s.vin_min_v * d)
        lp_h = s.vin_min_v * d / (f * peak_a)
        rms_primary = peak_a * math.sqrt(d / 3)
        try:
            p_d, p_n, p_cu, p_packed = choose_wire(
                rms_primary, s.current_density_a_mm2, f)
        except ValueError:
            continue
        for n_primary in range(2, 121):
            bpk = lp_h * peak_a / (n_primary * ae)
            if bpk > s.max_b_t:
                continue
            al_nh = lp_h / n_primary**2 * 1e9
            gap_mm = (MU0 * ae * n_primary**2 / lp_h -
                      le / core.mur) * 1000
            if not (s.gap_min_mm <= gap_mm <= s.gap_max_mm):
                continue
            base_secondary = max(1, round(
                n_primary * v_main / s.vref_target_v))
            copper_primary = (rms_primary**2 * copper_rho * mlt_m *
                              1.15 * n_primary / p_cu)
            for n_main in range(max(1, base_secondary - 3), base_secondary + 4):
                v_ref = n_primary / n_main * v_main
                if not (0.75 * s.vref_target_v <= v_ref <=
                        1.25 * s.vref_target_v):
                    continue
                d_demag = s.vin_min_v * d / v_ref
                idle = 1 - d - d_demag
                if idle < s.min_demag_margin:
                    continue
                used_area = n_primary * p_packed
                copper_losses = copper_primary
                winding_results = []
                error_score = 0.0
                feasible = True
                for o in s.outputs:
                    n = max(1, round(n_main *
                        (abs(o.voltage_v) + o.diode_v) / v_main))
                    voltage_magnitude = n / n_main * v_main - o.diode_v
                    predicted = math.copysign(voltage_magnitude, o.voltage_v)
                    error = 100 * (
                        voltage_magnitude - abs(o.voltage_v)) / abs(o.voltage_v)
                    # First-order DCM RMS approximation per separate output.
                    rms = 2 * o.current_a / math.sqrt(3 * d_demag)
                    try:
                        wd, wn, wa, packed = choose_wire(
                            rms, s.current_density_a_mm2, f)
                    except ValueError:
                        feasible = False
                        break
                    loss = rms**2 * copper_rho * mlt_m * 1.15 * n / wa
                    used_area += packed * n
                    copper_losses += loss
                    weight = max(0.3, math.sqrt(
                        abs(o.voltage_v) * o.current_a /
                        (p_out / len(s.outputs))))
                    error_score += abs(error) * weight
                    winding_results.append(WindingResult(
                        o.name, o.group, n, o.voltage_v, predicted,
                        o.current_a, rms, wd, wn, rms / wa,
                        loss, packed * n, error))
                if not feasible:
                    continue
                used_fraction = used_area / core.aw_mm2 + s.window_reserved
                if used_fraction > s.window_utilization:
                    continue
                score = (4 * error_score / len(s.outputs) +
                         5 * copper_losses / max(p_out, 0.01) +
                         0.015 * (n_primary +
                                  sum(w.turns for w in winding_results)) +
                         0.15 * gap_mm +
                         1.3 * used_fraction / s.window_utilization)
                candidates.append(Candidate(
                    core.name, n_primary, lp_h * 1e6, al_nh,
                    gap_mm, bpk, d, d_demag, idle, v_ref, peak_a,
                    rms_primary, p_d, p_n, p_out, p_in,
                    copper_primary, copper_losses, used_fraction,
                    s.vin_max_v + v_ref, d * s.vin_min_v / s.vin_max_v,
                    score, winding_results))
    candidates.sort(key=lambda c: c.score)
    distinct = []
    seen = set()
    for c in candidates:
        key = (c.primary_turns, tuple(x.turns for x in c.windings),
               round(c.duty, 3))
        if key in seen:
            continue
        distinct.append(c)
        seen.add(key)
        if len(distinct) >= top:
            break
    return distinct


def report(s: Settings, candidates: list[Candidate]) -> str:
    """Human-readable preliminary report in Russian."""
    validate(s)
    lines = [
        "FLYBACK TRANSFORMER DESIGNER | ПРЕДВАРИТЕЛЬНЫЙ РАСЧЁТ DCM",
        "=" * 79,
        f"Сердечник: {s.core.name}; Ae={s.core.ae_mm2:g} мм²; "
        f"окно≈{s.core.aw_mm2:g} мм²; MLT≈{s.core.mlt_mm:g} мм",
        f"Vin={s.vin_min_v:g}..{s.vin_max_v:g} В; "
        f"f={s.frequency_khz:g} кГц; Dmax={s.duty_max:.3f}; "
        f"расчётный КПД={s.efficiency:.0%}",
        f"Вторичных обмоток: {len(s.outputs)}; "
        f"изолированных групп: {len(set(o.group for o in s.outputs))}",
        f"Нагрузка: {sum(abs(o.voltage_v)*o.current_a for o in s.outputs):.3f} Вт",
        "",
    ]
    if not candidates:
        lines.append("ВАРИАНТЫ НЕ НАЙДЕНЫ ПРИ ЗАДАННЫХ ОГРАНИЧЕНИЯХ")
    for index, c in enumerate(candidates, 1):
        lines.extend([
            f"ВАРИАНТ {index}  (оценка {c.score:.3f})",
            "-" * 79,
            f"Np={c.primary_turns}; Lp={c.lp_uh:.2f} мкГн; "
            f"AL={c.al_nh:.1f} нГн/вит²; полный зазор≈{c.total_gap_mm:.3f} мм",
            f"Bpk≈{c.bpk_t*1000:.1f} мТл; "
            f"Ipk≈{c.input_peak_a:.3f} А; "
            f"Irms≈{c.input_rms_a:.3f} А; "
            f"первичный провод: {c.primary_strands}×{c.primary_wire_mm:g} мм",
            f"Dвкл={c.duty:.3f}; Dразмагничивания={c.demag_duty:.3f}; "
            f"свободный период={c.idle_fraction:.3f}",
            f"Vотражённое={c.vref_v:.2f} В; "
            f"Vds идеальное при Vin_max≥{c.mosfet_vds_ideal_v:.1f} В "
            f"(без выброса от Lрассеяния)",
            f"Заполнение окна≈{c.used_window_fraction:.1%}; "
            f"Pмедь(только DC)≈{c.copper_losses_w:.3f} Вт",
            "Группа | Обмотка | Витки | Uрасч | I_rms | Провод | Ошибка",
        ])
        for w in c.windings:
            lines.append(
                f"{w.group} | {w.name} | {w.turns} | "
                f"{w.predicted_v:+.2f} В | {w.rms_a:.3f} А | "
                f"{w.strands}×{w.wire_mm:g} мм | {w.error_percent:+.2f}%")
        if any(abs(w.error_percent) > 5 for w in c.windings):
            lines.append("ВНИМАНИЕ: ошибка напряжений отдельных обмоток >5%.")
        lines.append("")
    lines.extend([
        "ВАЖНО: расчёт предварительный, рассчитана только точка DCM при Vin_min.",
        "Не моделируются сердечниковые и AC-потери меди, реальная раскладка,",
        "размагничивание разных выходов, кросс-регулирование, тепловой режим,",
        "снаббер, выбросы на ключе, фринжинг, изоляционные расстояния и EMI.",
        "Перед изготовлением проверить паспорт сердечника и каркаса,",
        "полученную Lp/AL, Ipk, осциллограммы, температуру и электрическую прочность."
    ])
    return "\n".join(lines)


def compare_cores(s: Settings) -> str:
    """Rank feasible known geometries by magnetic volume, not by temperature."""
    validate(s)
    lines = [
        "СРАВНЕНИЕ СЕРДЕЧНИКОВ — УПРОЩЁННАЯ ГЕОМЕТРИЧЕСКАЯ ОЦЕНКА",
        "Не учитывает потери феррита, нагрев, зазоры изоляции и стоимость.",
        "Сердечник | Ve (см³) | Np | Lp (мкГн) | Зазор (мм) | "
        "Bpk (мТл) | Медь (Вт) | Окно (%) | Макс ошибка (%)",
    ]
    for name, core in sorted(
        CORES.items(), key=lambda item: item[1].ae_mm2 * item[1].le_mm
    ):
        cands = optimize(replace(s, core=replace(core)), top=1)
        ve = core.ae_mm2 * core.le_mm / 1000
        if not cands:
            lines.append(f"{name} | {ve:.2f} | вариант не найден")
            continue
        c = cands[0]
        max_error = max(abs(w.error_percent) for w in c.windings)
        lines.append(f"{name} | {ve:.2f} | {c.primary_turns} | "
                     f"{c.lp_uh:.2f} | {c.total_gap_mm:.3f} | "
                     f"{c.bpk_t*1000:.1f} | {c.copper_losses_w:.3f} | "
                     f"{c.used_window_fraction*100:.1f} | {max_error:.2f}")
    return "\n".join(lines)