import os
import time
import json
import threading
import shutil
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# Nuevas librerías para impresión nativa
import win32print
import win32con
import win32ui
from PIL import Image, ImageWin
import fitz  # PyMuPDF

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from queue import Queue

# --- CONFIGURACIÓN ESTÁTICA ---
CONFIG_FILE = "config_qrs.json"

class MonitorHandler(FileSystemEventHandler):
    def __init__(self, cola_impresion, log_func):
        self.cola_impresion = cola_impresion
        self.log = log_func

    def on_created(self, event):
        # Detectamos solo archivos PDF en la carpeta y los mandamos a la fila
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
        
        # --- SECCIÓN 1: CONFIGURACIÓN DE CARPETAS E IMPRESORA ---
        tk.Label(root, text="1. Configuración del Sistema", font=("Segoe UI", 12, "bold")).pack(pady=(10, 5))
        
        frame_rutas = tk.Frame(root, bg="#e1f5fe", padx=10, pady=5)
        frame_rutas.pack(fill="x", padx=20, pady=5)
        
        # Carpeta Origen
        tk.Label(frame_rutas, text="Carpeta de Origen / Temporal (Donde guarda PDFCreator):", bg="#e1f5fe", font=("Arial", 9, "bold")).pack(anchor="w")
        self.lbl_origen = tk.Label(frame_rutas, text="Ninguna seleccionada", fg="#01579b", bg="#e1f5fe", font=("Consolas", 9), wraplength=550, justify="left")
        self.lbl_origen.pack(anchor="w", pady=2)
        tk.Button(frame_rutas, text="📁 Seleccionar Origen", command=self.seleccionar_origen, font=("Arial", 8)).pack(anchor="e", pady=(0, 10))

        # Carpeta Destino
        tk.Label(frame_rutas, text="Carpeta Destino Oficial (Donde se guardarán los pacientes):", bg="#e1f5fe", font=("Arial", 9, "bold")).pack(anchor="w")
        self.lbl_destino = tk.Label(frame_rutas, text="Ninguna seleccionada", fg="#01579b", bg="#e1f5fe", font=("Consolas", 9), wraplength=550, justify="left")
        self.lbl_destino.pack(anchor="w", pady=2)
        tk.Button(frame_rutas, text="📂 Seleccionar Destino", command=self.seleccionar_destino, font=("Arial", 8)).pack(anchor="e")

        # Impresora
        tk.Label(root, text="Seleccione su Impresora:", pady=5, font=("Arial", 10)).pack()
        try:
            self.impresoras = [p[2] for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)]
        except:
            self.impresoras = ["Error detectando impresoras"]

        self.combo = ttk.Combobox(root, values=self.impresoras, width=50, state="readonly")
        self.combo.pack(pady=5)

        self.btn_run = tk.Button(root, text="▶ ACTIVAR VIGILANCIA DE IMPRESIÓN", bg="#00C853", fg="white", font=("Segoe UI", 10, "bold"), command=self.activar)
        self.btn_run.pack(pady=10)

        tk.Frame(root, height=2, bd=1, relief="sunken").pack(fill="x", padx=20, pady=10)

        # --- SECCIÓN 2: GESTIÓN DE PACIENTES ---
        tk.Label(root, text="2. Clasificar Estudios del Paciente", font=("Segoe UI", 12, "bold")).pack()
        tk.Label(root, text="(Llenar al terminar la prueba de esfuerzo para limpiar la carpeta temporal)", font=("Arial", 8)).pack()
        
        frame_paciente = tk.Frame(root)
        frame_paciente.pack(pady=10)
        
        tk.Label(frame_paciente, text="Nombre del Paciente:").pack(side="left")
        self.entry_paciente = tk.Entry(frame_paciente, width=35)
        self.entry_paciente.pack(side="left", padx=5)
        
        tk.Button(frame_paciente, text="💾 Agrupar y Renombrar", bg="#FF9800", fg="white", font=("Segoe UI", 9, "bold"), command=self.clasificar_paciente).pack(side="left")

        # --- SECCIÓN 3: LOG DE EVENTOS ---
        tk.Label(root, text="Historial de Eventos:", font=("Arial", 8)).pack(anchor="w", padx=20)
        self.txt_log = tk.Text(root, height=8, width=75, state="disabled", font=("Consolas", 8), bg="#f8f9fa")
        self.txt_log.pack(padx=20, pady=5)
        
        self.cargar_config()

    def log_msg(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        self.txt_log.config(state="normal")
        self.txt_log.insert(tk.END, f"[{timestamp}] {msg}\n")
        self.txt_log.see(tk.END)
        self.txt_log.config(state="disabled")

    def seleccionar_origen(self):
        carpeta = filedialog.askdirectory(title="Selecciona la carpeta temporal (Origen)")
        if carpeta:
            self.ruta_origen = os.path.normpath(carpeta)
            self.lbl_origen.config(text=self.ruta_origen)
            self.guardar_config()

    def seleccionar_destino(self):
        carpeta = filedialog.askdirectory(title="Selecciona la carpeta oficial (Destino)")
        if carpeta:
            self.ruta_destino = os.path.normpath(carpeta)
            self.lbl_destino.config(text=self.ruta_destino)
            self.guardar_config()

    def cargar_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    self.combo.set(data.get("impresora", ""))
                    
                    if data.get("ruta_origen") and os.path.exists(data.get("ruta_origen")):
                        self.ruta_origen = data["ruta_origen"]
                        self.lbl_origen.config(text=self.ruta_origen)
                        
                    if data.get("ruta_destino") and os.path.exists(data.get("ruta_destino")):
                        self.ruta_destino = data["ruta_destino"]
                        self.lbl_destino.config(text=self.ruta_destino)
            except: pass

    def guardar_config(self):
        with open(CONFIG_FILE, "w") as f:
            json.dump({
                "impresora": self.combo.get(),
                "ruta_origen": self.ruta_origen,
                "ruta_destino": self.ruta_destino
            }, f)

    def activar(self):
        if self.sistema_activo: return
        
        impresora = self.combo.get()
        if not impresora or not self.ruta_origen or not self.ruta_destino:
            messagebox.showwarning("Atención", "Configure la impresora, la carpeta origen y la carpeta destino antes de iniciar.")
            return

        self.guardar_config()
        self.sistema_activo = True
        
        self.btn_run.config(state="disabled", text="SISTEMA ACTIVO Y VIGILANDO", bg="#0277bd")
        self.combo.config(state="disabled")
        
        self.log_msg("🟢 Sistema iniciado. Motor Python activado.")
        
        # Hilos en segundo plano para no congelar la interfaz
        threading.Thread(target=self.run_watchdog, daemon=True).start()
        threading.Thread(target=self.procesador_impresion, args=(impresora,), daemon=True).start()

    def run_watchdog(self):
        observer = Observer()
        handler = MonitorHandler(self.cola_impresion, self.log_msg)
        observer.schedule(handler, self.ruta_origen, recursive=False)
        observer.start()
        try:
            while True: time.sleep(1)
        except: observer.stop()

    def archivo_esta_listo(self, filepath, timeout=15):
        """Intenta renombrar el archivo a sí mismo para verificar si PDFCreator ya lo soltó."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                os.rename(filepath, filepath)
                return True
            except OSError:
                time.sleep(0.5)
        return False

    def procesador_impresion(self, impresora):
        """Sistema de fila: imprime un archivo a la vez usando solo Python."""
        while True:
            archivo = self.cola_impresion.get()
            nombre_arch = os.path.basename(archivo)
            
            self.log_msg(f"⏳ Renderizando: {nombre_arch}...")
            
            # Asegurar que el archivo esté completo antes de enviarlo
            if not self.archivo_esta_listo(archivo):
                self.log_msg(f"❌ Error: {nombre_arch} está dañado o bloqueado.")
                self.cola_impresion.task_done()
                continue
                
            try:
                self.imprimir_pdf_nativo(archivo, impresora)
                self.log_msg(f"✅ ¡Impreso con éxito: {nombre_arch}!")
            except Exception as e:
                self.log_msg(f"❌ Error al imprimir: {e}")
            
            self.cola_impresion.task_done()
            time.sleep(0.5) # Pausa ligera entre cada impresión

    def imprimir_pdf_nativo(self, ruta_pdf, nombre_impresora):
        """
        Abre el PDF, lo renderiza a 300 DPI y lo envía directo al Spooler de Windows.
        Esto soluciona el desbordamiento de memoria de las impresoras.
        """
        # 1. Abrir el documento PDF
        doc = fitz.open(ruta_pdf)
        
        # 2. Conectar a la impresora mediante la API de Windows
        hDC = win32ui.CreateDC()
        hDC.CreatePrinterDC(nombre_impresora)
        hDC.StartDoc(ruta_pdf)
        
        # 3. Obtener los límites físicos del papel en la impresora
        ancho_impresora = hDC.GetDeviceCaps(win32con.HORZRES)
        alto_impresora = hDC.GetDeviceCaps(win32con.VERTRES)
        
        # 4. Procesar y enviar hoja por hoja
        for num_pagina in range(len(doc)):
            hDC.StartPage()
            pagina = doc.load_page(num_pagina)
            
            # Definir la resolución a 300 DPI (300 / 72 = 4.16 zoom)
            zoom = 300 / 72 
            matriz = fitz.Matrix(zoom, zoom)
            
            # Convertir la hoja del PDF a pixeles
            pix = pagina.get_pixmap(matrix=matriz, alpha=False)
            
            # Transformar a una imagen compatible con el sistema Windows
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            dib = ImageWin.Dib(img)
            
            # Dibujar la imagen sobre el lienzo de la impresora
            dib.draw(hDC.GetHandleOutput(), (0, 0, ancho_impresora, alto_impresora))
            
            hDC.EndPage()
            
        # Cerrar y liberar la memoria
        hDC.EndDoc()
        hDC.DeleteDC()
        doc.close()

    def clasificar_paciente(self):
        """Mueve los PDFs impresos de la carpeta temporal a su carpeta final con el nombre del paciente."""
        nombre_paciente = self.entry_paciente.get().strip()
        
        if not nombre_paciente:
            messagebox.showwarning("Falta Dato", "Escriba el nombre del paciente antes de clasificar.")
            return
            
        if not self.ruta_origen or not self.ruta_destino:
            messagebox.showwarning("Falta Configuración", "Las rutas de origen y destino deben estar configuradas.")
            return

        archivos_temporales = [f for f in os.listdir(self.ruta_origen) if f.lower().endswith('.pdf')]
        
        if not archivos_temporales:
            messagebox.showinfo("Sin archivos", "No hay estudios en la carpeta temporal (Origen) para clasificar.")
            return

        # Crear carpeta final del paciente
        carpeta_paciente = os.path.join(self.ruta_destino, nombre_paciente)
        os.makedirs(carpeta_paciente, exist_ok=True)

        # Mover y renombrar los archivos
        exitosos = 0
        for i, archivo in enumerate(archivos_temporales, 1):
            ruta_actual = os.path.join(self.ruta_origen, archivo)
            
            # Nos aseguramos de no mover archivos que todavía se estén imprimiendo
            if self.archivo_esta_listo(ruta_actual, timeout=2):
                nuevo_nombre = f"{nombre_paciente}_Estudio_{i}.pdf"
                ruta_final = os.path.join(carpeta_paciente, nuevo_nombre)
                
                try:
                    shutil.move(ruta_actual, ruta_final)
                    exitosos += 1
                except Exception as e:
                    self.log_msg(f"⚠️ No se pudo mover {archivo}: {e}")
            else:
                self.log_msg(f"⚠️ {archivo} está en uso, omitiendo por ahora.")
            
        self.log_msg(f"📂 ¡Se guardaron {exitosos} estudios de {nombre_paciente}!")
        self.entry_paciente.delete(0, tk.END)
        messagebox.showinfo("Éxito", f"Se ha creado el expediente de:\n{nombre_paciente}\ncon {exitosos} archivo(s).")

if __name__ == "__main__":
    root = tk.Tk()
    app = AppCardio(root)
    root.mainloop()