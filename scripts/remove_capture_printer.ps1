<#
.SYNOPSIS
Elimina exclusivamente la cola de LABORATORIO CPROT, previa confirmación.
No elimina drivers ni cambia la impresora predeterminada.
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [ValidateRange(1024,65535)][int]$Port = 19100,
    [string]$PrinterName = "CPROT QRS Capture (LAB)"
)
$ErrorActionPreference = "Stop"
$PortName = "CPROT_RAW_LOCAL_$Port"
Write-Host "Quitar exclusivamente $PrinterName / $PortName."
if (-not $Apply) {
    Write-Host "Solo simulación. Para aplicar, usa: .\scripts\remove_capture_printer.ps1 -Apply"
    exit 0
}
$p = Get-Printer -Name $PrinterName -ErrorAction SilentlyContinue
if ($p -and $p.PortName -ne $PortName) {
    throw "La impresora tiene un puerto diferente. No se eliminará."
}
if ($p) {
    Remove-Printer -Name $PrinterName -ErrorAction Stop
    Write-Host "Impresora de laboratorio eliminada."
}
$portObject = Get-PrinterPort -Name $PortName -ErrorAction SilentlyContinue
if ($portObject) {
    if ($portObject.PrinterHostAddress -ne "127.0.0.1" -or [int]$portObject.PortNumber -ne $Port) {
        throw "El puerto ya no pertenece a la captura local. No se eliminará."
    }
    $uses = @(Get-Printer | Where-Object { $_.PortName -eq $PortName })
    if ($uses.Count -eq 0) {
        Remove-PrinterPort -Name $PortName -ErrorAction Stop
        Write-Host "Puerto local eliminado."
    } else {
        Write-Warning "El puerto lo usa otra impresora. Se conserva."
    }
}
Write-Host "No se alteró ningún controlador ni la impresora predeterminada."
