import os
import time
import json
import threading
import shutil
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from queue import Queue

import win32print
import win32con
import win32ui
from PIL import Image, ImageWin
import fitz  # PyMuPDF

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


CONFIG_FILE = "config_qrs.json"
DPI_RENDER = 300


class MonitorHandler(FileSystemEventHandler):
    def __init__(self, cola_impresion, log_func):
        self.cola_impresion = cola_impresion
        self.log = log_func

    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith(".pdf"):
            self.log(f"📥 Detectado: {os.path.basename(event.src_path)}")
            self.cola_impresion.put(event.src_path)


class AppCardio:
    def __init__(self, root):
        self.root = root
        self.root.title("QRS-Card: Puente de Impresión Nativo y Expedientes")
        self.root.geometry("650x650")

        self.ruta_origen = ""
        self.ruta_destino = ""
        self.cola_impresion = Queue()
        self.sistema_activo = False
        self.observer = None
        self.archivos_en_proceso = set()

        tk.Label(root, text="1. Configuración del Sistema", font=("Segoe UI", 12, "bold")).pack(pady=(10, 5))

        frame_rutas = tk.Frame(root, bg="#e1f5fe", padx=10, pady=5)
        frame_rutas.pack(fill="x", padx=20, pady=5)

        tk.Label(
            frame_rutas,
            text="Carpeta de Origen / Temporal (Donde guarda PDFCreator):",
            bg="#e1f5fe",
            font=("Arial", 9, "bold")
        ).pack(anchor="w")

        self.lbl_origen = tk.Label(
            frame_rutas,
            text="Ninguna seleccionada",
            fg="#01579b",
            bg="#e1f5fe",
            font=("Consolas", 9),
            wraplength=550,
            justify="left"
        )
        self.lbl_origen.pack(anchor="w", pady=2)

        tk.Button(
            frame_rutas,
            text="📁 Seleccionar Origen",
            command=self.seleccionar_origen,
            font=("Arial", 8)
        ).pack(anchor="e", pady=(0, 10))

        tk.Label(
            frame_rutas,
            text="Carpeta Destino Oficial (Donde se guardarán los pacientes):",
            bg="#e1f5fe",
            font=("Arial", 9, "bold")
        ).pack(anchor="w")

        self.lbl_destino = tk.Label(
            frame_rutas,
            text="Ninguna seleccionada",
            fg="#01579b",
            bg="#e1f5fe",
            font=("Consolas", 9),
            wraplength=550,
            justify="left"
        )
        self.lbl_destino.pack(anchor="w", pady=2)

        tk.Button(
            frame_rutas,
            text="📂 Seleccionar Destino",
            command=self.seleccionar_destino,
            font=("Arial", 8)
        ).pack(anchor="e")

        tk.Label(root, text="Seleccione su Impresora:", pady=5, font=("Arial", 10)).pack()

        try:
            self.impresoras = [
                p[2] for p in win32print.EnumPrinters(
                    win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
                )
            ]
        except Exception:
            self.impresoras = ["Error detectando impresoras"]

        self.combo = ttk.Combobox(root, values=self.impresoras, width=50, state="readonly")
        self.combo.pack(pady=5)

        self.btn_run = tk.Button(
            root,
            text="▶ ACTIVAR VIGILANCIA DE IMPRESIÓN",
            bg="#00C853",
            fg="white",
            font=("Segoe UI", 10, "bold"),
            command=self.activar
        )
        self.btn_run.pack(pady=10)

        tk.Frame(root, height=2, bd=1, relief="sunken").pack(fill="x", padx=20, pady=10)

        tk.Label(root, text="2. Clasificar Estudios del Paciente", font=("Segoe UI", 12, "bold")).pack()
        tk.Label(
            root,
            text="(Llenar al terminar la prueba para limpiar la carpeta temporal)",
            font=("Arial", 8)
        ).pack()

        frame_paciente = tk.Frame(root)
        frame_paciente.pack(pady=10)

        tk.Label(frame_paciente, text="Nombre del Paciente:").pack(side="left")

        self.entry_paciente = tk.Entry(frame_paciente, width=35)
        self.entry_paciente.pack(side="left", padx=5)

        tk.Button(
            frame_paciente,
            text="💾 Agrupar y Renombrar",
            bg="#FF9800",
            fg="white",
            font=("Segoe UI", 9, "bold"),
            command=self.clasificar_paciente
        ).pack(side="left")

        tk.Label(root, text="Historial de Eventos:", font=("Arial", 8)).pack(anchor="w", padx=20)

        self.txt_log = tk.Text(
            root,
            height=8,
            width=75,
            state="disabled",
            font=("Consolas", 8),
            bg="#f8f9fa"
        )
        self.txt_log.pack(padx=20, pady=5)

        self.cargar_config()
        self.root.protocol("WM_DELETE_WINDOW", self.cerrar_app)

    def log_msg(self, msg):
        self.root.after(0, self._log_msg_seguro, msg)

    def _log_msg_seguro(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        self.txt_log.config(state="normal")
        self.txt_log.insert(tk.END, f"[{timestamp}] {msg}\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state="disabled")

    def seleccionar_origen(self):
        carpeta = filedialog.askdirectory(title="Selecciona la carpeta temporal")
        if carpeta:
            self.ruta_origen = os.path.normpath(carpeta)
            self.lbl_origen.config(text=self.ruta_origen)
            self.guardar_config()

    def seleccionar_destino(self):
        carpeta = filedialog.askdirectory(title="Selecciona la carpeta oficial")
        if carpeta:
            self.ruta_destino = os.path.normpath(carpeta)
            self.lbl_destino.config(text=self.ruta_destino)
            self.guardar_config()

    def cargar_config(self):
        if not os.path.exists(CONFIG_FILE):
            return

        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.combo.set(data.get("impresora", ""))

            ruta_origen = data.get("ruta_origen", "")
            ruta_destino = data.get("ruta_destino", "")

            if ruta_origen and os.path.exists(ruta_origen):
                self.ruta_origen = ruta_origen
                self.lbl_origen.config(text=ruta_origen)

            if ruta_destino and os.path.exists(ruta_destino):
                self.ruta_destino = ruta_destino
                self.lbl_destino.config(text=ruta_destino)

        except Exception as e:
            self.log_msg(f"⚠️ No se pudo cargar configuración: {e}")

    def guardar_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "impresora": self.combo.get(),
                    "ruta_origen": self.ruta_origen,
                    "ruta_destino": self.ruta_destino
                }, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.log_msg(f"⚠️ No se pudo guardar configuración: {e}")

    def activar(self):
        if self.sistema_activo:
            return

        impresora = self.combo.get()

        if not impresora or not self.ruta_origen or not self.ruta_destino:
            messagebox.showwarning(
                "Atención",
                "Configure la impresora, la carpeta origen y la carpeta destino antes de iniciar."
            )
            return

        if not os.path.exists(self.ruta_origen):
            messagebox.showerror("Error", "La carpeta de origen no existe.")
            return

        if not os.path.exists(self.ruta_destino):
            messagebox.showerror("Error", "La carpeta destino no existe.")
            return

        self.guardar_config()
        self.sistema_activo = True

        self.btn_run.config(state="disabled", text="SISTEMA ACTIVO Y VIGILANDO", bg="#0277bd")
        self.combo.config(state="disabled")

        self.log_msg("🟢 Sistema iniciado. Motor Python activado.")

        threading.Thread(target=self.run_watchdog, daemon=True).start()
        threading.Thread(target=self.procesador_impresion, args=(impresora,), daemon=True).start()

    def run_watchdog(self):
        try:
            self.observer = Observer()
            handler = MonitorHandler(self.cola_impresion, self.log_msg)
            self.observer.schedule(handler, self.ruta_origen, recursive=False)
            self.observer.start()

            while self.sistema_activo:
                time.sleep(1)

        except Exception as e:
            self.log_msg(f"❌ Error en vigilancia: {e}")

        finally:
            if self.observer:
                self.observer.stop()
                self.observer.join()

    def archivo_esta_listo(self, filepath, timeout=20, intervalo=0.5):
        inicio = time.time()
        tamaño_anterior = -1

        while time.time() - inicio < timeout:
            try:
                if not os.path.exists(filepath):
                    return False

                tamaño_actual = os.path.getsize(filepath)

                if tamaño_actual > 0 and tamaño_actual == tamaño_anterior:
                    try:
                        with open(filepath, "rb"):
                            return True
                    except OSError:
                        pass

                tamaño_anterior = tamaño_actual
                time.sleep(intervalo)

            except OSError:
                time.sleep(intervalo)

        return False

    def procesador_impresion(self, impresora):
        while True:
            archivo = self.cola_impresion.get()
            nombre_arch = os.path.basename(archivo)
            self.archivos_en_proceso.add(archivo)

            try:
                self.log_msg(f"⏳ Preparando PDF: {nombre_arch}")

                if not self.archivo_esta_listo(archivo):
                    self.log_msg(f"❌ Error: {nombre_arch} está incompleto, bloqueado o dañado.")
                    continue

                self.log_msg(f"🖨️ Imprimiendo: {nombre_arch}")
                self.imprimir_pdf_nativo(archivo, impresora)

                self.log_msg(f"✅ Impreso con éxito: {nombre_arch}")

            except Exception as e:
                self.log_msg(f"❌ Error al imprimir {nombre_arch}: {e}")

            finally:
                self.archivos_en_proceso.discard(archivo)
                self.cola_impresion.task_done()
                time.sleep(0.5)

    def imprimir_pdf_nativo(self, ruta_pdf, nombre_impresora):
        doc = None
        hDC = None
        start_doc_iniciado = False

        try:
            doc = fitz.open(ruta_pdf)

            if len(doc) == 0:
                raise ValueError("El PDF no contiene páginas.")

            hDC = win32ui.CreateDC()
            hDC.CreatePrinterDC(nombre_impresora)

            hDC.StartDoc(os.path.basename(ruta_pdf))
            start_doc_iniciado = True

            ancho_impresora = hDC.GetDeviceCaps(win32con.HORZRES)
            alto_impresora = hDC.GetDeviceCaps(win32con.VERTRES)

            for num_pagina in range(len(doc)):
                pagina = doc.load_page(num_pagina)

                zoom = DPI_RENDER / 72
                matriz = fitz.Matrix(zoom, zoom)
                pix = pagina.get_pixmap(matrix=matriz, alpha=False)

                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                dib = ImageWin.Dib(img)

                escala = min(
                    ancho_impresora / pix.width,
                    alto_impresora / pix.height
                )

                nuevo_ancho = int(pix.width * escala)
                nuevo_alto = int(pix.height * escala)

                x = int((ancho_impresora - nuevo_ancho) / 2)
                y = int((alto_impresora - nuevo_alto) / 2)

                hDC.StartPage()

                dib.draw(
                    hDC.GetHandleOutput(),
                    (x, y, x + nuevo_ancho, y + nuevo_alto)
                )

                hDC.EndPage()

        finally:
            if hDC:
                try:
                    if start_doc_iniciado:
                        hDC.EndDoc()
                except Exception:
                    pass

                try:
                    hDC.DeleteDC()
                except Exception:
                    pass

            if doc:
                try:
                    doc.close()
                except Exception:
                    pass

    def limpiar_nombre_carpeta(self, nombre):
        caracteres_invalidos = '<>:"/\\|?*'
        for c in caracteres_invalidos:
            nombre = nombre.replace(c, "_")
        return nombre.strip()

    def clasificar_paciente(self):
        nombre_paciente = self.entry_paciente.get().strip()

        if not nombre_paciente:
            messagebox.showwarning("Falta Dato", "Escriba el nombre del paciente antes de clasificar.")
            return

        if not self.ruta_origen or not self.ruta_destino:
            messagebox.showwarning("Falta Configuración", "Las rutas de origen y destino deben estar configuradas.")
            return

        nombre_paciente = self.limpiar_nombre_carpeta(nombre_paciente)

        archivos_temporales = [
            f for f in os.listdir(self.ruta_origen)
            if f.lower().endswith(".pdf")
        ]

        if not archivos_temporales:
            messagebox.showinfo(
                "Sin archivos",
                "No hay estudios en la carpeta temporal para clasificar."
            )
            return

        carpeta_paciente = os.path.join(self.ruta_destino, nombre_paciente)
        os.makedirs(carpeta_paciente, exist_ok=True)

        exitosos = 0

        for i, archivo in enumerate(archivos_temporales, 1):
            ruta_actual = os.path.join(self.ruta_origen, archivo)

            if ruta_actual in self.archivos_en_proceso:
                self.log_msg(f"⚠️ {archivo} todavía se está imprimiendo. Se omitió.")
                continue

            if not self.archivo_esta_listo(ruta_actual, timeout=3):
                self.log_msg(f"⚠️ {archivo} está en uso o incompleto. Se omitió.")
                continue

            nuevo_nombre = f"{nombre_paciente}_Estudio_{i}.pdf"
            ruta_final = os.path.join(carpeta_paciente, nuevo_nombre)

            contador = 1
            while os.path.exists(ruta_final):
                nuevo_nombre = f"{nombre_paciente}_Estudio_{i}_{contador}.pdf"
                ruta_final = os.path.join(carpeta_paciente, nuevo_nombre)
                contador += 1

            try:
                shutil.move(ruta_actual, ruta_final)
                exitosos += 1
            except Exception as e:
                self.log_msg(f"⚠️ No se pudo mover {archivo}: {e}")

        self.log_msg(f"📂 Se guardaron {exitosos} estudio(s) de {nombre_paciente}.")
        self.entry_paciente.delete(0, tk.END)

        messagebox.showinfo(
            "Éxito",
            f"Se ha creado/actualizado el expediente de:\n{nombre_paciente}\n\nArchivos guardados: {exitosos}"
        )

    def cerrar_app(self):
        self.sistema_activo = False

        try:
            if self.observer:
                self.observer.stop()
        except Exception:
            pass

        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = AppCardio(root)
    root.mainloop()