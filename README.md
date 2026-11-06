# QRS-Card — watchdog de impresión y expedientes PDF

Aplicación local para **Windows** que recibe PDF producidos por una impresora virtual como PDFCreator, los renderiza con PyMuPDF y los envía **de uno en uno** a una impresora instalada en Windows. Después permite **seleccionar explícitamente** los estudios que corresponden a cada paciente y moverlos a su expediente.

Pensado para software médico heredado. **No es un sistema clínico certificado** ni sustituye la comprobación manual de los documentos.

## Funciones

- Vigilancia con Watchdog de PDF **creados, modificados o movidos** a la carpeta temporal.
- Espera a que el tamaño y la fecha sean estables y a que el archivo tenga marcador EOF y estructura PDF legible.
- Cola de impresión de un solo trabajador.
- Bitácora persistente para evitar **reenvíos automáticos del mismo archivo**, incluso al reiniciar. Los trabajos con resultado incierto se marcan para revisión y no se reintentan automáticamente.
- Renderizado RGB a un máximo de 300 DPI y 12 millones de píxeles por página.
- **Selección manual** de archivos al clasificar: no mueve todos los PDF al mismo paciente.
- Nombres de carpetas válidos en Windows, colisiones de nombres evitadas y registro de errores.

> **Importante:** «Enviado a impresora» quiere decir que Windows aceptó el trabajo en su cola. **NO confirma que haya salido el papel**, que exista tinta o que la impresora haya terminado.

## Requisitos

- Windows 10/11, Python 3.11 o superior y una impresora configurada en Windows.
- PDFCreator u otra impresora virtual que guarde automáticamente archivos PDF en una carpeta temporal.
- Paquetes indicados en `requirements.txt`: PyMuPDF, Pillow, pywin32 y watchdog.

## Instalar en Windows

Abra PowerShell en una carpeta donde pueda guardar el programa:

```powershell
git clone https://github.com/josesamuelramirez1998-oss/Wachdog-impresora-.git
cd Wachdog-impresora-
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe print_manager.py
```

Para probar la rama de mejoras, después del `cd` ejecute `git switch fix/reliable-print-watchdog` antes de instalar.

## Configurar PDFCreator

1. Configure su perfil para **guardar automáticamente** cada trabajo PDF en la carpeta temporal.
2. Elija un nombre de archivo único (fecha/hora y un identificador si es posible).
3. Desactive acciones «Abrir después de guardar» y ventanas que interrumpan el proceso.
4. En QRS-Card seleccione esa misma carpeta temporal como **Origen**.
5. Seleccione una carpeta **distinta** como destino de **Expedientes**, preferiblemente con copias de seguridad.
6. Seleccione una impresora de Windows y pulse **Activar vigilancia**.

QRS-Card no instala ni configura PDFCreator automáticamente.

## Operación segura

1. Los **PDF nuevos** se detectan y envían a la cola cuando estén completos.
2. Los PDF **ya existentes** al activar el monitor **no se imprimen automáticamente**, para evitar duplicados. Para recuperar alguno, selecciónelo y use **Imprimir seleccionados / reimprimir** solo después de revisar su historial.
3. Verifique la impresión física. Si aparece **«Revisar impresora»**, examine la cola de Windows antes de reintentar.
4. Seleccione en la lista **únicamente los PDF de un mismo paciente**, escriba su nombre y confirme **Guardar seleccionados en expediente**.
5. Compruebe los documentos y mantenga un respaldo del directorio oficial de expedientes.

**QRS-Card no verifica la identidad de un paciente ni interpreta el contenido de los PDF.** La selección y revisión clínica son responsabilidad del operador.

## Archivos de configuración y recuperación

En Windows se guardan en:

```text
%LOCALAPPDATA%\QRS-Card\config_qrs.json
%LOCALAPPDATA%\QRS-Card\print_jobs.json
```

- `config_qrs.json` contiene rutas y el nombre de la impresora. Si existe una configuración anterior junto al script, se intenta leer para migrarla.
- `print_jobs.json` es una bitácora de huellas SHA-256 de ruta, tamaño y fecha de los archivos. **No almacena el contenido clínico**.
- Si la bitácora se corrompe, **el programa impide iniciar la vigilancia** para evitar imprimir otra vez sin control. Recupérela desde un respaldo o revísela antes de continuar.
- Los archivos no se borran tras imprimir; solo se mueven después de confirmar la selección de expediente.
- No hay envío a servicios externos por este programa. Proteja las rutas locales y los respaldos como información sensible.

## Límites conocidos

- La aceptación de un trabajo por el spooler no demuestra impresión física correcta.
- Las firmas de archivos evitan duplicados comunes, pero no garantizan **exactamente una impresión** frente a cambios de archivos, fallas de energía o problemas con la cola del sistema.
- Si se cierra la aplicación mientras hay trabajos activos, hay que verificar qué se completó antes de repetir.
- En carpetas compartidas de red que no emiten eventos correctamente, se recomienda capturar primero en un disco local.
- El funcionamiento con impresoras reales y controladores de Windows requiere pruebas manuales.

## Pruebas

La lógica independiente de Windows dispone de pruebas automatizadas:

```bash
python -m unittest discover -s tests -v
python -m py_compile print_core.py print_manager.py
```

No se incluyen PDFs reales de pacientes ni documentos médicos sensibles.

## Estructura

- `print_manager.py`: interfaz, Watchdog, spooler de Windows y archivado.
- `print_core.py`: gestión de trabajos, nombres seguros y espera de archivos.
- `tests/test_print_core.py`: pruebas independientes de Windows.
