# Propuesta CPROT: captura nativa de QRS-Card sin dependencia obligatoria de PDFCreator

> Documento de diseño y validación. No hay implementación de captura PCL ni garantía de fidelidad clínica hasta realizar pruebas con QRS-Card y un equipo de laboratorio.

## Hallazgo en la documentación del fabricante

- El manual de QRS-Card 4.06 muestra Utility > Configuration > Real Time Print, con formato PCL5, plantilla pcl5us.rtt y alternativa genrtp.rtt. Indica que la impresión en tiempo real necesita una impresora compatible PCL5.
- El mismo manual documenta archivos SCP en la base de datos local (qrsdb4/files). Estos archivos se deben preservar y respaldar sin modificar; todavía falta verificar qué contenido conserva cada prueba en la versión instalada.
- La guía oficial de Stress ECG documenta la generación de reportes a impresora, PDF y Word desde la pantalla de revisión.

Fuentes:
- https://www.qrscard.com/download/Documents/CS406-10.pdf
- https://www.qrscard.com/download/Documents/CS406-15.pdf

## Objetivos diferentes que NO debemos confundir

1. Archivo clínico editable / revisable: conservar los archivos nativos y metadatos originales de QRS-Card.
2. Documento fiel al papel: conservar una copia bit a bit del trabajo PCL5 o EMF/XPS que el software entregue a la cola de prueba, y generar PDF de consulta.
3. Captura en vivo: recibir el flujo a medida que se transmite y conservarlo. Ver avances por página requiere reconocer límites de página o un intérprete del lenguaje; no se garantiza solo mirando la cola de impresión.
4. Impresión física: debe seguir funcionando de forma independiente a CPROT QRS-Card durante la validación.

## Arquitectura experimental preferida

1. Captura aislada con QRS-Card en modo DEMO o prueba no clínica. No cambiar la impresora clínica durante un procedimiento real.
2. Configurar una cola Windows de prueba PCL5 y estudiar si QRS-Card transmite trabajos RAW PCL5, EMF o XPS (la ruta depende de software y driver).
3. Prototipo opcional de receptor local solo en loopback (127.0.0.1) que guarde por sesión el flujo original como .pcl/.prn y su SHA-256. No exponer el puerto a la red.
4. En caso de comprobar que el flujo capturado es PCL5 compatible, probar conversión a PDF mediante un intérprete PCL, por ejemplo GhostPCL, evaluando licencias AGPL/comerciales y sin incorporar automáticamente binarios a una solución cerrada.
5. Asociar el resultado a un estudio mediante selección/verificación humana; conservar original y PDF. No determinar paciente por nombre de archivo o aproximación temporal.
6. Mantener PDFCreator como alternativa temporal para reportes convencionales hasta demostrar una captura directa robusta.

## Requisitos de fidelidad y seguridad

- Conservar el flujo fuente exacto junto al PDF; una conversión puede modificar la representación, las fuentes o rasterizar trazos.
- Comparar escala 10 mm/mV, velocidad 25/50 mm/s, cuadrícula, 12 derivaciones, calibración, etiquetas, orden y continuidad sin recortar segmentos.
- No modificar ni reconstruir los datos diagnósticos del estudio; no usar captura de pantalla como sustituto de información clínica.
- No tratar un PDF impreso como equivalente a señal ECG de tiempo real o a 'full disclosure' sin verificar qué salida QRS-Card produjo.
- Aislar datos personales: archivos locales privados, registros sin información clínica, permisos mínimos y copias de seguridad.
- Seguir mostrando 'enviado al spooler' y no 'impreso físicamente' hasta verificar el equipo.

## Etapas y criterios de aceptación

### A. Reutilizar funciones nativas existentes

- Desde un examen de prueba abrir QRS-Card, seleccionar Report y localizar la opción PDF File Viewer; comparar el PDF exportado con la impresión física.
- Inspeccionar la configuración Real Time Print sin alterar el equipo que esté atendiendo pacientes.
- Confirmar ubicación de base de datos y tipo de archivos de la versión instalada; respaldarlos antes de pruebas.

### B. Captura del flujo real

- Generar un trazo de ejemplo durante una prueba de simulación y comprobar que el receptor captura bytes en tiempo real.
- Determinar si la salida contiene PCL5 RAW o si pasa por una representación EMF/XPS. No suponer que son equivalentes.
- Confirmar comportamiento por página, fin de trabajo, fallos, impresiones continuas y cancelaciones.

### C. PDF validado

- Convertir una captura completa a PDF conservando el archivo original.
- Comparar contra papel y PDF exportado por QRS: cuadrícula, amplitud, velocidad, derivaciones, márgenes y legibilidad.
- Aprobar pruebas de regresión antes de ofrecer esta vía en producción.

## Restricciones de Windows

- Windows admite rutas GDI/EMF, XPS y RAW; no es posible recuperar información que la aplicación nunca envió a imprimir.
- Los controladores v4 no permiten monitores de puerto personalizados de terceros. Un driver propio de impresión exige diseño, instalación y pruebas adicionales.
- Los trabajos continuos pueden permanecer abiertos durante una prueba: no garantizar un PDF final completo hasta la finalización, salvo que se demuestre procesamiento seguro por páginas.

## Estado

Propuesta aprobada como dirección de investigación, pendiente de pruebas reales. No sustituir PDFCreator ni modificar la configuración de QRS-Card del consultorio hasta verificar compatibilidad, continuidad y fidelidad.