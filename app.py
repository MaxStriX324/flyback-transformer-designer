"""Tkinter GUI and CLI for the preliminary multi-output flyback calculator."""
import argparse
import csv
from dataclasses import asdict
from pathlib import Path
import sys

from advisor import advice_report, inspect_design, inspect_settings
from winding_layout import Bobbin, Packing, calculate_layout, from_candidate, layout_report

from engine import (
    CORES, Core, Output, Settings, compare_cores,
    load_project, optimize, report, save_project, validate,
)

PARAMS = (
    ("vin_min_v", "Vin минимум, В"),
    ("vin_max_v", "Vin максимум, В"),
    ("frequency_khz", "Частота, кГц"),
    ("duty_max", "D максимум"),
    ("efficiency", "КПД (0..1)"),
    ("vref_target_v", "V отражённое, В"),
    ("max_b_t", "Предел B, Тл"),
    ("current_density_a_mm2", "J, А/мм²"),
    ("window_utilization", "Заполнение окна"),
    ("window_reserved", "Резерв под изоляцию"),
    ("min_demag_margin", "Мин. пауза D"),
    ("gap_min_mm", "Зазор min, мм"),
    ("gap_max_mm", "Зазор max, мм"),
    ("winding_temp_c", "Температура меди, °C"),
)
CORE_PARAMS = (
    ("ae_mm2", "Ae, мм²"),
    ("aw_mm2", "Площадь окна, мм²"),
    ("le_mm", "le, мм"),
    ("mur", "μr (оценка)"),
    ("mlt_mm", "MLT, мм (оценка)"),
)


def main_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class Designer(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title("Flyback Transformer Designer — универсальный многообмоточный расчёт / v0.2")
            self.geometry("1540x930")
            self.minsize(1160, 760)
            self.entries = {}
            self.core_entries = {}
            self.output_entries = {}
            self.outputs = []
            self.last_candidates = []
            self._build()
            self.set_project(Settings())
            self.calculate()

        @staticmethod
        def _put(entry, value):
            entry.delete(0, "end")
            entry.insert(0, str(value))

        def _field(self, parent, key, title, row, destination, width=15):
            ttk.Label(parent, text=title).grid(
                row=row, column=0, sticky="w", padx=5, pady=2)
            e = ttk.Entry(parent, width=width)
            e.grid(row=row, column=1, sticky="ew", padx=5, pady=2)
            destination[key] = e

        def _build(self):
            top = ttk.Frame(self, padding=8)
            top.pack(fill="x")
            boxes = [
                ttk.LabelFrame(top, text="Питание / преобразователь", padding=8),
                ttk.LabelFrame(top, text="Сердечник / каркас", padding=8),
                ttk.LabelFrame(top, text="Ограничения", padding=8),
            ]
            for box in boxes:
                box.pack(side="left", fill="both", expand=True, padx=3)
            for row, (key, title) in enumerate(PARAMS[:6]):
                self._field(boxes[0], key, title, row, self.entries)
            ttk.Label(boxes[1], text="Тип сердечника").grid(
                row=0, column=0, sticky="w", padx=5)
            self.core_name = ttk.Combobox(boxes[1], values=list(CORES), width=18)
            self.core_name.grid(row=0, column=1, sticky="ew", padx=5)
            self.core_name.bind("<<ComboboxSelected>>", self.change_core)
            for row, (key, title) in enumerate(CORE_PARAMS, 1):
                self._field(boxes[1], key, title, row, self.core_entries)
            for row, (key, title) in enumerate(PARAMS[6:]):
                self._field(boxes[2], key, title, row, self.entries)
            ttk.Label(boxes[2], text="Предварительная модель DCM.").grid(
                row=9, column=0, columnspan=2, sticky="w", padx=5)

            panel = ttk.LabelFrame(
                self,
                text="Вторичные обмотки (произвольное число). Первая — опорная",
                padding=7,
            )
            panel.pack(fill="x", padx=14, pady=5)
            tree_box = ttk.Frame(panel)
            tree_box.pack(fill="x")
            columns = ("group", "name", "voltage", "current", "diode")
            self.tree = ttk.Treeview(
                tree_box, columns=columns, show="headings",
                height=11, selectmode="browse",
            )
            for key, label, width in (
                ("group", "Изолированная группа", 175),
                ("name", "Обмотка", 245),
                ("voltage", "U до стабилизатора, В", 185),
                ("current", "Ток, А", 90),
                ("diode", "Диод, В", 100),
            ):
                self.tree.heading(key, text=label)
                self.tree.column(key, width=width, stretch=key in ("group", "name"))
            scrollbar = ttk.Scrollbar(tree_box, orient="vertical",
                                       command=self.tree.yview)
            self.tree.configure(yscrollcommand=scrollbar.set)
            self.tree.pack(side="left", fill="x", expand=True)
            scrollbar.pack(side="right", fill="y")
            self.tree.bind("<<TreeviewSelect>>", self.select_output)

            editor = ttk.Frame(panel)
            editor.pack(fill="x", pady=5)
            for key, label, width in (
                ("group", "Группа", 16),
                ("name", "Название", 23),
                ("voltage_v", "U (+/-), В", 12),
                ("current_a", "Ток, А", 12),
                ("diode_v", "Диод, В", 12),
            ):
                frame = ttk.Frame(editor)
                frame.pack(side="left", padx=(0, 8))
                ttk.Label(frame, text=label).pack(anchor="w")
                e = ttk.Entry(frame, width=width)
                e.pack()
                self.output_entries[key] = e
            for caption, action in (
                ("Добавить", self.add_output),
                ("Обновить", self.update_output),
                ("Удалить", self.delete_output),
                ("Копировать", self.duplicate_output),
                ("Выше", self.move_up),
                ("Ниже", self.move_down),
                ("Сделать опорной", self.make_main),
                ("Импорт CSV", self.import_csv),
                ("Экспорт CSV", self.export_csv),
            ):
                ttk.Button(editor, text=caption, command=action).pack(
                    side="left", padx=3, pady=13)

            actions = ttk.Frame(self, padding=(14, 5))
            actions.pack(fill="x")
            for caption, action in (
                ("Рассчитать варианты", self.calculate),
                ("Сравнить сердечники", self.compare),
                ("Новый проект", self.new_project),
                ("Сохранить JSON", self.save),
                ("Открыть JSON", self.load),
                ("Экспорт TXT", self.export),
            ):
                ttk.Button(actions, text=caption, command=action).pack(
                    side="left", padx=4)

            self.notebook = ttk.Notebook(self)
            self.notebook.pack(fill="both", expand=True, padx=14, pady=(4, 12))
            calculations = ttk.Frame(self.notebook)
            diagnostics = ttk.Frame(self.notebook)
            placement = ttk.Frame(self.notebook)
            self.notebook.add(calculations, text="Результаты / обмоточные данные")
            self.notebook.add(diagnostics, text="Диагностика и рекомендации")
            self.notebook.add(placement, text="Укладка на каркасе")

            def make_text(parent):
                container = ttk.Frame(parent, padding=5)
                container.pack(fill="both", expand=True)
                bar = ttk.Scrollbar(container)
                bar.pack(side="right", fill="y")
                content = tk.Text(container, font=("Consolas", 10), wrap="none",
                                  yscrollcommand=bar.set)
                content.pack(fill="both", expand=True)
                bar.configure(command=content.yview)
                return content

            self.text = make_text(calculations)
            self.advice_text = make_text(diagnostics)

            geometry = ttk.LabelFrame(
                placement, text="Каркас — свои размеры по чертежу или измерению, мм", padding=8)
            geometry.pack(fill="x", padx=7, pady=6)
            self.bobbin_fields = {}
            dims = (
                ("name", "Название каркаса", "User-defined bobbin"),
                ("winding_width_mm", "Полная ширина намотки", "30.0"),
                ("mean_turn_length_mm", "Средняя длина витка MLT", "70.0"),
                ("available_radial_mm", "Радиальное место (пусто = неизвестно)", ""),
                ("end_margin_mm", "Поле по краям (с каждой стороны)", "1.5"),
                ("interlayer_tape_mm", "Изоляция между слоями", "0.05"),
                ("interwinding_tape_mm", "Изоляция между обмотками", "0.07"),
                ("intergroup_tape_mm", "Изоляция между группами", "0.15"),
                ("radial_reserve_mm", "Радиальный резерв", "0.5"),
            )
            for i, (key, title, value) in enumerate(dims):
                col = i % 3
                row = i // 3
                cell = ttk.Frame(geometry)
                cell.grid(row=row, column=col, sticky="ew", padx=8, pady=3)
                ttk.Label(cell, text=title).pack(anchor="w")
                field = ttk.Entry(cell, width=26)
                field.insert(0, value)
                field.pack(fill="x")
                self.bobbin_fields[key] = field
            for col in range(3):
                geometry.columnconfigure(col, weight=1)
            ttk.Button(geometry, text="Проверить укладку обмоток",
                       command=self.check_layout).grid(
                row=3, column=0, columnspan=3, sticky="w", padx=8, pady=6)
            self.layout_text = make_text(placement)

        def change_core(self, event=None):
            core = CORES.get(self.core_name.get())
            if core:
                for key, entry in self.core_entries.items():
                    self._put(entry, getattr(core, key))

        def set_project(self, settings):
            for key, entry in self.entries.items():
                self._put(entry, getattr(settings, key))
            self.core_name.set(settings.core.name)
            for key, entry in self.core_entries.items():
                self._put(entry, getattr(settings.core, key))
            self.outputs = [Output(**asdict(o)) for o in settings.outputs]
            self.last_candidates = []
            for key, value in (settings.layout_options or {}).items():
                if key in self.bobbin_fields:
                    self._put(self.bobbin_fields[key], value)
            self.refresh_outputs()

        def refresh_outputs(self, selected=None):
            self.tree.delete(*self.tree.get_children())
            for index, o in enumerate(self.outputs):
                self.tree.insert("", "end", iid=str(index), values=(
                    o.group, o.name, f"{o.voltage_v:+g}",
                    f"{o.current_a:g}", f"{o.diode_v:g}"))
            if selected is not None and 0 <= selected < len(self.outputs):
                self.tree.selection_set(str(selected))
                self.tree.see(str(selected))

        def selected_index(self):
            selected = self.tree.selection()
            return int(selected[0]) if selected else None

        def select_output(self, event=None):
            index = self.selected_index()
            if index is not None:
                o = self.outputs[index]
                for key, entry in self.output_entries.items():
                    self._put(entry, getattr(o, key))

        def get_output(self):
            try:
                e = self.output_entries
                out = Output(
                    e["name"].get().strip(), e["group"].get().strip(),
                    float(e["voltage_v"].get().replace(",", ".")),
                    float(e["current_a"].get().replace(",", ".")),
                    float(e["diode_v"].get().replace(",", ".")),
                )
                if not out.name or not out.group or out.voltage_v == 0 \
                        or out.current_a <= 0 or out.diode_v < 0:
                    raise ValueError("Параметры обмотки некорректны")
                return out
            except (ValueError, TypeError) as exc:
                messagebox.showerror("Обмотка", str(exc))
                return None

        def add_output(self):
            out = self.get_output()
            if out:
                self.outputs.append(out)
                self.refresh_outputs(len(self.outputs)-1)

        def update_output(self):
            index = self.selected_index()
            if index is None:
                messagebox.showinfo("Выбор", "Выберите обмотку")
                return
            out = self.get_output()
            if out:
                self.outputs[index] = out
                self.refresh_outputs(index)

        def delete_output(self):
            index = self.selected_index()
            if index is not None:
                del self.outputs[index]
                self.refresh_outputs()

        def make_main(self):
            index = self.selected_index()
            if index is not None:
                self.outputs.insert(0, self.outputs.pop(index))
                self.refresh_outputs(0)

        def read_settings(self):
            try:
                params = {key: float(entry.get().replace(",", "."))
                          for key, entry in self.entries.items()}
                geometry = {key: float(entry.get().replace(",", "."))
                            for key, entry in self.core_entries.items()}
                core = Core(
                    name=self.core_name.get().strip() or "Custom", **geometry)
                s = Settings(**params, core=core, outputs=self.outputs[:],
                             layout_options={key: entry.get()
                                for key, entry in self.bobbin_fields.items()})
                return s
            except (ValueError, TypeError) as exc:
                messagebox.showerror("Параметры", str(exc))
                return None

        def import_csv(self):
            path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
            if not path:
                return
            try:
                with open(path, "r", encoding="utf-8-sig", newline="") as file:
                    sample = file.read(4096)
                    file.seek(0)
                    delimiter = ";" if sample.count(";") > sample.count(",") else ","
                    reader = csv.DictReader(file, delimiter=delimiter)
                    required = {"name", "group", "voltage_v", "current_a"}
                    if not reader.fieldnames or not required.issubset(reader.fieldnames):
                        raise ValueError("Нужны столбцы name,group,voltage_v,current_a; "
                                         "diode_v необязателен")
                    rows = []
                    for line, item in enumerate(reader, 2):
                        if not any(item.values()):
                            continue
                        voltage = float(item["voltage_v"].replace(",", "."))
                        current = float(item["current_a"].replace(",", "."))
                        diode = float((item.get("diode_v") or "0.7").replace(",", "."))
                        out = Output(item["name"].strip(), item["group"].strip(),
                                     voltage, current, diode)
                        if not out.name or not out.group or voltage == 0 \
                                or current <= 0 or diode < 0:
                            raise ValueError(f"Строка {line}: некорректная обмотка")
                        rows.append(out)
                if not rows:
                    raise ValueError("В CSV нет строк с обмотками")
                self.outputs.extend(rows)
                self.refresh_outputs(len(self.outputs)-len(rows))
                messagebox.showinfo("Импорт", f"Добавлено обмоток: {len(rows)}")
            except (OSError, KeyError, ValueError, AttributeError) as exc:
                messagebox.showerror("CSV", str(exc))

        def export_csv(self):
            path = filedialog.asksaveasfilename(
                defaultextension=".csv", filetypes=[("CSV", "*.csv")])
            if path:
                with open(path, "w", encoding="utf-8-sig", newline="") as file:
                    writer = csv.writer(file, delimiter=";")
                    writer.writerow(("name", "group", "voltage_v", "current_a", "diode_v"))
                    for o in self.outputs:
                        writer.writerow((o.name, o.group, o.voltage_v,
                                         o.current_a, o.diode_v))

        def new_project(self):
            self.set_project(Settings(outputs=[
                Output("Output 1", "Group 1", 12.0, 0.2, 0.7)]))
            self.calculate()

        def duplicate_output(self):
            index = self.selected_index()
            if index is None:
                return
            source = self.outputs[index]
            duplicate = Output(source.name + " copy", source.group,
                               source.voltage_v, source.current_a, source.diode_v)
            self.outputs.insert(index + 1, duplicate)
            self.refresh_outputs(index + 1)

        def move_up(self):
            index = self.selected_index()
            if index is not None and index > 0:
                self.outputs[index-1], self.outputs[index] = (
                    self.outputs[index], self.outputs[index-1])
                self.refresh_outputs(index-1)

        def move_down(self):
            index = self.selected_index()
            if index is not None and index + 1 < len(self.outputs):
                self.outputs[index+1], self.outputs[index] = (
                    self.outputs[index], self.outputs[index+1])
                self.refresh_outputs(index+1)

        def show_result(self, content):
            self.text.delete("1.0", "end")
            self.text.insert("1.0", content)

        def show_advice(self, notes):
            self.advice_text.delete("1.0", "end")
            self.advice_text.insert("1.0", advice_report(notes))

        def calculate(self):
            s = self.read_settings()
            if s is None:
                return
            try:
                basic_notes = inspect_settings(s)
                if any(a.level == "ERROR" for a in basic_notes):
                    self.last_candidates = []
                    self.show_result("Расчёт не выполнен: исправьте входные данные.\n"
                                     "Перейдите на вкладку «Диагностика и рекомендации».")
                    self.show_advice(basic_notes)
                    self.notebook.select(1)
                    return
                self.last_candidates = optimize(s, top=5)
                self.show_result(report(s, self.last_candidates))
                self.show_advice(inspect_design(s, self.last_candidates))
                if not self.last_candidates:
                    self.notebook.select(1)
            except Exception as exc:
                messagebox.showerror("Расчёт", str(exc))

        def read_bobbin(self):
            fields = self.bobbin_fields
            def number(key):
                return float(fields[key].get().replace(",", "."))
            name = fields["name"].get().strip()
            radial = fields["available_radial_mm"].get().strip()
            bobbin = Bobbin(name=name,
                winding_width_mm=number("winding_width_mm"),
                mean_turn_length_mm=number("mean_turn_length_mm"),
                available_radial_mm=float(radial.replace(",", ".")) if radial else None)
            packing = Packing(end_margin_mm=number("end_margin_mm"),
                interlayer_tape_mm=number("interlayer_tape_mm"),
                interwinding_tape_mm=number("interwinding_tape_mm"),
                intergroup_tape_mm=number("intergroup_tape_mm"),
                radial_reserve_mm=number("radial_reserve_mm"))
            return bobbin, packing

        def check_layout(self):
            s = self.read_settings()
            if s is None:
                return
            try:
                candidates = optimize(s, top=1)
                if not candidates:
                    self.last_candidates = []
                    self.layout_text.delete("1.0", "end")
                    self.layout_text.insert("1.0",
                        "В заданных электрических ограничениях вариант не найден.\n"
                        "См. вкладку «Диагностика и рекомендации».")
                    self.show_advice(inspect_design(s, []))
                    return
                self.last_candidates = candidates
                bobbin, packing = self.read_bobbin()
                layout = calculate_layout(
                    from_candidate(candidates[0]), bobbin, packing)
                self.layout_text.delete("1.0", "end")
                self.layout_text.insert("1.0", layout_report(layout))
                if layout.fits is False:
                    self.advice_text.insert("end",
                        "\n[WARNING] Намотка не помещается по радиальному размеру.\n"
                        "Выберите больший каркас, измените провод или "
                        "геометрию укладки. Проверьте изоляцию отдельно.\n")
            except ValueError as exc:
                self.layout_text.delete("1.0", "end")
                self.layout_text.insert("1.0", "Ошибка геометрии: " + str(exc))

        def compare(self):
            s = self.read_settings()
            if s is not None:
                try:
                    self.show_result(compare_cores(s))
                    self.notebook.select(0)
                except Exception as exc:
                    self.show_advice(inspect_settings(s))
                    self.notebook.select(1)
                    messagebox.showerror("Сравнение", str(exc))

        def save(self):
            s = self.read_settings()
            if s is None:
                return
            filename = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON", "*.json")])
            if filename:
                save_project(s, filename)

        def load(self):
            filename = filedialog.askopenfilename(
                filetypes=[("JSON", "*.json")])
            if filename:
                try:
                    self.set_project(load_project(filename))
                    self.calculate()
                except Exception as exc:
                    messagebox.showerror("Файл", str(exc))

        def export(self):
            filename = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Text", "*.txt")])
            if filename:
                Path(filename).write_text(
                    self.text.get("1.0", "end-1c"), encoding="utf-8-sig")

    Designer().mainloop()


def main():
    parser = argparse.ArgumentParser(
        description="Preliminary multi-output flyback transformer optimizer")
    parser.add_argument("--cli", metavar="PROJECT.json",
                        help="Run JSON project in console mode")
    parser.add_argument("--out", metavar="REPORT.txt",
                        help="Save plain-text report")
    parser.add_argument("--demo", action="store_true",
                        help="Run generic example project")
    parser.add_argument("--advice", action="store_true",
                        help="Append actionable diagnostic recommendations")
    parser.add_argument("--compare-cores", action="store_true",
                        help="Run geometric core comparison")
    args = parser.parse_args()
    if args.cli or args.demo or args.compare_cores or args.advice:
        s = load_project(args.cli) if args.cli else Settings()
        candidates = [] if args.compare_cores else optimize(s)
        result = (compare_cores(s) if args.compare_cores
                  else report(s, candidates))
        if args.advice:
            result += "\n\n" + advice_report(inspect_design(s, candidates))
        if args.out:
            Path(args.out).write_text(result, encoding="utf-8-sig")
        else:
            try:
                print(result)
            except UnicodeEncodeError:
                sys.stdout.buffer.write(result.encode("utf-8"))
    else:
        main_gui()


if __name__ == "__main__":
    main()