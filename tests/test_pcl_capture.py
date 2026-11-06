"""Pruebas del receptor PCL sin impresora ni documentos reales."""
from __future__ import annotations

import hashlib
import json
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from pcl_capture import (
    BIND_HOST, CaptureEvent, RawCaptureServer,
    convert_to_pdf, identify_format, load_captures,
)


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((BIND_HOST, 0))
        port = s.getsockname()[1]
        if port < 1024:
            raise RuntimeError("Puerto de prueba inválido.")
        return port


def await_jobs(folder: Path, count: int, timeout: float = 6.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        jobs = load_captures(folder)
        if len(jobs) >= count:
            return jobs
        time.sleep(0.04)
    raise AssertionError(f"Solo se encontraron {len(load_captures(folder))} trabajos.")


class ClassificationTest(unittest.TestCase):
    def test_pcl_and_other_languages(self):
        self.assertEqual(identify_format(b"\x1bE\x1b&l0Oabc"), "pcl")
        self.assertEqual(identify_format(b"\x1b%-12345X@PJL ENTER LANGUAGE=PCL\r\n"), "pcl")
        self.assertEqual(identify_format(b"\x1b%-12345X@PJL ENTER LANGUAGE=PCLXL\r\n"), "pclxl")
        self.assertEqual(identify_format(b"%PDF-1.4\n"), "pdf")
        self.assertEqual(identify_format(b"%!PS-Adobe-3.0"), "postscript")
        self.assertEqual(identify_format(b"no-print-language"), "unknown")

    def test_port_restriction(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                RawCaptureServer(td, port=80)
            with self.assertRaises(ValueError):
                RawCaptureServer(td, port=99999)


class ReceiverTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.port = free_port()
        self.messages = []
        self.server = RawCaptureServer(self.folder, port=self.port,
                                       on_event=self.messages.append)
        self.server.start()
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.server.stop()
        self.server.wait_closed(timeout=3.0)

    def send(self, payload: bytes):
        with socket.create_connection((BIND_HOST, self.port), timeout=2) as client:
            client.sendall(payload)

    def test_receives_exact_bytes_and_manifest(self):
        payload = b"\x1bE" + (b"ECG testing line\n" * 200)
        self.send(payload[:87])
        # One connection is one job; next transfer should be a distinct job.
        self.send(payload)
        jobs = await_jobs(self.folder, 2)
        completed = [j for j in jobs if j["bytes"] == len(payload)]
        self.assertEqual(len(completed), 1)
        job = completed[0]
        self.assertEqual(job["state"], "complete")
        self.assertEqual(job["format"], "pcl")
        self.assertEqual(job["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual((self.folder / job["source_file"]).read_bytes(), payload)
        self.assertFalse((self.folder / job["source_file"]).is_symlink())
        self.assertTrue(any(e.kind == "completed" for e in self.messages))

    def test_localhost_only(self):
        self.assertTrue(self.server.running)
        self.assertEqual(self.server._socket.getsockname()[0], "127.0.0.1")

    def test_empty_probe_does_not_create_job(self):
        with socket.create_connection((BIND_HOST, self.port), timeout=2):
            pass
        time.sleep(0.2)
        self.assertEqual(load_captures(self.folder), [])

    def test_stop_marks_open_session_as_incomplete(self):
        client = socket.create_connection((BIND_HOST, self.port), timeout=3)
        try:
            client.sendall(b"\x1bE" + b"still-running" * 100)
            time.sleep(0.15)
            self.server.stop()
            self.server.wait_closed(timeout=3)
            jobs = await_jobs(self.folder, 1)
            self.assertEqual(jobs[0]["state"], "interrupted")
            self.assertTrue(jobs[0]["source_file"].endswith(".partial"))
            self.assertGreater(jobs[0]["bytes"], 0)
        finally:
            client.close()

    def test_size_limit_preserves_partial_data(self):
        self.shutdown()
        self.server = RawCaptureServer(self.folder, port=self.port,
                                       max_bytes=1024, on_event=self.messages.append)
        self.server.start()
        self.send(b"\x1bE" + (b"a" * 1100))
        job = await_jobs(self.folder, 1)[0]
        self.assertEqual(job["state"], "too_large")
        self.assertTrue(job["source_file"].endswith(".partial"))


class ConversionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ident = "20261106_120000_" + "abc123def456"
        self.raw = self.root / (self.ident + ".pcl")
        self.raw.write_bytes(b"\x1bE" + b"PCL fake fixture")
        self.record = {
            "schema": 1, "id": self.ident, "state": "complete",
            "format": "pcl", "source_file": self.raw.name,
            "sha256": hashlib.sha256(self.raw.read_bytes()).hexdigest(),
            "converted_pdf": "",
        }
        (self.root / (self.ident + ".json")).write_text(json.dumps(self.record), encoding="utf-8")

    def test_broken_integrity_blocks_conversion(self):
        self.raw.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "cambió"):
            convert_to_pdf(self.root, self.record, sys.executable)

    def test_incomplete_rejected(self):
        record = dict(self.record, state="interrupted")
        with self.assertRaisesRegex(ValueError, "incompleta"):
            convert_to_pdf(self.root, record, sys.executable)

    def test_guard_against_path_traversal(self):
        record = dict(self.record, source_file="../outside.pcl")
        with self.assertRaises(ValueError):
            convert_to_pdf(self.root, record, sys.executable)

    def test_conversion_retains_original_and_checks_pdf(self):
        source_content = self.raw.read_bytes()
        calls = []
        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            output = next(a.split("=", 1)[1] for a in argv if a.startswith("-sOutputFile="))
            Path(output).write_bytes(b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
        with patch("pcl_capture.subprocess.run", side_effect=fake_run):
            result = convert_to_pdf(self.root, self.record, sys.executable)
        self.assertEqual(result.suffix, ".pdf")
        self.assertEqual(self.raw.read_bytes(), source_content)
        self.assertTrue(result.exists())
        self.assertFalse(calls[0][1]["shell"])
        self.assertEqual(json.loads((self.root / (self.ident + ".json")).read_text())["converted_pdf"], result.name)


if __name__ == "__main__":
    unittest.main()
