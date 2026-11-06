"""QRS-Card: captura de PDFCreator, cola de impresión y archivo clínico.

Windows únicamente. Los trabajos se envían al spooler (no se confirma
automáticamente que el papel haya salido o que la impresora esté en línea).
"""
from __future__ import annotations

import json
import math
import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import fitz
import win32con
import win32print
import win32ui
from PIL import Image, ImageWin
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from print_core import (
    PrintRegistry, file_signature, move_study, patient_folder_name, pdf_files, wait_for_ready_pdf,
)

APP_FOLDER = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "QRS-Card"
CONFIG_FILE = APP_FOLDER / "config_qrs.json"
LEDGER_FILE = APP_FOLDER / "print_jobs.json"
DPI_RENDER = 300
MAX_RENDER_PIXELS = 12_000_000
MAX_RENDER_SIDE = 6000


class PrinterJobError(RuntimeError):
    """Si may_have_printed es True, no reintentar automáticamente."""

    def __init__(self, message: str, *, may_have_printed: bool):
        super().__init__(message)
        self.may_have_printed = may_have_printed


class MonitorHandler(FileSystemEventHandler):
    def __init__(self, on_pdf):
        self.on_pdf = on_pdf

    def _detect(self, path: str) -> None:
        if path.lower().endswith(".pdf"):
            self.on_pdf(path)

    def on_created(self, event):
        if not event.is_directory:
            self._detect(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._detect(event.dest_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._detect(event.src_path)


def pdf_is_complete(path: Path) -> bool:
    """Exige un marcador EOF y una estructura PDF legible."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            if size < 20:
                return False
            handle.seek(max(0, size - 4096))
            if b"%%EOF" not in handle.read():
                return False
        with fitz.open(path) as doc:
            return doc.page_count > 0 and not doc.needs_pass
    except (OSError, RuntimeError, ValueError, fitz.FileDataError):
        return False


def print_pdf_to_spooler(path: Path, printer: str) -> int:
    """Rasteriza cada página bajo límites de memoria y la entrega a Windows.

    EndDoc confirma aceptación por la cola de impresión, NO impresión física.
    Un error tras intentar StartDoc se considera de resultado incierto.
    """
    dc = None
    doc = None
    attempted_doc = False
    started_doc = False
    try:
        doc = fitz.open(path)
        if doc.needs_pass or doc.page_count < 1:
            raise ValueError("El PDF está protegido o no contiene páginas.")

        dc = win32ui.CreateDC()
        dc.CreatePrinterDC(printer)
        page_w = dc.GetDeviceCaps(win32con.HORZRES)
        page_h = dc.GetDeviceCaps(win32con.VERTRES)
        if page_w <= 0 or page_h <= 0:
            raise ValueError("El controlador de impresora no informa un área imprimible válida.")

        attempted_doc = True
        dc.StartDoc(path.name)
        started_doc = True
        for number in range(doc.page_count):
            page = doc.load_page(number)
            rect = page.rect
            if rect.width <= 0 or rect.height <= 0:
                raise ValueError(f"Página {number + 1} con dimensiones inválidas.")
            zoom = min(
                DPI_RENDER / 72.0,
                MAX_RENDER_SIDE / max(rect.width, rect.height),
                math.sqrt(MAX_RENDER_PIXELS / (rect.width * rect.height)),
            )
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False, colorspace=fitz.csRGB)
            if pix.width < 1 or pix.height < 1:
                raise ValueError(f"Página {number + 1} vacía.")
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            scale = min(page_w / pix.width, page_h / pix.height)
            width = max(1, int(pix.width * scale))
            height = max(1, int(pix.height * scale))
            x = (page_w - width) // 2
            y = (page_h - height) // 2

            dc.StartPage()
            ImageWin.Dib(image).draw(dc.GetHandleOutput(), (x, y, x + width, y + height))
            dc.EndPage()
            image.close()
            del pix

        dc.EndDoc()
        started_doc = False
        return doc.page_count
    except Exception as exc:
        uncertain = attempted_doc
        if started_doc and dc is not None:
            try:
                dc.AbortDoc()
            except Exception:
                pass
        raise PrinterJobError(str(exc), may_have_printed=uncertain) from exc
    finally:
        if dc is not None:
            try:
                dc.DeleteDC()
            except Exception:
                pass
        if doc is not None:
            doc.close()


class AppCardio:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("QRS-Card · Vigilancia de impresión y expedientes")
        self.root.geometry("780x795")
        self.root.minsize(700, 680)

        self.origin = ""
        self.destination = ""
        self.active = False
        self.stop = threading.Event()
        self.observer = None
        self.worker = None
        self.work_queue: queue.Queue = queue.Queue()
        self.ui_queue: queue.Queue = queue.Queue()
        self.retry_after: dict[str, float] = {}
        self.listed: list[Path] = []
        self.classifying = False
        self.closing = False
        try:
            self.registry = PrintRegistry(LEDGER_FILE)
            self.registry_error = ""
        except ValueError as exc:
            # No reiniciar la bitácora y arriesgar una impresión duplicada.
            self.registry = None
            self.registry_error = str(exc)

        self._build_ui()
        self._load_config()
        self._refresh_list()
        self.root.after(150, self._drain_ui)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        if self.registry_error:
            self.root.after(300, lambda: messagebox.showerror("Bitácora dañada", self.registry_error))

    def _build_ui(self):
        from cprot_ui import build_interface
        build_interface(self)

    def _post(self, kind: str, value):
        self.ui_queue.put((kind, value))

    def _log(self, msg: str):
        self._post("log", msg)

    def _drain_ui(self):
        if self.closing:
            return
        for _ in range(80):
            try:
                kind, value = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.log_text.configure(state="normal")
                self.log_text.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {value}\n")
                # Limita la memoria de la interfaz durante jornadas largas.
                if int(self.log_text.index("end-1c").split(".")[0]) > 600:
                    self.log_text.delete("1.0", "101.0")
                self.log_text.see(tk.END)
                self.log_text.configure(state="disabled")
            elif kind == "refresh":
                self._refresh_list()
            elif kind == "fatal":
                self.active = False
                self.stop.set()
                if self.observer:
                    self.observer.stop()
                self.run_button.configure(state="disabled", text="Vigilancia detenida (error de bitácora)")
                self.status_label.configure(text="Error de bitácora")
                self.header_status_label.configure(text="●  Error de bitácora", fg="#F15B67")
                messagebox.showerror("Vigilancia detenida", value)
            elif kind == "classified":
                self.classifying = False
                self.classify_button.configure(state="normal")
                self._refresh_list()
                moved, skipped = value
                messagebox.showinfo("Clasificación terminada",
                                    f"Archivos archivados: {moved}\nOmitidos / fallidos: {skipped}")
        self.root.after(150, self._drain_ui)

    def _list_printers(self):
        previous = self.printer_combo.get()
        try:
            names = [
                entry[2] for entry in win32print.EnumPrinters(
                    win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
                )
            ]
            names = sorted(set(names), key=str.casefold)
        except Exception as exc:
            names = []
            self._log(f"⚠️ No se pudo consultar impresoras: {exc}")
        self.printer_combo.configure(values=names)
        if previous in names:
            self.printer_combo.set(previous)
        else:
            try:
                default = win32print.GetDefaultPrinter()
                self.printer_combo.set(default if default in names else "")
            except Exception:
                self.printer_combo.set("")

    def _select_origin(self):
        if self.active or self.classifying:
            messagebox.showwarning("Vigilancia activa", "Detenga y reinicie la aplicación antes de cambiar las carpetas.")
            return
        chosen = filedialog.askdirectory(title="Carpeta temporal donde guarda PDFCreator")
        if chosen:
            self.origin = os.path.normpath(chosen)
            self.origin_label.configure(text=f"Origen: {self.origin}")
            self._save_config()
            self._refresh_list()

    def _select_destination(self):
        if self.active or self.classifying:
            messagebox.showwarning("Vigilancia activa", "Detenga y reinicie la aplicación antes de cambiar las carpetas.")
            return
        chosen = filedialog.askdirectory(title="Carpeta oficial para expedientes")
        if chosen:
            self.destination = os.path.normpath(chosen)
            self.destination_label.configure(text=f"Expedientes: {self.destination}")
            self._save_config()

    def _load_config(self):
        legacy = Path("config_qrs.json")
        source = CONFIG_FILE if CONFIG_FILE.exists() else legacy
        if not source.exists():
            return
        try:
            settings = json.loads(source.read_text(encoding="utf-8"))
            self.origin = settings.get("ruta_origen", "")
            self.destination = settings.get("ruta_destino", "")
            if self.origin and Path(self.origin).is_dir():
                self.origin_label.configure(text=f"Origen: {self.origin}")
            else:
                self.origin = ""
            if self.destination and Path(self.destination).is_dir():
                self.destination_label.configure(text=f"Expedientes: {self.destination}")
            else:
                self.destination = ""
            selected_theme = settings.get("tema", "")
            if selected_theme in ("cprot-dark", "cprot-light"):
                self.root.theme_use(selected_theme)
                from cprot_ui import _decorate_tk_widgets
                _decorate_tk_widgets(self)
            name = settings.get("impresora", "")
            if name in self.printer_combo["values"]:
                self.printer_combo.set(name)
        except (OSError, ValueError, AttributeError) as exc:
            self._log(f"⚠️ No se pudo cargar configuración: {exc}")

    def _save_config(self):
        try:
            APP_FOLDER.mkdir(parents=True, exist_ok=True)
            tempfile = CONFIG_FILE.with_suffix(".json.tmp")
            tempfile.write_text(json.dumps({
                "impresora": self.printer_combo.get(),
                "ruta_origen": self.origin,
                "ruta_destino": self.destination,
                "tema": self.root.theme_use(),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tempfile, CONFIG_FILE)
        except OSError as exc:
            self._log(f"⚠️ No se pudo guardar configuración: {exc}")

    def _refresh_list(self):
        previous = {
            self.listed[index].name for index in self.files_box.curselection()
            if index < len(self.listed)
        }
        self.listed = pdf_files(self.origin) if self.origin else []
        self.files_box.delete(0, tk.END)
        for idx, path in enumerate(self.listed):
            status = self.registry.status(path) if self.registry else "Registro no disponible"
            self.files_box.insert(tk.END, f"{path.name}   [{status}]")
            if path.name in previous:
                self.files_box.selection_set(idx)
        self.metric_files.configure(text=str(len(self.listed)))
        self.metric_queue.configure(text=str(self.work_queue.qsize()))

    def _start(self):
        if self.active:
            return
        if self.registry is None:
            messagebox.showerror("Bitácora inválida", self.registry_error)
            return
        if not self.origin or not Path(self.origin).is_dir():
            messagebox.showwarning("Origen", "Seleccione una carpeta temporal existente.")
            return
        if not self.destination or not Path(self.destination).is_dir():
            messagebox.showwarning("Destino", "Seleccione una carpeta de expedientes existente.")
            return
        if Path(self.origin).resolve() == Path(self.destination).resolve():
            messagebox.showerror("Rutas inválidas", "El origen y el destino no pueden ser la misma carpeta.")
            return
        if self.printer_combo.get() not in self.printer_combo["values"]:
            messagebox.showwarning("Impresora", "Seleccione una impresora válida de Windows.")
            return

        self.stop.clear()
        try:
            self.observer = Observer()
            self.observer.schedule(MonitorHandler(self._enqueue_event), self.origin, recursive=False)
            self.observer.start()
        except Exception as exc:
            if self.observer:
                try:
                    self.observer.stop()
                except Exception:
                    pass
            messagebox.showerror("Watchdog", f"No se pudo iniciar el monitor:\n{exc}")
            return

        self.active = True
        self.selected_printer = self.printer_combo.get()
        self.worker = threading.Thread(target=self._worker, name="qrs-print-worker", daemon=True)
        self.worker.start()
        self.run_button.configure(state="disabled", text="✓ Vigilancia activa")
        self.printer_combo.configure(state="disabled")
        self.status_label.configure(text="Vigilancia activa")
        self.header_status_label.configure(text="●  Vigilando documentos", fg="#12B886")
        self._save_config()
        self._log("🟢 Vigilancia activada. Los PDF existentes NO se reimprimen automáticamente.")
        self._refresh_list()

    def _enqueue_event(self, path: str):
        if not self.active or self.stop.is_set() or self.registry is None:
            return
        p = Path(path)
        try:
            if p.parent.resolve() != Path(self.origin).resolve() or p.suffix.lower() != ".pdf":
                return
        except OSError:
            return
        now = time.monotonic()
        key = os.path.normcase(os.path.abspath(path))
        if self.retry_after.get(key, 0) > now:
            return
        token = self.registry.claim(p)
        if token is None:
            return
        self.work_queue.put((p, token, False))
        self._log(f"📥 PDF detectado: {p.name}")
        self._post("refresh", None)

    def _print_selected(self):
        if not self.active:
            messagebox.showwarning("Vigilancia detenida", "Active primero la vigilancia.")
            return
        indexes = self.files_box.curselection()
        if not indexes:
            messagebox.showwarning("Seleccione archivos", "Seleccione al menos un PDF en la lista.")
            return
        choices = [self.listed[i] for i in indexes]
        if not messagebox.askyesno(
            "Confirmar impresión",
            f"¿Enviar {len(choices)} PDF seleccionado(s) a la impresora?\n"
            "Los documentos ya enviados podrán IMPRIMIRSE OTRA VEZ.",
        ):
            return
        for path in choices:
            token = self.registry.claim(path, force=True)
            if token:
                self.work_queue.put((path, token, True))
            else:
                self._log(f"⚠️ {path.name}: ya está pendiente o no existe.")
        self._refresh_list()

    def _worker(self):
        while not self.stop.is_set():
            try:
                path, token, manual = self.work_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                self._log(f"⏳ Esperando PDF completo: {path.name}")
                if not wait_for_ready_pdf(path, pdf_is_complete, timeout=45, stop=self.stop):
                    if not self.stop.is_set():
                        self.retry_after[token[0]] = time.monotonic() + 10
                        self._log(f"⚠️ {path.name}: PDF no listo tras 45 s. "
                                  "Puede recuperarlo con «Imprimir seleccionados».")
                    continue
                # La primera firma pudo corresponder a un PDF aún escribiéndose.
                # Registrar la versión validada evita duplicados tras reinicios.
                final_token = (token[0], file_signature(path))
                if not manual and self.registry.was_handled(final_token):
                    self._log(f"ℹ️ {path.name}: ya enviado o pendiente de revisión. Omitido.")
                    continue
                self._log(f"🖨️ Enviando: {path.name}")
                try:
                    page_count = print_pdf_to_spooler(path, self.selected_printer)
                except PrinterJobError as exc:
                    if exc.may_have_printed:
                        try:
                            self.registry.record(final_token, uncertain=True)
                        except OSError as write_error:
                            self._log(f"❌ No se pudo persistir el estado: {write_error}")
                            self._post("fatal", f"No se pudo guardar el resultado incierto de {path.name}.\nNo reimprima sin comprobar primero la cola de Windows.\n\n{write_error}")
                        self._log(f"⚠️ Resultado incierto de {path.name}: {exc}. "
                                  "Verifique la impresora antes de reintentar.")
                    else:
                        self.retry_after[token[0]] = time.monotonic() + 10
                        self._log(f"❌ No se pudo imprimir {path.name}: {exc}")
                    continue
                try:
                    self.registry.record(final_token)
                    self._log(f"✅ {path.name}: {page_count} página(s) ENVIADAS a cola Windows.")
                except OSError as exc:
                    self._log(f"⚠️ Se envió a la impresora, pero falló la bitácora: {exc}. "
                              "EVITE reimprimir sin verificar primero.")
                    self._post("fatal", f"No se pudo guardar la bitácora del documento {path.name}.\nRevise la cola de impresión antes de reintentar.\n\n{exc}")
            except Exception as exc:
                self.retry_after[token[0]] = time.monotonic() + 10
                self._log(f"❌ Error inesperado al procesar {path.name}: {exc}")
            finally:
                self.registry.release(token)
                self.work_queue.task_done()
                self._post("refresh", None)

    def _classify(self):
        if self.classifying:
            return
        indexes = self.files_box.curselection()
        if not indexes:
            messagebox.showwarning("Estudios", "Seleccione únicamente los archivos de este paciente.")
            return
        if not self.destination or not Path(self.destination).is_dir():
            messagebox.showwarning("Destino", "Seleccione una carpeta válida para expedientes.")
            return
        try:
            name = patient_folder_name(self.patient_entry.get())
        except ValueError as exc:
            messagebox.showwarning("Nombre del paciente", str(exc))
            return
        chosen = [self.listed[i] for i in indexes]
        uncertain = [
            p.name for p in chosen if self.registry and
            self.registry.status(p) != "Enviado a impresora"
        ]
        warning = (
            f"Guardar {len(chosen)} PDF en la carpeta:\n{name}\n\n"
            "Confirme que TODOS pertenecen al mismo paciente."
        )
        if uncertain:
            warning += (
                "\n\nATENCIÓN: estos archivos no constan como enviados al spooler "
                "(o tienen resultado incierto):\n" +
                "\n".join(uncertain[:8]) +
                ("\n..." if len(uncertain) > 8 else "") +
                "\nRevise si deben imprimirse primero."
            )
        if not messagebox.askyesno("Verificar asociación del paciente", warning):
            return

        reserved = []
        for path in chosen:
            token = self.registry.claim(path, force=True) if self.registry else None
            if token:
                reserved.append((path, token))
            else:
                self._log(f"⚠️ No se puede archivar {path.name}: pendiente de impresión o no disponible.")
        if not reserved:
            return
        self.classifying = True
        self.classify_button.configure(state="disabled")
        threading.Thread(
            target=self._archive_worker, args=(name, reserved, len(chosen)-len(reserved)),
            daemon=True, name="qrs-archive-worker",
        ).start()

    def _archive_worker(self, patient: str, selected, skipped: int):
        moved = 0
        try:
            for path, token in selected:
                try:
                    if not wait_for_ready_pdf(path, pdf_is_complete, timeout=8, stop=self.stop):
                        skipped += 1
                        self._log(f"⚠️ {path.name} sigue incompleto o no está disponible.")
                        continue
                    result = move_study(path, self.destination, patient, moved + 1)
                    moved += 1
                    self._log(f"📁 Archivado: {path.name} → {result.name}")
                except Exception as exc:
                    skipped += 1
                    self._log(f"❌ No se pudo archivar {path.name}: {exc}")
                finally:
                    self.registry.release(token)
        finally:
            self._post("classified", (moved, skipped))

    def _close(self):
        if self.closing:
            return
        if self.registry and self.registry.pending:
            if not messagebox.askyesno(
                "Trabajos activos",
                "Hay documentos imprimiéndose o archivándose.\n"
                "Cerrar ahora puede interrumpir el envío a la impresora o el archivado.\n\n"
                "¿Cerrar de todos modos? Se recomienda esperar.",
            ):
                return
        self.closing = True
        self.active = False
        self.stop.set()
        if self.observer:
            try:
                self.observer.stop()
            except Exception:
                pass
        self.root.destroy()


if __name__ == "__main__":
    from cprot_ui import make_root
    root = make_root()
    AppCardio(root)
    root.mainloop()
