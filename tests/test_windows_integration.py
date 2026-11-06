"""Pruebas de integración sin imprimir ni usar datos clínicos reales (Windows)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

@unittest.skipUnless(sys.platform == "win32", "Solo Windows con pywin32")
class WindowsIntegrationTest(unittest.TestCase):
    def setUp(self):
        import fitz
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.valid = self.folder / "prueba.pdf"
        doc = fitz.open()
        doc.new_page(width=595, height=842)
        doc.save(self.valid)
        doc.close()

    def test_pdf_readiness(self):
        from print_manager import pdf_is_complete
        self.assertTrue(pdf_is_complete(self.valid))
        invalid = self.folder / "roto.pdf"
        invalid.write_bytes(b"%PDF-1.4\ntexto no PDF\n%%EOF")
        self.assertFalse(pdf_is_complete(invalid))
        truncated = self.folder / "sin_fin.pdf"
        truncated.write_bytes(self.valid.read_bytes()[:-10])
        self.assertFalse(pdf_is_complete(truncated))

    def test_watchdog_catches_create_move_modify(self):
        from print_manager import MonitorHandler
        events = []
        handler = MonitorHandler(events.append)
        event = Mock(is_directory=False, src_path="C:\\temp\\estudio.pdf",
                     dest_path="C:\\temp\\renombrado.pdf")
        handler.on_created(event)
        handler.on_modified(event)
        handler.on_moved(event)
        self.assertEqual(len(events), 3)
        self.assertTrue(events[-1].endswith("renombrado.pdf"))

    def test_submission_success_using_fake_printer(self):
        import print_manager as pm
        dc = Mock()
        dc.GetDeviceCaps.side_effect = [2000, 2900]
        dc.GetHandleOutput.return_value = 12345
        with patch.object(pm.win32ui, "CreateDC", return_value=dc):
            with patch.object(pm.ImageWin, "Dib") as dib:
                count = pm.print_pdf_to_spooler(self.valid, "Impresora ficticia")
        self.assertEqual(count, 1)
        dc.StartDoc.assert_called_once()
        dc.EndDoc.assert_called_once()
        dc.DeleteDC.assert_called_once()
        dib.return_value.draw.assert_called_once()

    def test_uncertain_job_aborts_without_reporting_success(self):
        import print_manager as pm
        dc = Mock()
        dc.GetDeviceCaps.side_effect = [2000, 2900]
        dc.EndDoc.side_effect = OSError("Simulated printer failure")
        with patch.object(pm.win32ui, "CreateDC", return_value=dc):
            with patch.object(pm.ImageWin, "Dib"):
                with self.assertRaises(pm.PrinterJobError) as raised:
                    pm.print_pdf_to_spooler(self.valid, "Impresora ficticia")
        self.assertTrue(raised.exception.may_have_printed)
        dc.AbortDoc.assert_called_once()
        dc.DeleteDC.assert_called_once()


if __name__ == "__main__":
    unittest.main()
