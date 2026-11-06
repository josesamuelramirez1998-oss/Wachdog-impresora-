<#
.SYNOPSIS
Prepara una impresora de LABORATORIO para enviar bytes RAW a CPROT QRS-Card.

.DESCRIPTION
Por defecto solo muestra el plan, sin modificar Windows.
Requiere -Apply y -DriverName para crear la cola de prueba. Usa el driver
PCL5 YA INSTALADO en el equipo; no instala drivers ni cambia la impresora
predeterminada. Inicie antes el receptor en 127.0.0.1:19100.
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [ValidateRange(1024,65535)][int]$Port = 19100,
    [string]$PrinterName = "CPROT QRS Capture (LAB)",
    [string]$DriverName = ""
)
$ErrorActionPreference = "Stop"
$HostIp = "127.0.0.1"
$PortName = "CPROT_RAW_LOCAL_$Port"

Write-Host "CPROT QRS-Card — Captura PCL de laboratorio" -ForegroundColor Cyan
Write-Host "Impresora: $PrinterName"
Write-Host "Host: $HostIp, puerto TCP RAW $Port, nombre de puerto: $PortName"
Write-Warning "NO usar en estudios reales ni convertirla en impresora predeterminada."
Write-Warning "NO imprime papel: captura el flujo de prueba en archivos locales."

if (-not $Apply) {
    Write-Host ""
    Write-Host "Simulación: Windows NO fue modificado." -ForegroundColor Yellow
    Write-Host "1. Consulta drivers disponibles: Get-PrinterDriver | Select-Object Name"
    Write-Host "2. Elige el nombre exacto de un driver realmente compatible con PCL5."
    Write-Host '3. Ejemplo: .\scripts\setup_capture_printer.ps1 -DriverName "NOMBRE EXACTO" -Apply'
    Write-Host "4. Primero inicia en QRS-Card > Captura PCL5 · LAB el receptor local."
    exit 0
}
if ([string]::IsNullOrWhiteSpace($DriverName)) {
    throw "Es obligatorio indicar -DriverName con un controlador PCL5 instalado."
}
$driver = Get-PrinterDriver -Name $DriverName -ErrorAction Stop
if (-not $driver) { throw "No se encontró el controlador: $DriverName" }
$existingPort = Get-PrinterPort -Name $PortName -ErrorAction SilentlyContinue
if ($existingPort) {
    if ($existingPort.PrinterHostAddress -ne $HostIp -or [int]$existingPort.PortNumber -ne $Port) {
        throw "Ya existe un puerto con ese nombre apuntando a otro destino. No se modificará."
    }
    Write-Host "Puerto local existente verificado."
} else {
    Add-PrinterPort -Name $PortName -PrinterHostAddress $HostIp -PortNumber $Port -ErrorAction Stop
    Write-Host "Creado puerto RAW local: $PortName"
}
$printer = Get-Printer -Name $PrinterName -ErrorAction SilentlyContinue
if ($printer) {
    if ($printer.PortName -ne $PortName -or $printer.DriverName -ne $DriverName) {
        throw "Ya existe una impresora con ese nombre y configuración diferente. No se modificará."
    }
    Write-Host "Impresora de laboratorio ya configurada."
} else {
    Add-Printer -Name $PrinterName -DriverName $DriverName -PortName $PortName -ErrorAction Stop
    Write-Host "Creada impresora de laboratorio: $PrinterName" -ForegroundColor Green
}
Write-Host "Elige explícitamente esta impresora SOLO en una prueba con datos ficticios."
Write-Host "Conservar la impresora real como predeterminada; revertir usando remove_capture_printer.ps1."
