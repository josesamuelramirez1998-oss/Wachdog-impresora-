"""Receptor local de trabajos de impresión RAW para prototipar captura PCL.

NO instala impresoras ni intercepta el spooler clínico: requiere configurar
explícitamente una cola de prueba de Windows cuyo puerto TCP RAW apunte a
127.0.0.1:<port>. Recibe bytes a medida que Windows los envía, conserva el
original intacto, y opcionalmente permite convertir trabajos PCL con GhostPCL.

El cierre de la conexión TCP marca el fin *del envío*, no garantiza que
el trabajo sea clínicamente íntegro ni que el ECG haya terminado.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

BIND_HOST = "127.0.0.1"
DEFAULT_PORT = 19100
MAX_BYTES = 512 * 1024 * 1024  # configurable con límite, para pruebas largas
IDLE_TIMEOUT = 600.0
MAX_CONNECTIONS = 3
BUF_SIZE = 65536


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def identify_format(prefix: bytes) -> str:
    """Clasificación informativa; no garantiza compatibilidad con el intérprete."""
    start = prefix.lstrip(b"\x00\x09\x0a\x0d\x20")
    upper = start[:8192].upper()
    if start.startswith(b"%PDF-"):
        return "pdf"
    if start.startswith(b"%!PS"):
        return "postscript"
    if b"@PJL ENTER LANGUAGE=PCLXL" in upper or b"@PJL ENTER LANGUAGE=PCL6" in upper:
        return "pclxl"
    if b"@PJL ENTER LANGUAGE=PCL" in upper or start.startswith(b"\x1b") or b"\x1bE" in prefix:
        return "pcl"
    return "unknown"


def _metadata_path(directory: Path, ident: str) -> Path:
    return directory / f"{ident}.json"


def _atomic_json(path: Path, data: dict) -> None:
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@dataclass(frozen=True)
class CaptureEvent:
    kind: str              # listening | started | progress | completed | interrupted | error | stopped
    job_id: str = ""
    size: int = 0
    message: str = ""
    filename: str = ""


class RawCaptureServer:
    """TCP listener on loopback ONLY. Each TCP connection is a captured session.

    Windows Standard TCP/IP Port Monitor in RAW mode typically opens one TCP
    connection per job. This behavior MUST be verified with the installed
    driver, QRS and operating system; it is not guaranteed for continuous print.
    """

    def __init__(
        self, output_dir: str | Path, *,
        port: int = DEFAULT_PORT,
        max_bytes: int = MAX_BYTES,
        idle_timeout: float = IDLE_TIMEOUT,
        on_event: Callable[[CaptureEvent], None] | None = None,
    ):
        if not isinstance(port, int) or not (1024 <= port <= 65535):
            raise ValueError("El puerto debe estar entre 1024 y 65535.")
        if not (1024 <= max_bytes <= MAX_BYTES):
            raise ValueError("El tamaño máximo debe estar entre 1 KiB y 512 MiB.")
        if idle_timeout < 1:
            raise ValueError("El tiempo de inactividad debe ser positivo.")
        self.output_dir = Path(output_dir).resolve()
        self.port = port
        self.max_bytes = max_bytes
        self.idle_timeout = idle_timeout
        self.on_event = on_event
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._workers: set[threading.Thread] = set()
        self._connections: set[socket.socket] = set()
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    @property
    def running(self) -> bool:
        return self._socket is not None and not self._stop.is_set()

    def _emit(self, kind: str, *, job_id: str = "", size: int = 0,
              message: str = "", filename: str = "") -> None:
        if self.on_event:
            try:
                self.on_event(CaptureEvent(kind, job_id, size, message, filename))
            except Exception:
                pass  # la UI/log no puede abortar la conservación de datos

    def start(self) -> None:
        if self.running:
            raise RuntimeError("El receptor ya está activo.")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((BIND_HOST, self.port))
            sock.listen(MAX_CONNECTIONS)
            sock.settimeout(0.5)
        except Exception:
            sock.close()
            raise
        self._socket = sock
        self._thread = threading.Thread(target=self._accept, daemon=True, name="cprot-pcl-listener")
        self._thread.start()
        self._emit("listening", message=f"Captura local activa en {BIND_HOST}:{self.port}")

    def stop(self) -> None:
        self._stop.set()
        sock = self._socket
        self._socket = None
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        with self._lock:
            conns = tuple(self._connections)
        # Desbloquea a los receptores; los trabajos abiertos se marcan interrumpidos.
        for conn in conns:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)

    def wait_closed(self, timeout: float = 4.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                alive = [w for w in self._workers if w.is_alive()]
            if not alive:
                return True
            for worker in alive:
                worker.join(timeout=min(0.1, max(0, deadline - time.monotonic())))
        with self._lock:
            return not any(w.is_alive() for w in self._workers)

    def _accept(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    server = self._socket
                    if server is None:
                        break
                    conn, address = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if not self._stop.is_set():
                        self._emit("error", message="Error de recepción TCP.")
                    break
                if address[0] != BIND_HOST or not self._slots.acquire(blocking=False):
                    conn.close()
                    self._emit("error", message="Conexión rechazada por límite de sesiones.")
                    continue
                t = threading.Thread(
                    target=self._receive, args=(conn,), daemon=True,
                    name="cprot-pcl-receiver",
                )
                with self._lock:
                    self._workers.add(t)
                    self._connections.add(conn)
                    self._workers = {w for w in self._workers if w.is_alive() or w is t}
                t.start()
        finally:
            self._emit("stopped", message="Receptor desconectado.")

    def _receive(self, conn: socket.socket) -> None:
        ident = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:12]
        temp = self.output_dir / f"{ident}.partial"
        started = utcnow()
        total = 0
        digest = hashlib.sha256()
        sample = bytearray()
        last_data = time.monotonic()
        last_notice = last_data
        outcome = "complete"
        error = ""
        try:
            conn.settimeout(0.5)
            self._emit("started", job_id=ident, message="Nuevo flujo de impresión recibido.")
            with temp.open("xb") as output:
                while True:
                    if self._stop.is_set():
                        outcome = "interrupted"
                        error = "Captura detenida con trabajo abierto."
                        break
                    try:
                        chunk = conn.recv(BUF_SIZE)
                    except socket.timeout:
                        if time.monotonic() - last_data > self.idle_timeout:
                            outcome = "interrupted"
                            error = "Sesión sin datos: terminó por tiempo de espera."
                            break
                        continue
                    except OSError as exc:
                        outcome = "interrupted"
                        error = f"Conexión interrumpida ({type(exc).__name__})."
                        break
                    if not chunk:
                        break
                    last_data = time.monotonic()
                    if total + len(chunk) > self.max_bytes:
                        outcome = "too_large"
                        error = "Límite de datos alcanzado. Conservada captura parcial."
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    total += len(chunk)
                    if len(sample) < 8192:
                        sample.extend(chunk[:8192 - len(sample)])
                    if last_data - last_notice >= 1.0:
                        self._emit("progress", job_id=ident, size=total)
                        last_notice = last_data
                output.flush()
                os.fsync(output.fileno())
        except OSError as exc:
            outcome = "error"
            error = f"Fallo guardando captura ({type(exc).__name__})."
        finally:
            try:
                conn.close()
            except OSError:
                pass
            with self._lock:
                self._connections.discard(conn)
                self._workers.discard(threading.current_thread())
            self._slots.release()

        # Cerrar el receptor puede hacer que recv() retorne EOF en vez de
        # lanzar un error. Nunca declarar completo ese trabajo al parar.
        if self._stop.is_set() and outcome == "complete":
            outcome = "interrupted"
            error = "Receptor detenido antes de confirmar el fin del trabajo."

        # Un sondeo de red vacío no representa un trabajo.
        if total == 0 and outcome == "complete":
            temp.unlink(missing_ok=True)
            return

        fmt = identify_format(bytes(sample))
        suffix = ".pcl" if fmt in {"pcl", "pclxl"} else ".ps" if fmt == "postscript" else ".pdf" if fmt == "pdf" else ".prn"
        final_file = self.output_dir / f"{ident}{suffix if outcome == 'complete' else '.partial'}"
        if temp.exists() and temp != final_file:
            try:
                os.replace(temp, final_file)
            except OSError as exc:
                outcome = "error"
                error = f"No se pudo terminar de guardar ({type(exc).__name__})."
                final_file = temp
        record = {
            "schema": 1, "id": ident, "started_utc": started, "finished_utc": utcnow(),
            "state": outcome, "bytes": total, "sha256": digest.hexdigest(),
            "format": fmt, "source_file": final_file.name, "converted_pdf": "",
            "message": error,
            "capture_method": "TCP RAW loopback, one connection",
        }
        try:
            _atomic_json(_metadata_path(self.output_dir, ident), record)
        except OSError:
            self._emit("error", job_id=ident, size=total,
                       message="La captura existe pero no pudo guardarse su manifiesto.")
            return
        self._emit("completed" if outcome == "complete" else "interrupted",
                   job_id=ident, size=total, filename=final_file.name,
                   message=error or f"Sesión recibida; formato estimado: {fmt}.")


def load_captures(folder: str | Path) -> list[dict]:
    root = Path(folder).resolve()
    result = []
    if not root.is_dir():
        return []
    for path in sorted(root.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("schema") != 1 or not isinstance(data.get("id"), str):
                continue
            if path.name != data["id"] + ".json":
                continue
            filename = data.get("source_file", "")
            if not isinstance(filename, str) or not filename or Path(filename).name != filename:
                continue
            result.append(data)
        except (OSError, ValueError, TypeError):
            continue
    return result


def find_ghostpcl(value: str | Path | None = None) -> str | None:
    if value:
        p = Path(value)
        return str(p.resolve()) if p.is_file() else shutil.which(str(value))
    for candidate in ("gpcl6win64.exe", "gpcl6win32.exe", "gpcl6.exe", "gpcl6", "pcl6"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _is_pdf(path: Path) -> bool:
    try:
        if path.stat().st_size < 16:
            return False
        with path.open("rb") as f:
            if not f.read(5) == b"%PDF-":
                return False
            f.seek(max(0, path.stat().st_size - 4096))
            return b"%%EOF" in f.read()
    except OSError:
        return False


def convert_to_pdf(folder: str | Path, capture: dict, executable: str | Path,
                   *, timeout: float = 180.0) -> Path:
    """Convierte un trabajo PCL completo sin sobrescribir el original.

    No invoca shell ni distribuye GhostPCL. El PDF resultante es de consulta;
    debe validarse contra papel/trazado antes de un uso clínico.
    """
    root = Path(folder).resolve()
    ident = capture.get("id")
    if not isinstance(ident, str) or not ident or _metadata_path(root, ident).name != ident + ".json":
        raise ValueError("Identificador de trabajo inválido.")
    if capture.get("state") != "complete":
        raise ValueError("La captura está incompleta; no se puede convertir automáticamente.")
    if capture.get("format") not in ("pcl", "pclxl"):
        raise ValueError("El contenido no está identificado como PCL.")
    name = capture.get("source_file", "")
    if not isinstance(name, str) or Path(name).name != name or not name.startswith(ident):
        raise ValueError("Ruta del trabajo inválida.")
    source = root / name
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError("No existe el trabajo PCL original.")
    digest = hashlib.sha256()
    with source.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(part)
    if digest.hexdigest() != capture.get("sha256"):
        raise ValueError("El trabajo original cambió: no se convertirá.")
    exe = find_ghostpcl(executable)
    if not exe:
        raise FileNotFoundError("Selecciona el ejecutable GhostPCL instalado por separado.")
    output = root / f"{ident}.pdf"
    if output.exists():
        if _is_pdf(output):
            return output
        raise FileExistsError("Ya existe un archivo PDF con ese nombre.")
    temp = root / f"{ident}.{uuid.uuid4().hex}.working.pdf"
    try:
        subprocess.run(
            [exe, "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite",
             f"-sOutputFile={temp}", str(source)],
            cwd=str(root), check=True, capture_output=True,
            timeout=timeout, shell=False,
        )
        if not _is_pdf(temp):
            raise ValueError("GhostPCL no generó un PDF con estructura mínima válida.")
        os.replace(temp, output)
        manifest = _metadata_path(root, ident)
        current = json.loads(manifest.read_text(encoding="utf-8"))
        current["converted_pdf"] = output.name
        current["converted_utc"] = utcnow()
        _atomic_json(manifest, current)
        return output
    finally:
        temp.unlink(missing_ok=True)
