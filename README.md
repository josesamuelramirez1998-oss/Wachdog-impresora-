# 🏥 QRS-Card: Medical Print & File Manager

![Python](https://img.shields.io/badge/Python-3.x-blue?style=flat&logo=python)
![Windows](https://img.shields.io/badge/OS-Windows-green?style=flat&logo=windows)

Una solución puente (Bridge) automatizada para sistemas médicos heredados (Legacy EMR / ECG Software). 

Este software soluciona el problema de impresión y digitalización de programas médicos antiguos (como CardioScan o software de pruebas de esfuerzo) que no cuentan con exportación nativa a PDF y causan errores de desbordamiento de memoria (Memory Overflow) en impresoras de red al intentar procesar gráficos de alta densidad.

## ✨ Características Principales

* **Impresión Nativa y Optimizada:** Ya no depende de visores de terceros (como SumatraPDF). Utiliza `PyMuPDF` y la API gráfica de Windows (`win32ui`) para renderizar los PDFs a un máximo de 300 DPI, enviando archivos extremadamente ligeros a la impresora física.
* **Monitoreo en Tiempo Real (Watchdog):** Vigila una carpeta temporal y procesa cualquier estudio médico nuevo en milisegundos.
* **Sistema de Colas (Queue):** Imprime de forma ordenada, un archivo a la vez, garantizando cero bloqueos o pérdida de documentos.
* **Organizador de Expedientes:** Permite agrupar los estudios impresos y moverlos automáticamente a una carpeta definitiva con el nombre del paciente.
* **Interfaz Gráfica (GUI):** Interfaz limpia y sencilla construida con Tkinter.

---

## ⚙️ Requisitos Previos

1. **Python 3.x** instalado en el sistema.
2. **PDFCreator** (Recomendado: Versión Free 3.2 o 4.4, sin instalar software publicitario de terceros).

### Configuración obligatoria de PDFCreator
Para que el sistema sea 100% invisible y automatizado, PDFCreator debe configurarse como un "motor fantasma":
1. Abre PDFCreator > **Perfiles**.
2. Activa el **Guardado Automático (Automatic Saving)**.
3. En **Nombre de archivo**, coloca: `<DateTime>`
4. En **Carpeta de destino**, selecciona la misma ruta que usarás como "Carpeta Origen / Temporal" en este programa.
5. **Desmarca** las casillas de: "Abrir archivo después de guardarlo" y "Mostrar acciones rápidas".

---

## 🚀 Instalación

1. Clona este repositorio o descarga el archivo `print_manager.py`:
   ```bash
   git clone [https://github.com/TU_USUARIO/qrs-card-print-manager.git](https://github.com/TU_USUARIO/qrs-card-print-manager.git)