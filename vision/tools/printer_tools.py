"""
Document Generation & Physical Printer Integration Tools for VISION.
Supports custom PDF generation (e.g. A4 bordered papers with custom margins)
and direct Windows GDI physical printer job dispatching via PyMuPDF + Win32 GDI,
including specific page or page-range printing (e.g. page 5, pages 1-3).
"""

import os
import time
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from vision.tools.registry import tool
from vision.memory.working_memory import working_memory
from vision.logger import logger
from vision.platform import IS_WINDOWS

try:
    import win32print
    import win32ui
    import win32con
    from PIL import Image, ImageWin
    import pymupdf
except ImportError:
    win32print = None
    win32ui = None
    win32con = None
    Image = None
    ImageWin = None
    pymupdf = None

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas
except ImportError:
    canvas = None


def check_printer_available(printer_name: Optional[str] = None) -> Dict[str, Any]:
    """Check if a printer is installed and accessible on the current OS."""
    # Windows: use Win32 GDI.
    if IS_WINDOWS and win32print:
        try:
            target_printer = printer_name or win32print.GetDefaultPrinter()
            if not target_printer:
                return {"available": False, "name": None, "error": "No printer detected or configured on this computer."}

            hprinter = win32print.OpenPrinter(target_printer)
            p_info = win32print.GetPrinter(hprinter, 2)
            win32print.ClosePrinter(hprinter)

            status = p_info.get("Status", 0)
            if status & 0x00000080:  # PRINTER_STATUS_OFFLINE
                return {
                    "available": False,
                    "name": target_printer,
                    "error": f"The printer '{target_printer}' is currently OFFLINE. Please check power and USB/network cables.",
                }
            return {"available": True, "name": target_printer, "error": None}
        except Exception as e:
            logger.warning(f"[PrinterTool] Failed to verify printer: {e}")
            return {"available": False, "name": None, "error": f"Printer is not connected or accessible ({e})."}

    # Linux / macOS: prefer CUPS `lpstat` / `lp`, fall back to `lpr`.
    if shutil.which("lpstat") or shutil.which("lp") or shutil.which("lpr"):
        try:
            if printer_name:
                target = printer_name
            elif shutil.which("lpstat"):
                out = subprocess.run(["lpstat", "-d"], capture_output=True, text=True, errors="ignore", timeout=5)
                target = None
                for line in out.stdout.splitlines():
                    if line.startswith("system default destination:"):
                        target = line.split(":", 1)[1].strip()
                        break
                if not target:
                    # List first available printer
                    out2 = subprocess.run(["lpstat", "-p"], capture_output=True, text=True, errors="ignore", timeout=5)
                    for line in out2.stdout.splitlines():
                        if line.startswith("printer"):
                            target = line.split()[1]
                            break
            else:
                target = printer_name
            if target:
                return {"available": True, "name": target, "error": None}
            return {"available": True, "name": "default", "error": None}
        except Exception as e:
            logger.warning(f"[PrinterTool] Failed to verify printer: {e}")
            return {"available": False, "name": None, "error": f"Printer check failed ({e})."}

    return {"available": False, "name": None, "error": "No printer subsystem available (install CUPS / a PDF viewer with print support)."}


def _parse_page_selection(pages_str: Optional[Union[str, int]], total_pages: int) -> List[int]:
    """Parse page specifications like '5', 5, '1-3', '2,4,6' into 0-indexed page indices."""
    if pages_str is None:
        return list(range(total_pages))

    if isinstance(pages_str, int):
        if 1 <= pages_str <= total_pages:
            return [pages_str - 1]
        return list(range(total_pages))

    indices = set()
    parts = str(pages_str).replace("page", "").replace("Page", "").strip().split(",")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                start_str, end_str = part.split("-", 1)
                start = max(1, int(start_str.strip()))
                end = min(total_pages, int(end_str.strip()))
                for p in range(start, end + 1):
                    indices.add(p - 1)
            except ValueError:
                continue
        else:
            try:
                p_num = int(part)
                if 1 <= p_num <= total_pages:
                    indices.add(p_num - 1)
            except ValueError:
                continue

    if not indices:
        return list(range(total_pages))
    return sorted(list(indices))


@tool(name="create_bordered_a4_document", description="Generate a blank A4 size PDF document with only a clean border on all four sides with custom margin (default 1.5 cm).")
def create_bordered_a4_document(margin_cm: float = 1.5, file_name: str = "bordered_a4_page.pdf", line_thickness: float = 1.5) -> str:
    """Generate a clean A4 paper PDF with specified border margin."""
    if not canvas:
        return "Error: reportlab is not installed."

    try:
        clean_name = file_name.strip()
        if not clean_name.lower().endswith(".pdf"):
            clean_name += ".pdf"

        output_dir = Path.home() / "Documents"
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / clean_name

        c = canvas.Canvas(str(out_path), pagesize=A4)
        width, height = A4
        margin = margin_cm * cm

        c.setLineWidth(line_thickness)
        # Draw clean border rectangle
        c.rect(margin, margin, width - (2 * margin), height - (2 * margin))
        c.showPage()
        c.save()

        working_memory.record_file(str(out_path))
        logger.info(f"[PrinterTool] Created bordered A4 document at {out_path}")
        return f"Successfully created A4 document with {margin_cm}cm border at '{out_path}'."
    except Exception as e:
        return f"Error creating bordered document: {e}"


# ── POSIX (Linux/macOS) print path via CUPS ────────────────────────

def _print_pdf_posix(pdf_path: Path, printer_name: Optional[str], copies: int = 1, page_selection: Optional[Union[str, int]] = None) -> bool:
    """Send a PDF to a CUPS/lpr printer using `lp` (preferred) or `lpr`."""
    sender = shutil.which("lp") or shutil.which("lpr")
    if not sender:
        return False
    pages_arg: List[str] = []
    if page_selection is not None:
        sel = str(page_selection)
        # Convert "1-3" -> "1-3" (CUPS already understands ranges) but strip
        # verbose words like "page" just in case.
        sel = sel.replace("page", "").replace("Page", "").strip()
        if sel:
            pages_arg = ["-P", sel] if sender.endswith("lp") else ["-o", f"page-ranges={sel}"]
    cmd = [sender]
    if printer_name and printer_name != "default":
        cmd += (["-d", printer_name] if sender.endswith("lp") else ["-P", printer_name])
    cmd += pages_arg
    for _ in range(max(1, copies)):
        cmd_c = cmd + [str(pdf_path)]
        try:
            subprocess.run(cmd_c, check=False, capture_output=True, text=True, errors="ignore")
        except Exception as e:
            logger.warning(f"[PrinterTool] POSIX print error: {e}")
            return False
    return True


def _print_pdf_cross_platform(pdf_path: Path, printer_name: str, copies: int = 1, page_selection: Optional[Union[str, int]] = None) -> bool:
    """Dispatch a print job using the best available backend for the OS."""
    if IS_WINDOWS and pymupdf and win32ui and win32print:
        return _print_pdf_direct_gdi(pdf_path, printer_name, copies=copies, page_selection=page_selection)
    if shutil.which("lp") or shutil.which("lpr"):
        return _print_pdf_posix(pdf_path, printer_name, copies=copies, page_selection=page_selection)
    # No GDI and no CUPS — cannot actually print, but report honestly.
    return False


def _print_pdf_direct_gdi(pdf_path: Path, printer_name: str, copies: int = 1, page_selection: Optional[Union[str, int]] = None) -> bool:
    """Render selected PDF pages and send direct GDI raster print jobs to the Windows printer DC."""
    if not pymupdf or not win32ui or not win32print:
        return False

    doc = pymupdf.open(str(pdf_path))
    total_pages = len(doc)
    selected_indices = _parse_page_selection(page_selection, total_pages)

    for copy_idx in range(copies):
        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(printer_name)
        page_info = f"Pages {[idx+1 for idx in selected_indices]}" if len(selected_indices) < total_pages else "All Pages"
        hdc.StartDoc(f"VISION Print - {pdf_path.name} ({page_info} - Copy {copy_idx + 1}/{copies})")

        printable_width = hdc.GetDeviceCaps(win32con.HORZRES)
        printable_height = hdc.GetDeviceCaps(win32con.VERTRES)

        for page_idx in selected_indices:
            page = doc[page_idx]
            pix = page.get_pixmap(dpi=300)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            hdc.StartPage()
            dib = ImageWin.Dib(img)
            dib.draw(hdc.GetHandleOutput(), (0, 0, printable_width, printable_height))
            hdc.EndPage()

        hdc.EndDoc()
        hdc.DeleteDC()
        time.sleep(0.5)

    doc.close()
    return True


@tool(name="print_document", description="Print one or multiple copies of a document (e.g. 'Venture Journey', 'Experiment_2.pdf') or specific pages (e.g. page_number='5' or pages='1-3') to the connected physical printer.")
def print_document(file_path: str, copies: int = 1, pages: Optional[Union[str, int]] = None, page_number: Optional[Union[str, int]] = None, printer_name: Optional[str] = None) -> str:
    """Send document or specific page numbers directly to physical printer via Windows GDI driver."""
    from vision.tools.file_tools import _resolve_user_path

    p = _resolve_user_path(file_path, find_existing_file=True)
    if not p.exists():
        return f"Error: Document '{file_path}' does not exist."
    if p.is_dir():
        return (
            f"Error: '{p}' is a folder, not a printable document. "
            f"Please provide the path to a specific PDF file."
        )
    if p.suffix.lower() != ".pdf":
        return (
            f"Error: '{p.name}' is not a PDF. The direct GDI printer pipeline "
            f"only supports .pdf documents (convert or export first)."
        )

    # 1. Verify Printer Connection
    chk = check_printer_available(printer_name)
    if not chk["available"]:
        err_msg = chk.get("error") or "No printer is connected."
        logger.warning(f"[PrinterTool] Print job aborted: {err_msg}")
        return f"Cannot print: {err_msg} Please ensure your printer is plugged in and powered on."

    target_printer = chk["name"]
    selected_page = page_number or pages
    page_desc = f"page {selected_page}" if selected_page else "all pages"
    logger.info(f"[PrinterTool] Printing {copies} copies of '{p.name}' ({page_desc}) to '{target_printer}' via Direct GDI")

    # 2. Dispatch print job using the best available backend for this OS
    try:
        success = _print_pdf_cross_platform(p, target_printer, copies=copies, page_selection=selected_page)
        if not success:
            return f"Error: no usable print backend available for '{target_printer}' on this OS."

        working_memory.record_file(str(p))
        return f"Successfully sent {copies} {'copy' if copies == 1 else 'copies'} of '{p.name}' ({page_desc}) directly to printer '{target_printer}'."
    except Exception as e:
        logger.error(f"[PrinterTool] GDI Print failed: {e}")
        return f"Error sending print job to '{target_printer}': {e}"


@tool(name="create_and_print_bordered_document", description="Create an A4 document with 1.5 cm border margins on all 4 sides and print the requested number of copies directly.")
def create_and_print_bordered_document(margin_cm: float = 1.5, copies: int = 2) -> str:
    """Generate bordered A4 paper and send to printer in a single automated step."""
    file_name = "plain_a4_bordered_paper.pdf"
    create_res = create_bordered_a4_document(margin_cm=margin_cm, file_name=file_name)
    if create_res.startswith("Error"):
        return create_res

    doc_path = str(Path.home() / "Documents" / file_name)
    print_res = print_document(file_path=doc_path, copies=copies)
    return f"{create_res}\n{print_res}"
