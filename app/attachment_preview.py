"""V3 : aperçu d'une pièce jointe reçue, avant de la télécharger.

PDF et images : affichés tels quels par le navigateur (adresse de la pièce jointe).
Word (.docx) : converti en HTML simple (mammoth). Excel (.xlsx) et CSV : tableau des premières
lignes. Texte : les premiers caractères. Le HTML produit est affiché dans un cadre « sandbox »
sans script, avec ses images intégrées seulement (rien n'est chargé depuis Internet).
Anciens formats (.doc, .xls), archives, etc. : pas d'aperçu, on télécharge.
"""
from __future__ import annotations

import csv
import html
import io

MAX_BYTES = 15 * 1024 * 1024
MAX_ROWS, MAX_COLS, MAX_SHEETS = 200, 30, 5
MAX_TEXT = 200_000

IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"}
DOCX_TYPES = {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
XLSX_TYPES = {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel.sheet.macroenabled.12"}


def kind_of(ctype: str, name: str) -> str | None:
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ctype == "application/pdf" or ext == "pdf":
        return "pdf"
    if ctype in IMAGE_TYPES:
        return "image"
    if ctype in DOCX_TYPES or ext == "docx":
        return "docx"
    if ctype in XLSX_TYPES or ext in ("xlsx", "xlsm"):
        return "xlsx"
    if ctype == "text/csv" or ext == "csv":
        return "csv"
    if ctype == "text/plain" or ext == "txt":
        return "text"
    return None


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _table(rows: list[list], title: str | None = None) -> str:
    out = [f"<h3>{html.escape(title)}</h3>"] if title else []
    out.append("<table>")
    for r in rows:
        out.append("<tr>" + "".join(f"<td>{html.escape('' if c is None else str(c))}</td>" for c in r[:MAX_COLS]) + "</tr>")
    out.append("</table>")
    return "".join(out)


def preview(data: bytes, ctype: str, name: str) -> dict:
    kind = kind_of(ctype, name)
    if kind is None:
        return {"kind": "none"}
    if len(data) > MAX_BYTES:
        return {"kind": "none", "reason": "Fichier trop lourd pour l'aperçu : téléchargez-le."}
    if kind in ("pdf", "image"):
        return {"kind": kind}
    try:
        if kind == "text":
            text = _decode(data)
            return {"kind": "text", "text": text[:MAX_TEXT], "truncated": len(text) > MAX_TEXT}
        if kind == "csv":
            text = _decode(data)
            sample = text[:4096]
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
            except csv.Error:
                dialect = csv.excel
            rows = [r for _, r in zip(range(MAX_ROWS + 1), csv.reader(io.StringIO(text), dialect))]
            return {"kind": "html", "html": _table(rows[:MAX_ROWS]), "truncated": len(rows) > MAX_ROWS}
        if kind == "docx":
            import mammoth
            res = mammoth.convert_to_html(io.BytesIO(data))
            return {"kind": "html", "html": res.value or "<p><i>Document vide.</i></p>"}
        if kind == "xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            parts, truncated = [], False
            for ws in wb.worksheets[:MAX_SHEETS]:
                rows = []
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i >= MAX_ROWS:
                        truncated = True
                        break
                    rows.append(list(row))
                while rows and all(c in (None, "") for c in rows[-1]):
                    rows.pop()
                parts.append(_table(rows, ws.title if len(wb.worksheets) > 1 else None))
            truncated = truncated or len(wb.worksheets) > MAX_SHEETS
            wb.close()
            return {"kind": "html", "html": "".join(parts) or "<p><i>Classeur vide.</i></p>", "truncated": truncated}
    except Exception:  # noqa: BLE001 – fichier abîmé ou protégé : on propose de le télécharger
        return {"kind": "none", "reason": "Aperçu impossible pour ce fichier : téléchargez-le."}
    return {"kind": "none"}
