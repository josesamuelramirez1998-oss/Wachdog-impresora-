"""Ventana de captura PCL5 experimental para CPROT QRS-Card.

No cambia la impresora predeterminada de Windows ni configura el controlador.
Necesita que el usuario cree una impresora DE PRUEBA con puerto RAW local.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import ttkbootstrap as ttk

from pcl_capture import DEFAULT_PORT, RawCaptureServer, convert_to_pdf, load_captures

APP_HOME = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "QRS-Card"
DEFAULT_STORE = APP_HOME / "capturas_pcl"
SETTINGS_FILE = APP_HOME / "pcl_capture_settings.json"


class CaptureWindow:
    def __init__(self, parent: tk.Misc):
        self.root = tk.Toplevel(parent)
        self.root.title("CPROT | Captura PCL5 · Laboratorio")
        self.root.geometry("900x735")
        self.root.minsize(760, 640)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.events: queue.Queue = queue.Queue()
        self.receiver: RawCaptureServer | None = None
        self.is_converting = False
        self.records: list[dict] = []
        self.closed = False
        self.output_var = tk.StringVar(value=str(DEFAULT_STORE))
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        self.ghost_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Detenido")
        self.last_job_var = tk.StringVar(value="Todavía no hay trabajos")
        self._load_settings()
        self._build()
        self.refresh()
        self.root.after(200, self._process_events)

    def _load_settings(self):
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            self.output_var.set(str(data.get("output_dir") or DEFAULT_STORE))
            self.port_var.set(str(data.get("port") or DEFAULT_PORT))
            self.ghost_var.set(str(data.get("ghostpcl") or ""))
        except (OSError, ValueError, TypeError):
            pass

    def _save_settings(self):
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = SETTINGS_FILE.with_suffix(".tmp")
        data = {"output_dir": self.output_var.get(), "port": self.port_var.get(),
                "ghostpcl": self.ghost_var.get()}
        try:
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, SETTINGS_FILE)
        finally:
            temp.unlink(missing_ok=True)

    def _build(self):
        shell = ttk.Frame(self.root, padding=(22, 17))
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text="CAPTURA DE IMPRESIÓN NATIVA",
                  font=("Segoe UI", 17, "bold")).pack(anchor="w")
        ttk.Label(shell, text="Laboratorio PCL / RAW TCP • Preserva los bytes originales de la cola de prueba",
                  bootstyle="secondary", font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 13))

        warning = ttk.Labelframe(shell, text="MODO EXPERIMENTAL · NO CLÍNICO", padding=12,
                                 bootstyle="warning")
        warning.pack(fill="x", pady=(0, 12))
        ttk.Label(
            warning, bootstyle="warning", wraplength=790, justify="left",
            text="Solo pruebas con datos ficticios. Esta herramienta NO modifica la impresora "
                 "clínica ni imprime papel. Escucha exclusivamente 127.0.0.1. "
                 "Una conexión TCP puede no corresponder a un estudio completo. "
                 "El PDF convertido requiere comparación con la salida clínica original."
        ).pack(anchor="w")

        config = ttk.Labelframe(shell, text="01 · Receptor local", padding=13)
        config.pack(fill="x", pady=(0, 12))
        row1 = ttk.Frame(config)
        row1.pack(fill="x", pady=(0, 8))
        ttk.Label(row1, text="Puerto TCP RAW:", width=18).pack(side="left")
        self.port_entry = ttk.Entry(row1, textvariable=self.port_var, width=8)
        self.port_entry.pack(side="left")
        ttk.Label(row1, text="Host fijo: 127.0.0.1 (sin acceso externo)",
                  bootstyle="secondary").pack(side="left", padx=14)
        row2 = ttk.Frame(config)
        row2.pack(fill="x", pady=(0, 8))
        ttk.Label(row2, text="Carpeta de captura:", width=18).pack(side="left")
        self.output_entry = ttk.Entry(row2, textvariable=self.output_var)
        self.output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.pick_folder_btn = ttk.Button(row2, text="Explorar", bootstyle="secondary outline",
                                          command=self.choose_folder)
        self.pick_folder_btn.pack(side="left")
        row3 = ttk.Frame(config)
        row3.pack(fill="x")
        self.toggle_button = ttk.Button(row3, text="▶  Iniciar receptor",
                                        bootstyle="success", command=self.toggle)
        self.toggle_button.pack(side="left")
        self.state_label = ttk.Label(row3, textvariable=self.status_var,
                                     bootstyle="secondary", font=("Segoe UI", 10, "bold"))
        self.state_label.pack(side="left", padx=16)
        ttk.Label(row3, text="Límite por sesión: 512 MiB",
                  bootstyle="secondary", font=("Segoe UI", 9)).pack(side="right")

        records = ttk.Labelframe(shell, text="02 · Capturas locales", padding=11)
        records.pack(fill="both", expand=True, pady=(0, 12))
        self.capture_list = tk.Listbox(records, selectmode=tk.SINGLE, height=7,
                                       font=("Consolas", 10), activestyle="none")
        scroll = ttk.Scrollbar(records, orient="vertical", command=self.capture_list.yview)
        self.capture_list.configure(yscrollcommand=scroll.set)
        self.capture_list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.capture_list.bind("<<ListboxSelect>>", lambda _event: self._show_selection())

        action_row = ttk.Frame(shell)
        action_row.pack(fill="x", pady=(0, 12))
        ttk.Button(action_row, text="↻  Actualizar", bootstyle="secondary outline",
                   command=self.refresh).pack(side="left", padx=(0, 7))
        ttk.Button(action_row, text="Abrir carpeta", bootstyle="secondary outline",
                   command=self.open_folder).pack(side="left", padx=(0, 7))
        ttk.Label(action_row, textvariable=self.last_job_var,
                  bootstyle="secondary", wraplength=470).pack(side="right")

        converter = ttk.Labelframe(shell, text="03 · Conversión opcional (GhostPCL)", padding=11)
        converter.pack(fill="x", pady=(0, 12))
        ttk.Label(
            converter,
            text="Instala GhostPCL por separado y selecciona su ejecutable. "
                 "La conversión solo funciona para capturas completas reconocidas como PCL.",
            bootstyle="secondary", wraplength=780,
        ).pack(anchor="w", pady=(0, 8))
        row4 = ttk.Frame(converter)
        row4.pack(fill="x")
        self.ghost_entry = ttk.Entry(row4, textvariable=self.ghost_var)
        self.ghost_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(row4, text="Seleccionar .exe", command=self.choose_ghost,
                   bootstyle="secondary outline").pack(side="left", padx=(0, 8))
        self.convert_button = ttk.Button(row4, text="Convertir PDF",
                                         command=self.convert_selected, bootstyle="info")
        self.convert_button.pack(side="left")

        ttk.Label(shell, text="CPROT · Archivo original intacto · PDF solo de consulta hasta validar escalas y trazos",
                  bootstyle="secondary", font=("Segoe UI", 9)).pack(anchor="w")

    def _folder(self) -> Path:
        directory = Path(self.output_var.get()).expanduser().resolve()
        if not self.output_var.get().strip() or directory == Path(directory.anchor):
            raise ValueError("Selecciona una carpeta de captura específica.")
        return directory

    def choose_folder(self):
        if self.receiver and self.receiver.running:
            return
        path = filedialog.askdirectory(parent=self.root, title="Carpeta privada de capturas PCL")
        if path:
            self.output_var.set(path)
            self.refresh()

    def choose_ghost(self):
        path = filedialog.askopenfilename(
            parent=self.root, title="Selecciona GhostPCL (gpcl6win64.exe)",
            filetypes=[("Ejecutable", "*.exe"), ("Todos", "*.*")],
        )
        if path:
            self.ghost_var.set(path)
            self._save_settings()

    def toggle(self):
        if self.receiver and self.receiver.running:
            if not messagebox.askyesno(
                "Detener receptor", "Si hay un trabajo de impresión abierto se conservará "
                "como captura parcial.\n\n¿Detener el receptor?", parent=self.root
            ):
                return
            self.receiver.stop()
            self.status_var.set("Detenido; revise los trabajos abiertos")
            self.toggle_button.configure(text="▶  Iniciar receptor", bootstyle="success")
            self.port_entry.configure(state="normal")
            self.output_entry.configure(state="normal")
            self.pick_folder_btn.configure(state="normal")
            self.refresh()
            return
        try:
            port = int(self.port_var.get().strip())
            folder = self._folder()
            srv = RawCaptureServer(folder, port=port,
                                   on_event=lambda ev: self.events.put(("capture", ev)))
            srv.start()
            self.receiver = srv
            self._save_settings()
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror("No se puede iniciar la captura", str(exc), parent=self.root)
            return
        self.status_var.set(f"Escuchando 127.0.0.1:{port}")
        self.toggle_button.configure(text="■  Detener receptor", bootstyle="danger")
        self.port_entry.configure(state="disabled")
        self.output_entry.configure(state="disabled")
        self.pick_folder_btn.configure(state="disabled")

    def refresh(self):
        try:
            self.records = load_captures(self._folder())
        except (OSError, ValueError):
            self.records = []
        self.capture_list.delete(0, tk.END)
        for record in self.records:
            value = record.get("bytes", 0)
            try:
                kb = max(0, int(value)) / 1024
            except (ValueError, TypeError):
                kb = 0
            line = f"{record.get('id', '')[:28]}  {record.get('state', '?'):<12}  {record.get('format', '?'):<10} {kb:>9,.0f} KiB"
            self.capture_list.insert(tk.END, line)

    def _show_selection(self):
        indexes = self.capture_list.curselection()
        if not indexes:
            return
        record = self.records[indexes[0]]
        self.last_job_var.set(
            f"{record.get('state', '?')} · {record.get('format', '?')} · "
            f"{record.get('bytes', 0)} bytes · PDF: "
            f"{'sí' if record.get('converted_pdf') else 'no'}"
        )

    def open_folder(self):
        try:
            folder = self._folder()
            folder.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(folder))  # disponible solo en Windows
            else:
                messagebox.showinfo("Carpeta", str(folder), parent=self.root)
        except OSError as exc:
            messagebox.showerror("Carpeta no disponible", str(exc), parent=self.root)

    def convert_selected(self):
        if self.is_converting:
            return
        indexes = self.capture_list.curselection()
        if not indexes:
            messagebox.showwarning("Selecciona una captura", "Selecciona un trabajo PCL completo.",
                                   parent=self.root)
            return
        record = self.records[indexes[0]]
        if record.get("state") != "complete" or record.get("format") not in ("pcl", "pclxl"):
            messagebox.showwarning("Captura no compatible",
                                   "Solo se convierten capturas PCL completas.",
                                   parent=self.root)
            return
        exe = self.ghost_var.get().strip()
        if not exe:
            messagebox.showwarning("GhostPCL", "Selecciona el ejecutable gpcl6win64.exe.",
                                   parent=self.root)
            return
        self._save_settings()
        self.is_converting = True
        self.convert_button.configure(state="disabled", text="Convirtiendo…")
        folder = self._folder()
        def task():
            try:
                result = convert_to_pdf(folder, record, exe, timeout=240)
                self.events.put(("converted", str(result)))
            except Exception as exc:
                self.events.put(("conversion_error", f"{type(exc).__name__}: {exc}"))
        threading.Thread(target=task, daemon=True, name="cprot-pcl-converter").start()

    def _process_events(self):
        if self.closed:
            return
        for _ in range(50):
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "capture":
                event = payload
                if event.kind == "started":
                    self.last_job_var.set("Recibiendo datos PCL en tiempo real…")
                elif event.kind == "progress":
                    self.last_job_var.set(f"Recibiendo: {event.size:,} bytes")
                elif event.kind in ("completed", "interrupted", "error"):
                    self.last_job_var.set(event.message or event.kind)
                    self.refresh()
                elif event.kind == "stopped" and (not self.receiver or not self.receiver.running):
                    self.status_var.set("Detenido")
            else:
                self.is_converting = False
                self.convert_button.configure(state="normal", text="Convertir PDF")
                self.refresh()
                if kind == "converted":
                    messagebox.showinfo("PDF generado", f"Se generó un PDF de consulta:\n{payload}\n\n"
                                        "Verifica escalas y trazos antes de cualquier uso clínico.",
                                        parent=self.root)
                elif kind == "conversion_error":
                    messagebox.showerror("No se pudo convertir", str(payload), parent=self.root)
        self.root.after(200, self._process_events)

    def close(self):
        if self.receiver and self.receiver.running:
            if not messagebox.askyesno(
                "Cerrar captura", "Cerrar interrumpe los trabajos abiertos. "
                "Se conservarán como parciales.\n\n¿Cerrar?", parent=self.root
            ):
                return
        if self.is_converting and not messagebox.askyesno(
            "Conversión en curso", "Hay un PDF convirtiéndose. ¿Cerrar la ventana?",
            parent=self.root
        ):
            return
        self.closed = True
        if self.receiver:
            self.receiver.stop()
        self.root.destroy()


def open_capture_window(parent: tk.Misc):
    return CaptureWindow(parent)
