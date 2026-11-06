"""Interfaz de escritorio QRS-Card con identidad visual CPROT.

Construida sobre ttkbootstrap: utiliza widgets nativos y conserva la lógica
de impresión en AppCardio. No usa gráficos ni servicios externos.
"""
from __future__ import annotations

import tkinter as tk
import ttkbootstrap as ttk

NAVY = "#081525"
CYAN = "#3EB6FF"
WHITE = "#F4FAFF"
MUTED = "#9EB2C8"


def make_root():
    """Registra una pareja de temas propios antes de abrir la ventana."""
    ttk.Theme(
        name="cprot",
        primary="#168BE4",
        success="#12B886",
        info="#38BDF8",
        warning="#F6B94D",
        danger="#F15B67",
        light=dict(background="#F5F8FD", foreground="#14253D"),
        dark=dict(background="#0B1525", foreground="#EAF4FF"),
    ).register()
    root = ttk.App(theme="cprot-dark", title="CPROT | QRS-Card")
    return root


def _card_metric(parent, column, title, value):
    card = ttk.Labelframe(parent, text=title, padding=(18, 11), bootstyle="secondary")
    card.grid(row=0, column=column, sticky="nsew", padx=(0, 8) if column < 2 else 0)
    label = ttk.Label(card, text=value, font=("Segoe UI", 15, "bold"))
    label.pack(anchor="w")
    return label


def _folder_card(parent, column, title, subtitle, text, callback):
    frame = ttk.Labelframe(parent, text=title, padding=(13, 10), bootstyle="secondary")
    frame.grid(row=0, column=column, sticky="nsew", padx=(0, 8) if column == 0 else 0)
    ttk.Label(frame, text=subtitle, bootstyle="secondary",
              font=("Segoe UI", 9)).pack(anchor="w")
    path = ttk.Label(frame, text=text, wraplength=370, font=("Segoe UI", 9))
    path.pack(anchor="w", fill="x", pady=(5, 8))
    ttk.Button(frame, text="Elegir carpeta", command=callback,
               bootstyle="secondary outline").pack(anchor="w")
    return path


def _decorate_tk_widgets(app):
    """Mantiene lista y registro legibles al cambiar tema oscuro/claro."""
    mode = app.root.theme_mode
    dark = mode == "dark"
    surface = "#121F33" if dark else "#FFFFFF"
    fg = "#EDF6FF" if dark else "#1D3550"
    muted = "#A8B7CA" if dark else "#60728B"
    app.files_box.configure(
        bg=surface, fg=fg, highlightthickness=0, relief="flat",
        selectbackground="#126EB6", selectforeground="#FFFFFF",
        activestyle="none", bd=0,
    )
    app.log_text.configure(
        bg=surface, fg=muted, insertbackground=fg,
        highlightthickness=0, relief="flat",
    )
    app.theme_button.configure(
        text="☀ Tema claro" if dark else "☾ Tema oscuro"
    )


def toggle_theme(app):
    app.root.toggle_theme()
    _decorate_tk_widgets(app)
    app._save_config()


def build_interface(app):
    """Monta el panel, guardando los atributos que usa AppCardio."""
    root = app.root
    root.title("CPROT | QRS-Card · Gestión de impresión")
    root.geometry("1100x850")
    root.minsize(880, 720)

    header = tk.Frame(root, bg=NAVY, padx=24, pady=15, height=92)
    header.pack(fill="x")
    header.pack_propagate(False)

    brand = tk.Frame(header, bg=NAVY)
    brand.pack(side="left", fill="y")
    tk.Label(brand, text="▮ CPROT", bg=NAVY, fg=CYAN,
             font=("Segoe UI", 21, "bold")).pack(side="left")
    tk.Frame(brand, width=1, bg="#36506D").pack(side="left", fill="y", padx=16, pady=5)
    identity = tk.Frame(brand, bg=NAVY)
    identity.pack(side="left", anchor="center")
    tk.Label(identity, text="QRS-CARD", bg=NAVY, fg=WHITE,
             font=("Segoe UI", 15, "bold")).pack(anchor="w")
    tk.Label(identity, text="Gestor de impresión y estudios PDF",
             bg=NAVY, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
    right_brand = tk.Frame(header, bg=NAVY)
    right_brand.pack(side="right", fill="y")
    tk.Label(right_brand, text="SOLUCIÓN LOCAL · WINDOWS", bg=NAVY, fg=MUTED,
             font=("Segoe UI", 9, "bold")).pack(anchor="e", pady=(7, 2))
    app.header_status_label = tk.Label(
        right_brand, text="●  Vigilancia detenida", bg=NAVY,
        fg="#F6B94D", font=("Segoe UI", 10, "bold")
    )
    app.header_status_label.pack(anchor="e")

    body = ttk.Frame(root, padding=(19, 16, 19, 12))
    body.pack(fill="both", expand=True)
    body.columnconfigure(0, weight=1)
    body.rowconfigure(3, weight=5)
    body.rowconfigure(4, weight=2)

    hero = ttk.Frame(body)
    hero.grid(row=0, column=0, sticky="ew", pady=(0, 13))
    hero.columnconfigure(0, weight=1)
    title_stack = ttk.Frame(hero)
    title_stack.grid(row=0, column=0, sticky="w")
    ttk.Label(title_stack, text="Panel de operación",
              font=("Segoe UI", 18, "bold")).pack(anchor="w")
    ttk.Label(title_stack, text="Monitoriza la recepción de PDF y controla cada envío a la impresora.",
              bootstyle="secondary", font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))
    actions = ttk.Frame(hero)
    actions.grid(row=0, column=1, sticky="e")
    app.theme_button = ttk.Button(
        actions, text="☀ Tema claro", bootstyle="secondary outline",
        command=lambda: toggle_theme(app),
    )
    app.theme_button.pack(side="left", padx=(0, 8))
    app.run_button = ttk.Button(
        actions, text="▶  ACTIVAR VIGILANCIA", bootstyle="primary",
        command=app._start, width=23,
    )
    app.run_button.pack(side="left")

    metrics = ttk.Frame(body)
    metrics.grid(row=1, column=0, sticky="ew", pady=(0, 13))
    for c in range(3):
        metrics.columnconfigure(c, weight=1, uniform="stat")
    app.status_label = _card_metric(metrics, 0, "ESTADO DEL SERVICIO", "Detenido")
    app.metric_files = _card_metric(metrics, 1, "PDF EN CARPETA TEMPORAL", "0")
    app.metric_queue = _card_metric(metrics, 2, "TRABAJOS EN COLA", "0")

    settings = ttk.Labelframe(body, text="01  CONFIGURACIÓN", padding=13)
    settings.grid(row=2, column=0, sticky="ew", pady=(0, 12))
    settings.columnconfigure(0, weight=1, uniform="folders")
    settings.columnconfigure(1, weight=1, uniform="folders")
    folders = ttk.Frame(settings)
    folders.grid(row=0, column=0, columnspan=2, sticky="ew")
    folders.columnconfigure(0, weight=1, uniform="folder")
    folders.columnconfigure(1, weight=1, uniform="folder")
    app.origin_label = _folder_card(
        folders, 0, "ORIGEN · PDFCreator", "PDF recibidos para imprimir",
        "No se ha seleccionado una carpeta.", app._select_origin
    )
    app.destination_label = _folder_card(
        folders, 1, "DESTINO · Expedientes", "Archivo final de estudios",
        "No se ha seleccionado una carpeta.", app._select_destination
    )
    printer_row = ttk.Frame(settings)
    printer_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(11, 0))
    printer_row.columnconfigure(1, weight=1)
    ttk.Label(printer_row, text="Impresora de Windows",
              font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 14))
    app.printer_combo = ttk.Combobox(printer_row, state="readonly", width=48)
    app.printer_combo.grid(row=0, column=1, sticky="ew", padx=(0, 9))
    app.printer_combo.bind("<<ComboboxSelected>>", lambda _event: app._save_config())
    ttk.Button(printer_row, text="↻  Actualizar", bootstyle="secondary outline",
               command=app._list_printers).grid(row=0, column=2)
    app._list_printers()

    workspace = ttk.Frame(body)
    workspace.grid(row=3, column=0, sticky="nsew", pady=(0, 12))
    workspace.columnconfigure(0, weight=7)
    workspace.columnconfigure(1, weight=4)
    workspace.rowconfigure(0, weight=1)

    documents = ttk.Labelframe(workspace, text="02  ESTUDIOS DISPONIBLES", padding=12)
    documents.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    documents.columnconfigure(0, weight=1)
    documents.rowconfigure(1, weight=1)
    ttk.Label(documents, text="Selecciona uno o varios documentos para imprimir o archivar.",
              bootstyle="secondary", font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", pady=(0, 8))
    lst = ttk.Frame(documents)
    lst.grid(row=1, column=0, sticky="nsew")
    lst.columnconfigure(0, weight=1)
    lst.rowconfigure(0, weight=1)
    scrollbar = ttk.Scrollbar(lst, orient="vertical")
    app.files_box = tk.Listbox(
        lst, selectmode=tk.EXTENDED, exportselection=False, height=7,
        font=("Consolas", 10), yscrollcommand=scrollbar.set,
    )
    app.files_box.grid(row=0, column=0, sticky="nsew")
    scrollbar.configure(command=app.files_box.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    doc_actions = ttk.Frame(documents)
    doc_actions.grid(row=2, column=0, sticky="ew", pady=(11, 0))
    ttk.Button(doc_actions, text="↻  Actualizar lista", bootstyle="secondary outline",
               command=app._refresh_list).pack(side="left", padx=(0, 8))
    ttk.Button(doc_actions, text="Imprimir / reimprimir selección", bootstyle="info outline",
               command=app._print_selected).pack(side="left")

    file_patient = ttk.Labelframe(workspace, text="03  ARCHIVAR EN EXPEDIENTE", padding=14)
    file_patient.grid(row=0, column=1, sticky="nsew")
    ttk.Label(file_patient, text="Paso 1 · Seleccionar estudios",
              font=("Segoe UI", 11, "bold")).pack(anchor="w")
    ttk.Label(file_patient, wraplength=300, bootstyle="secondary",
              text="Selecciona únicamente los archivos del mismo paciente en la lista de la izquierda.").pack(anchor="w", pady=(3, 13))
    ttk.Label(file_patient, text="Paso 2 · Nombre del paciente",
              font=("Segoe UI", 11, "bold")).pack(anchor="w")
    app.patient_entry = ttk.Entry(file_patient, width=36)
    app.patient_entry.pack(fill="x", pady=(7, 13))
    ttk.Label(file_patient, text="Paso 3 · Confirmar expediente",
              font=("Segoe UI", 11, "bold")).pack(anchor="w")
    app.classify_button = ttk.Button(
        file_patient, text="Guardar estudios seleccionados",
        command=app._classify, bootstyle="success"
    )
    app.classify_button.pack(fill="x", pady=(8, 12))
    ttk.Separator(file_patient).pack(fill="x", pady=(0, 11))
    ttk.Label(
        file_patient,
        text="Seguridad: revisa el nombre del paciente y el documento antes de archivar. "
             "La aplicación no identifica pacientes automáticamente.",
        bootstyle="warning", wraplength=310, justify="left",
        font=("Segoe UI", 9),
    ).pack(anchor="w")

    history = ttk.Labelframe(body, text="04  ACTIVIDAD RECIENTE", padding=(10, 7))
    history.grid(row=4, column=0, sticky="nsew", pady=(0, 6))
    history.columnconfigure(0, weight=1)
    history.rowconfigure(0, weight=1)
    log_scroll = ttk.Scrollbar(history, orient="vertical")
    app.log_text = tk.Text(
        history, height=5, wrap="word",
        state="disabled", font=("Consolas", 9), padx=9, pady=7,
        yscrollcommand=log_scroll.set,
    )
    app.log_text.grid(row=0, column=0, sticky="nsew")
    log_scroll.configure(command=app.log_text.yview)
    log_scroll.grid(row=0, column=1, sticky="ns")

    footer = ttk.Frame(body)
    footer.grid(row=5, column=0, sticky="ew", pady=(2, 0))
    ttk.Label(footer, text="CPROT  •  Soluciones tecnológicas",
              bootstyle="secondary", font=("Segoe UI", 9, "bold")).pack(side="left")
    ttk.Label(
        footer,
        text="Enviado al spooler ≠ impresión física confirmada",
        bootstyle="warning", font=("Segoe UI", 9),
    ).pack(side="right")
    _decorate_tk_widgets(app)
