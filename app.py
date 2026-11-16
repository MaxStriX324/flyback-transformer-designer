"""Tkinter GUI and CLI for the preliminary multi-output flyback calculator."""
import argparse
from dataclasses import asdict
from pathlib import Path
import sys

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
            self.title("Flyback Transformer Designer — многовыводный DCM / v0.1")
            self.geometry("1460x950")
            self.minsize(1100, 730)
            self.entries = {}
            self.core_entries = {}
            self.output_entries = {}
            self.outputs = []
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
                height=9, selectmode="browse",
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
                ("Сделать опорной", self.make_main),
            ):
                ttk.Button(editor, text=caption, command=action).pack(
                    side="left", padx=3, pady=13)

            actions = ttk.Frame(self, padding=(14, 5))
            actions.pack(fill="x")
            for caption, action in (
                ("Рассчитать варианты", self.calculate),
                ("Сравнить сердечники", self.compare),
                ("Сохранить JSON", self.save),
                ("Открыть JSON", self.load),
                ("Экспорт TXT", self.export),
            ):
                ttk.Button(actions, text=caption, command=action).pack(
                    side="left", padx=4)

            result = ttk.LabelFrame(
                self, text="Расчётные варианты / обмоточные данные", padding=6)
            result.pack(fill="both", expand=True, padx=14, pady=(4, 12))
            scroll = ttk.Scrollbar(result)
            scroll.pack(side="right", fill="y")
            self.text = tk.Text(
                result, font=("Consolas", 10), wrap="none",
                yscrollcommand=scroll.set)
            self.text.pack(fill="both", expand=True)
            scroll.configure(command=self.text.yview)

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
                s = Settings(**params, core=core, outputs=self.outputs[:])
                validate(s)
                return s
            except (ValueError, TypeError) as exc:
                messagebox.showerror("Параметры", str(exc))
                return None

        def show_result(self, content):
            self.text.delete("1.0", "end")
            self.text.insert("1.0", content)

        def calculate(self):
            s = self.read_settings()
            if s is not None:
                try:
                    self.show_result(report(s, optimize(s, top=5)))
                except Exception as exc:
                    messagebox.showerror("Расчёт", str(exc))

        def compare(self):
            s = self.read_settings()
            if s is not None:
                try:
                    self.show_result(compare_cores(s))
                except Exception as exc:
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
                        help="Run bundled default 8-output demo")
    parser.add_argument("--compare-cores", action="store_true",
                        help="Run geometric core comparison")
    args = parser.parse_args()
    if args.cli or args.demo or args.compare_cores:
        s = load_project(args.cli) if args.cli else Settings()
        result = (compare_cores(s) if args.compare_cores
                  else report(s, optimize(s)))
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