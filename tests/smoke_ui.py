"""Smoke test gráfico con Xvfb: comprueba que los controles se construyen."""
from __future__ import annotations

import queue
import tkinter as tk
from cprot_ui import make_root, build_interface, toggle_theme


class FakeController:
    def __init__(self, root):
        self.root = root
        self.work_queue = queue.Queue()

    def _start(self): pass
    def _list_printers(self):
        self.printer_combo.configure(values=["Impresora de prueba"])
        self.printer_combo.set("Impresora de prueba")
    def _select_origin(self): pass
    def _select_destination(self): pass
    def _refresh_list(self): pass
    def _print_selected(self): pass
    def _classify(self): pass
    def _save_config(self): pass


if __name__ == "__main__":
    root = make_root()
    try:
        app = FakeController(root)
        build_interface(app)
        root.update_idletasks()
        root.update()
        for obj in ("run_button", "printer_combo", "files_box", "patient_entry",
                    "classify_button", "log_text", "status_label",
                    "metric_files", "metric_queue", "header_status_label"):
            assert hasattr(app, obj), "Control ausente: " + obj
            assert getattr(app, obj).winfo_exists()
        assert root.theme_use() == "cprot-dark", root.theme_use()
        toggle_theme(app)
        root.update_idletasks()
        assert root.theme_use() == "cprot-light", root.theme_use()
        toggle_theme(app)
        assert root.theme_use() == "cprot-dark", root.theme_use()
        print("CPROT UI: dark/light themes and essential widgets OK")
    finally:
        root.destroy()
