"""Funciones independientes de Windows para gestionar estudios y evitar duplicados.

La bitácora registra firmas de ruta/tamaño/fecha, nunca contenido clínico.
No confirma que una impresora haya producido papel: 'submitted' significa
que el trabajo fue entregado correctamente al spooler de Windows.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

INVALID_WINDOWS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_WINDOWS = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', re.I)


def patient_folder_name(raw: str) -> str:
    """Normaliza un nombre para una carpeta de pacientes en Windows."""
    name = INVALID_WINDOWS.sub("_", raw.strip()).strip(" .")
    name = re.sub(r"\s+", " ", name)
    if not name or name in {".", ".."}:
        raise ValueError("Escriba un nombre de paciente válido.")
    if RESERVED_WINDOWS.match(name):
        name = "_" + name
    return name[:110].rstrip(" .")


def pdf_files(folder: str | Path) -> list[Path]:
    """Lista solo PDF regulares del directorio (sin seguir enlaces simbólicos)."""
    try:
        with os.scandir(folder) as entries:
            result = [
                Path(e.path) for e in entries
                if e.is_file(follow_symlinks=False) and e.name.lower().endswith(".pdf")
            ]
    except OSError:
        return []
    return sorted(result, key=lambda p: p.name.casefold())


def file_signature(path: str | Path) -> str:
    """Firma sin leer el estudio; distingue reemplazos y modificaciones."""
    p = Path(path).resolve()
    st = p.stat()
    if not p.is_file():
        raise FileNotFoundError(str(p))
    raw = f"{os.path.normcase(str(p))}\0{st.st_size}\0{st.st_mtime_ns}"
    return hashlib.sha256(raw.encode("utf-8", errors="surrogatepass")).hexdigest()


def wait_for_ready_pdf(
    path: str | Path, validate: Callable[[Path], bool], *,
    timeout: float = 45.0, interval: float = 0.5,
    stop: threading.Event | None = None,
) -> bool:
    """Espera estabilidad de tamaño y fecha en tres muestras y PDF válido.

    Llamar desde un hilo, no desde Tkinter.
    """
    if timeout <= 0 or interval <= 0:
        raise ValueError("El tiempo de espera y el intervalo deben ser positivos.")
    deadline = time.monotonic() + timeout
    previous = None
    consecutive = 0
    p = Path(path)
    while time.monotonic() < deadline:
        if stop and stop.is_set():
            return False
        try:
            st = p.stat()
            current = (st.st_size, st.st_mtime_ns)
            if st.st_size > 0 and current == previous:
                consecutive += 1
            else:
                consecutive = 1
            previous = current
            if consecutive >= 3 and validate(p):
                # Evita devolver listo si cambió durante la comprobación.
                end = p.stat()
                if (end.st_size, end.st_mtime_ns) == current:
                    return True
        except (OSError, ValueError):
            previous, consecutive = None, 0
        delay = min(interval, max(0.0, deadline - time.monotonic()))
        if stop:
            if stop.wait(delay):
                return False
        else:
            time.sleep(delay)
    return False


class PrintRegistry:
    """Bitácora de envíos al spooler e impresiones de estado incierto.

    Impide que el monitor envíe automáticamente el mismo archivo dos veces.
    La reimpresión deliberada se realiza mediante claim(..., force=True).
    """
    MAX_RECORDS = 20000

    def __init__(self, state_file: str | Path):
        self.path = Path(state_file)
        self.lock = threading.RLock()
        self.pending: set[str] = set()
        self.submitted: list[str] = []
        self.uncertain: list[str] = []
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if raw.get("version") != 1 or not isinstance(raw.get("submitted"), list) or not isinstance(raw.get("uncertain"), list):
                    raise ValueError("Estructura de la bitácora incorrecta.")
                self.submitted = [str(x) for x in raw["submitted"] if isinstance(x, str)]
                self.uncertain = [str(x) for x in raw["uncertain"] if isinstance(x, str)]
            except (OSError, ValueError, TypeError, AttributeError) as exc:
                raise ValueError(
                    "No se puede leer la bitácora de impresión. Por seguridad, "
                    "la vigilancia no debe iniciarse hasta revisarla."
                ) from exc

    @staticmethod
    def _key(path: str | Path) -> str:
        return os.path.normcase(os.path.abspath(path))

    def is_pending(self, path: str | Path) -> bool:
        with self.lock:
            return self._key(path) in self.pending

    def claim(self, path: str | Path, *, force: bool = False) -> tuple[str, str] | None:
        """Reserva un trabajo o retorna None si ya está pendiente/completado."""
        try:
            sig = file_signature(path)
        except OSError:
            return None
        key = self._key(path)
        with self.lock:
            if key in self.pending:
                return None
            if not force and (sig in self.submitted or sig in self.uncertain):
                return None
            self.pending.add(key)
        return key, sig

    def release(self, token: tuple[str, str]) -> None:
        with self.lock:
            self.pending.discard(token[0])

    def status(self, path: str | Path) -> str:
        with self.lock:
            if self._key(path) in self.pending:
                return "Pendiente / imprimiendo"
            try:
                sig = file_signature(path)
            except OSError:
                return "No disponible"
            if sig in self.uncertain:
                return "Revisar impresora"
            if sig in self.submitted:
                return "Enviado a impresora"
            return "Sin procesar"

    def record(self, token: tuple[str, str], *, uncertain: bool = False) -> None:
        """Persiste una firma. Si falla el disco, propaga el error."""
        sig = token[1]
        with self.lock:
            target = self.uncertain if uncertain else self.submitted
            if sig not in target:
                target.append(sig)
            target[:] = target[-self.MAX_RECORDS:]
            if uncertain and sig in self.submitted:
                self.submitted.remove(sig)
            if not uncertain and sig in self.uncertain:
                self.uncertain.remove(sig)
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        target = self.path.with_name(self.path.name + ".tmp")
        data = {"version": 1, "submitted": self.submitted, "uncertain": self.uncertain}
        try:
            with target.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(target, self.path)
        finally:
            if target.exists():
                target.unlink(missing_ok=True)


def unique_study_path(folder: str | Path, patient: str, number: int) -> Path:
    """Genera un destino disponible sin sobrescribir expedientes existentes."""
    base = Path(folder)
    candidate = base / f"{patient}_Estudio_{number:02d}.pdf"
    suffix = 1
    while candidate.exists():
        candidate = base / f"{patient}_Estudio_{number:02d}_{suffix}.pdf"
        suffix += 1
    return candidate


def move_study(source: str | Path, destination_folder: str | Path, patient: str, number: int) -> Path:
    """Mueve un PDF y no utiliza nombres de destino aportados sin sanitizar."""
    source = Path(source)
    if source.is_symlink() or not source.is_file() or source.suffix.lower() != ".pdf":
        raise ValueError("El archivo debe ser un PDF regular.")
    name = patient_folder_name(patient)
    directory = Path(destination_folder) / name
    directory.mkdir(parents=True, exist_ok=True)
    target = unique_study_path(directory, name, number)
    shutil.move(str(source), str(target))
    return target
