"""Pruebas de regresión de la lógica sin dependencias de Windows."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from print_core import (
    PrintRegistry, file_signature, move_study, patient_folder_name,
    pdf_files, unique_study_path, wait_for_ready_pdf,
)


class PatientNamesTest(unittest.TestCase):
    def test_clean_and_reserved_windows_names(self):
        self.assertEqual(patient_folder_name("  Ana  López  "), "Ana López")
        self.assertEqual(patient_folder_name("Juan: Pérez/Estudio"), "Juan_ Pérez_Estudio")
        self.assertEqual(patient_folder_name("CON"), "_CON")
        self.assertEqual(patient_folder_name("aux.pdf"), "_aux.pdf")
        self.assertEqual(patient_folder_name("Archivo..."), "Archivo")

    def test_invalid_names(self):
        for bad in ("", "   ", "...", "   .   "):
            with self.subTest(name=bad):
                with self.assertRaises(ValueError):
                    patient_folder_name(bad)


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.pdf = self.folder / "estudio.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        self.file = self.folder / "ledger.json"

    def test_claim_dedup_and_restart(self):
        store = PrintRegistry(self.file)
        first = store.claim(self.pdf)
        self.assertIsNotNone(first)
        self.assertIsNone(store.claim(self.pdf))
        self.assertTrue(store.is_pending(self.pdf))
        store.record(first)
        store.release(first)
        self.assertEqual(store.status(self.pdf), "Enviado a impresora")
        reopened = PrintRegistry(self.file)
        self.assertIsNone(reopened.claim(self.pdf))
        self.assertIsNotNone(reopened.claim(self.pdf, force=True))

    def test_final_signature_prevents_reprint_after_file_finishes(self):
        store = PrintRegistry(self.file)
        early = store.claim(self.pdf)
        # PDFCreator adds bytes after the filesystem creation event.
        self.pdf.write_bytes(self.pdf.read_bytes() + b"last update")
        final = (early[0], file_signature(self.pdf))
        self.assertNotEqual(early[1], final[1])
        self.assertFalse(store.was_handled(final))
        store.record(final)
        store.release(early)
        reopened = PrintRegistry(self.file)
        self.assertTrue(reopened.was_handled(final))
        self.assertIsNone(reopened.claim(self.pdf))

    def test_uncertain_needs_manual_action(self):
        store = PrintRegistry(self.file)
        token = store.claim(self.pdf)
        store.record(token, uncertain=True)
        store.release(token)
        self.assertEqual(store.status(self.pdf), "Revisar impresora")
        self.assertIsNone(PrintRegistry(self.file).claim(self.pdf))

    def test_file_changes_can_be_processed(self):
        store = PrintRegistry(self.file)
        token = store.claim(self.pdf)
        store.record(token)
        store.release(token)
        self.pdf.write_bytes(self.pdf.read_bytes() + b"\n% revised")
        self.assertIsNotNone(store.claim(self.pdf))
        self.assertEqual(len(file_signature(self.pdf)), 64)

    def test_corrupt_state_fails_closed(self):
        self.file.write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "bitácora"):
            PrintRegistry(self.file)


class FileHandlingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "temp"
        self.source.mkdir()
        self.destination = self.root / "expedientes"
        self.destination.mkdir()

    def test_only_pdfs(self):
        (self.source / "one.PDF").write_text("test")
        (self.source / "two.txt").write_text("test")
        self.assertEqual([p.name for p in pdf_files(self.source)], ["one.PDF"])

    def test_safe_move_never_overwrites(self):
        first = self.source / "first.pdf"
        first.write_bytes(b"first")
        dst = move_study(first, self.destination, "María/Álvarez", 1)
        self.assertEqual(dst.name, "María_Álvarez_Estudio_01.pdf")
        self.assertEqual(dst.read_bytes(), b"first")
        another = self.source / "second.pdf"
        another.write_bytes(b"second")
        result = move_study(another, self.destination, "María/Álvarez", 1)
        self.assertNotEqual(result, dst)
        self.assertEqual(dst.read_bytes(), b"first")
        self.assertEqual(result.read_bytes(), b"second")

    def test_stability_check_validates_content(self):
        path = self.source / "new.pdf"
        path.write_text("incomplete")
        def finish():
            time.sleep(0.12)
            path.write_text("complete")
        thread = threading.Thread(target=finish)
        thread.start()
        self.assertTrue(wait_for_ready_pdf(
            path, lambda p: p.read_text() == "complete",
            timeout=2.0, interval=0.03,
        ))
        thread.join()

    def test_cancel_wait(self):
        event = threading.Event()
        event.set()
        self.assertFalse(wait_for_ready_pdf(
            self.source / "missing.pdf", lambda p: True,
            timeout=1, interval=0.01, stop=event,
        ))


if __name__ == "__main__":
    unittest.main()
