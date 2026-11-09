"""
Servicio de Monitoreo de Transporte y Seguimiento en Vivo (SharePoint / Excel).
Lee y estructura la información operativa de la 'Tabla3' en la hoja 'Perú' del archivo
'Monitoreo General UT Provincia 2030.xlsx'.

Arquitectura Google ADK:
- Soporta lectura local (OneDrive/SharePoint sincronizado en Windows).
- Lectura resiliente contra bloqueos exclusivos de Microsoft Excel (Win32 API FILE_SHARE_READ | FILE_SHARE_WRITE).
- Parser dual: OpenPyXL de alto rendimiento + Parser XML nativo (zipfile + ElementTree) con cero dependencias externas.
- Mapeo directo por letras de columnas (O=TIM, AO=UBICACIÓN, AJ=TRACTO, U=FIN DE CARGA, etc.) y cabeceras dinámicas.
- Caché en memoria con invalidación automática basada en timestamp (mtime).
- Diagnóstico automático persistente en data/monitoreo_status.json.
"""

import io
import os
import sys
import json
import re
import shutil
import logging
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, date, time as dt_time, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

from backend.config import settings

logger = logging.getLogger("backend.monitoreo_service")


class MonitoreoService:
    """
    Gestor de lectura y búsqueda sobre el archivo de monitoreo operativo de transporte a provincia y locales.
    """

    def __init__(self, excel_path: Optional[str] = None):
        self.excel_path_str = excel_path or settings.MONITOREO_EXCEL_PATH
        self._cached_records: Optional[List[Dict[str, Any]]] = None
        self._last_mtime: float = 0.0
        self._last_size: int = 0

    def clear_cache(self):
        """Purga la memoria caché de monitoreo para forzar recarga inmediata de disco."""
        self._cached_records = None
        self._last_mtime = 0.0
        self._last_size = 0
        logger.info("🧹 Caché de MonitoreoService purgada exitosamente.")

    def _get_excel_path(self) -> Optional[Path]:
        """
        Resuelve la ruta del archivo y verifica su existencia.
        Si existen varias copias (OneDrive / local data), selecciona automáticamente
        la que tenga la fecha de modificación más reciente para garantizar datos en vivo.
        """
        candidates = [
            Path(self.excel_path_str),
            Path.home() / "Falabella" / "DATA ANALITYCS PL - Documentos" / "Proyectos Test" / "Transporte" / "Monitoreo General UT Provincia 2030.xlsx",
            Path(r"C:\Users\fhurtadoa\Falabella\DATA ANALITYCS PL - Documentos\Proyectos Test\Transporte\Monitoreo General UT Provincia 2030.xlsx"),
            Path(__file__).resolve().parent.parent.parent / "data" / "Monitoreo General UT Provincia 2030.xlsx",
            Path.home() / "OneDrive - Falabella" / "Documentos" / "GitHub" / "agent-test" / "data" / "Monitoreo General UT Provincia 2030.xlsx"
        ]
        existing = [c for c in candidates if c.exists() and c.is_file()]
        if not existing:
            return None

        # Seleccionar la copia con mayor timestamp de modificación (la más fresca)
        try:
            latest = max(existing, key=lambda p: p.stat().st_mtime)
            return latest
        except Exception:
            return existing[0]

    def _read_bytes_safely(self, file_path: Path) -> Optional[io.BytesIO]:
        """
        Lee el archivo en un búfer binario en memoria.
        Maneja bloqueos exclusivos de Microsoft Excel en Windows mediante Win32 API
        con flags FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE.
        """
        # 1. En Windows: usar CreateFileW con permisos de compartir completos
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes

                GENERIC_READ = 0x80000000
                FILE_SHARE_READ = 0x00000001
                FILE_SHARE_WRITE = 0x00000002
                FILE_SHARE_DELETE = 0x00000004
                OPEN_EXISTING = 3
                FILE_ATTRIBUTE_NORMAL = 0x80

                kernel32 = ctypes.windll.kernel32
                handle = kernel32.CreateFileW(
                    str(file_path),
                    GENERIC_READ,
                    FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                    None,
                    OPEN_EXISTING,
                    FILE_ATTRIBUTE_NORMAL,
                    None
                )
                if handle not in (-1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
                    try:
                        file_size = wintypes.LARGE_INTEGER()
                        if kernel32.GetFileSizeEx(handle, ctypes.byref(file_size)):
                            size_val = file_size.value
                            if size_val > 0:
                                buf = ctypes.create_string_buffer(size_val)
                                bytes_read = wintypes.DWORD()
                                if kernel32.ReadFile(handle, buf, size_val, ctypes.byref(bytes_read), None):
                                    raw_data = buf.raw[:bytes_read.value]
                                    logger.info(f"✅ Archivo leído exitosamente vía Win32 compartido ({len(raw_data)} bytes)")
                                    return io.BytesIO(raw_data)
                    finally:
                        kernel32.CloseHandle(handle)
            except Exception as win_err:
                logger.warning(f"Intento Win32 compartido arrojó excepción: {win_err}. Continuando con lectura estándar...")

        # 2. Intento directo de lectura estándar
        try:
            with open(file_path, "rb") as f:
                raw_bytes = f.read()
                if raw_bytes:
                    return io.BytesIO(raw_bytes)
        except Exception as e:
            logger.warning(f"Aviso de lectura directa en {file_path.name}: {e}. Intentando lectura vía copia sombra...")

        # 3. Intento de copia temporal para evitar bloqueos
        temp_dir = tempfile.gettempdir()
        temp_file = Path(temp_dir) / f"monitoreo_shadow_{os.getpid()}_{int(datetime.now().timestamp())}.xlsx"
        try:
            shutil.copy2(file_path, temp_file)
            with open(temp_file, "rb") as f:
                data = io.BytesIO(f.read())
            return data
        except Exception as ex:
            logger.error(f"Error al leer archivo mediante copia temporal: {ex}")
            return None
        finally:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass

    def _format_cell_value(self, val: Any) -> str:
        """Limpia y da formato legible a valores de celdas (fechas, horas, números, textos)."""
        if val is None:
            return ""
        if isinstance(val, (datetime, date)):
            if isinstance(val, datetime):
                return val.strftime("%Y-%m-%d %H:%M:%S")
            return val.strftime("%Y-%m-%d")
        if isinstance(val, dt_time):
            return val.strftime("%H:%M:%S")
        if isinstance(val, float):
            if val.is_integer():
                return str(int(val))
            return f"{val:.2f}"
        s = str(val).strip()
        if s.lower() in ("nan", "none", "nat", "null"):
            return ""
        # Limpiar '.0' al final si es número entero en string
        s = re.sub(r'\.0+$', '', s)
        return s

    def _clean_key(self, val: Any) -> str:
        """Normaliza cadenas para búsqueda eliminando guiones, espacios y acentos."""
        if not val:
            return ""
        s = str(val).upper().strip()
        # Eliminar sufijo .0 si vino de float serializado
        s = re.sub(r'\.0+$', '', s)
        return re.sub(r'[^A-Z0-9]', '', s)

    def _parse_xlsx_xml(self, buffer: io.BytesIO) -> List[Dict[str, Any]]:
        """
        Parsea directamente el contenido de un archivo .xlsx usando la biblioteca estándar (zipfile + XML).
        Garantiza funcionamiento sin dependencias externas (sin necesidad de openpyxl o pandas)
        y con mapeo directo por letras de columnas (O -> TIM, AO -> UBICACIÓN, AJ -> TRACTO, etc.).
        """
        records = []
        try:
            buffer.seek(0)
            with zipfile.ZipFile(buffer, 'r') as z:
                # 1. Cargar cadenas compartidas (sharedStrings.xml)
                shared_strings = []
                if "xl/sharedStrings.xml" in z.namelist():
                    sst_data = z.read("xl/sharedStrings.xml")
                    root = ET.fromstring(sst_data)
                    for si in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
                        texts = [t.text for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t") if t.text]
                        shared_strings.append("".join(texts))

                # 2. Localizar hoja 'Perú' en workbook.xml y rels
                sheet_target = None
                if "xl/workbook.xml" in z.namelist():
                    wb_root = ET.fromstring(z.read("xl/workbook.xml"))
                    target_r_id = None
                    for sheet in wb_root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet"):
                        name = sheet.attrib.get("name", "").strip().lower()
                        if name in ("perú", "peru"):
                            target_r_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                            break
                    if not target_r_id:
                        for sheet in wb_root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet"):
                            target_r_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                            break

                    if target_r_id and "xl/_rels/workbook.xml.rels" in z.namelist():
                        rels_root = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
                        for rel in rels_root.iter("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
                            if rel.attrib.get("Id") == target_r_id:
                                target = rel.attrib.get("Target", "")
                                if not target.startswith("xl/"):
                                    target = f"xl/{target}"
                                sheet_target = target
                                break

                if not sheet_target:
                    candidates = [n for n in z.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
                    if candidates:
                        sheet_target = candidates[0]
                    else:
                        return []

                # 3. Parsear hoja
                sheet_root = ET.fromstring(z.read(sheet_target))
                sheet_data = sheet_root.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheetData")
                if sheet_data is None:
                    return []

                # Mapeo oficial de columnas por letras estándar proporcionadas por la operación
                default_col_map = {
                    "N": "origen",
                    "O": "tim",
                    "P": "placa",
                    "R": "destino",
                    "U": "fin_de_carga",
                    "AF": "punto",
                    "AG": "carga",
                    "AH": "tipo_ut",
                    "AJ": "tracto",
                    "AK": "salida_cd",
                    "AL": "salida_ruta",
                    "AM": "llegada_destino",
                    "AN": "registro_destino",
                    "AO": "ubicacion",
                    "AP": "status",
                    "BM": "motivo"
                }

                col_map = dict(default_col_map)
                header_detected = False

                for row_elem in sheet_data.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
                    row_cells: Dict[str, str] = {}
                    for c in row_elem.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
                        r_ref = c.attrib.get("r", "")
                        col_letter = "".join(filter(str.isalpha, r_ref)).upper()
                        c_type = c.attrib.get("t")
                        val_elem = c.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")

                        val_str = ""
                        if val_elem is not None and val_elem.text is not None:
                            raw_v = val_elem.text
                            if c_type == "s":
                                try:
                                    s_idx = int(raw_v)
                                    val_str = shared_strings[s_idx] if s_idx < len(shared_strings) else raw_v
                                except Exception:
                                    val_str = raw_v
                            else:
                                val_str = raw_v
                        else:
                            is_elem = c.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}is")
                            if is_elem is not None:
                                val_str = "".join([t.text for t in is_elem.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t") if t.text])

                        if col_letter:
                            row_cells[col_letter] = self._format_cell_value(val_str)

                    if not row_cells:
                        continue

                    # Detectar encabezados si la fila contiene 'TIM' o palabras clave
                    if not header_detected:
                        values_upper = {k: v.upper() for k, v in row_cells.items()}
                        has_tim = any(v == "TIM" or v.startswith("TIM") for v in values_upper.values())
                        has_keywords = sum(1 for v in values_upper.values() if any(kw in v for kw in ["TRACTO", "UBICACI", "DESTINO", "CARGA", "SALIDA"])) >= 2
                        if has_tim or has_keywords:
                            for col_letter, h_text in values_upper.items():
                                if not h_text:
                                    continue
                                if "ORIGEN" in h_text:
                                    col_map[col_letter] = "origen"
                                elif h_text == "TIM" or h_text.startswith("TIM"):
                                    col_map[col_letter] = "tim"
                                elif "TRACTO" in h_text:
                                    col_map[col_letter] = "tracto"
                                elif "PLACA" in h_text or h_text in ("CARRETA", "REMOLQUE", "UNIDAD"):
                                    col_map[col_letter] = "placa"
                                elif "DESTINO" in h_text:
                                    col_map[col_letter] = "destino"
                                elif "FIN" in h_text and "CARGA" in h_text:
                                    col_map[col_letter] = "fin_de_carga"
                                elif "PUNTO" in h_text:
                                    col_map[col_letter] = "punto"
                                elif h_text == "CARGA" or h_text.startswith("CARGA"):
                                    col_map[col_letter] = "carga"
                                elif "TIPO" in h_text and "UT" in h_text:
                                    col_map[col_letter] = "tipo_ut"
                                elif "SALIDA" in h_text and "CD" in h_text:
                                    col_map[col_letter] = "salida_cd"
                                elif "SALIDA" in h_text and "RUTA" in h_text:
                                    col_map[col_letter] = "salida_ruta"
                                elif "LLEGADA" in h_text and "DESTINO" in h_text:
                                    col_map[col_letter] = "llegada_destino"
                                elif "REGISTRO" in h_text and "DESTINO" in h_text:
                                    col_map[col_letter] = "registro_destino"
                                elif "UBICACI" in h_text:
                                    col_map[col_letter] = "ubicacion"
                                elif "STATUS" in h_text or "ESTADO" in h_text:
                                    col_map[col_letter] = "status"
                                elif "MOTIVO" in h_text or "PERCANCE" in h_text or "OBSERVACI" in h_text:
                                    col_map[col_letter] = "motivo"
                            header_detected = True
                            continue

                    # Extraer registro de datos
                    tim_col = next((k for k, v in col_map.items() if v == "tim"), "O")
                    tim_val = row_cells.get(tim_col, "")
                    clean_t = self._clean_key(tim_val)
                    if not clean_t or clean_t == "TIM" or not any(ch.isdigit() for ch in clean_t):
                        continue

                    item = {}
                    for letter, field in col_map.items():
                        item[field] = row_cells.get(letter, "")

                    if not item.get("motivo"):
                        item["motivo"] = "Sin incidencias reportadas"

                    item["_clean_tim"] = clean_t
                    item["_clean_placa"] = self._clean_key(item.get("placa", ""))
                    item["_clean_tracto"] = self._clean_key(item.get("tracto", ""))
                    item["_clean_destino"] = self._clean_key(item.get("destino", ""))
                    records.append(item)

            logger.info(f"✅ Parser XML nativo extrajo exitosamente {len(records)} registros.")
            return records
        except Exception as e:
            logger.error(f"Error en _parse_xlsx_xml: {e}", exc_info=True)
            return []

    def _parse_xlsx_openpyxl(self, buffer: io.BytesIO) -> List[Dict[str, Any]]:
        """Parsea usando openpyxl si está disponible en el entorno."""
        try:
            import openpyxl

            buffer.seek(0)
            wb = openpyxl.load_workbook(buffer, data_only=True, read_only=False)

            sheet_name = None
            for name in wb.sheetnames:
                if name.strip().lower() in ("perú", "peru"):
                    sheet_name = name
                    break
            if not sheet_name:
                sheet_name = wb.sheetnames[0]

            ws = wb[sheet_name]

            # Mapeo por defecto de letras de columna
            default_col_letters = {
                "N": "origen",
                "O": "tim",
                "P": "placa",
                "R": "destino",
                "U": "fin_de_carga",
                "AF": "punto",
                "AG": "carga",
                "AH": "tipo_ut",
                "AJ": "tracto",
                "AK": "salida_cd",
                "AL": "salida_ruta",
                "AM": "llegada_destino",
                "AN": "registro_destino",
                "AO": "ubicacion",
                "AP": "status",
                "BM": "motivo"
            }
            col_letter_map = dict(default_col_letters)
            header_detected = False
            records: List[Dict[str, Any]] = []

            for row in ws.iter_rows(values_only=False):
                if not row or all(c.value is None for c in row):
                    continue

                row_cells: Dict[str, str] = {}
                for cell in row:
                    letter = cell.column_letter.upper()
                    row_cells[letter] = self._format_cell_value(cell.value)

                # Detección de fila de cabecera
                if not header_detected:
                    values_upper = {k: v.upper() for k, v in row_cells.items()}
                    has_tim = any(v == "TIM" or v.startswith("TIM") for v in values_upper.values())
                    has_keywords = sum(1 for v in values_upper.values() if any(kw in v for kw in ["TRACTO", "UBICACI", "DESTINO", "CARGA", "SALIDA"])) >= 2
                    if has_tim or has_keywords:
                        for col_letter, h_text in values_upper.items():
                            if not h_text:
                                continue
                            if "ORIGEN" in h_text:
                                col_letter_map[col_letter] = "origen"
                            elif h_text == "TIM" or h_text.startswith("TIM"):
                                col_letter_map[col_letter] = "tim"
                            elif "TRACTO" in h_text:
                                col_letter_map[col_letter] = "tracto"
                            elif "PLACA" in h_text or h_text in ("CARRETA", "REMOLQUE", "UNIDAD"):
                                col_letter_map[col_letter] = "placa"
                            elif "DESTINO" in h_text:
                                col_letter_map[col_letter] = "destino"
                            elif "FIN" in h_text and "CARGA" in h_text:
                                col_letter_map[col_letter] = "fin_de_carga"
                            elif "PUNTO" in h_text:
                                col_letter_map[col_letter] = "punto"
                            elif h_text == "CARGA" or h_text.startswith("CARGA"):
                                col_letter_map[col_letter] = "carga"
                            elif "TIPO" in h_text and "UT" in h_text:
                                col_letter_map[col_letter] = "tipo_ut"
                            elif "SALIDA" in h_text and "CD" in h_text:
                                col_letter_map[col_letter] = "salida_cd"
                            elif "SALIDA" in h_text and "RUTA" in h_text:
                                col_letter_map[col_letter] = "salida_ruta"
                            elif "LLEGADA" in h_text and "DESTINO" in h_text:
                                col_letter_map[col_letter] = "llegada_destino"
                            elif "REGISTRO" in h_text and "DESTINO" in h_text:
                                col_letter_map[col_letter] = "registro_destino"
                            elif "UBICACI" in h_text:
                                col_letter_map[col_letter] = "ubicacion"
                            elif "STATUS" in h_text or "ESTADO" in h_text:
                                col_letter_map[col_letter] = "status"
                            elif "MOTIVO" in h_text or "PERCANCE" in h_text or "OBSERVACI" in h_text:
                                col_letter_map[col_letter] = "motivo"
                        header_detected = True
                        continue

                # Procesar fila de datos
                tim_col = next((k for k, v in col_letter_map.items() if v == "tim"), "O")
                tim_val = row_cells.get(tim_col, "")
                clean_t = self._clean_key(tim_val)
                if not clean_t or clean_t == "TIM" or not any(ch.isdigit() for ch in clean_t):
                    continue

                item = {}
                for letter, field in col_letter_map.items():
                    item[field] = row_cells.get(letter, "")

                if not item.get("motivo"):
                    item["motivo"] = "Sin incidencias reportadas"

                item["_clean_tim"] = clean_t
                item["_clean_placa"] = self._clean_key(item.get("placa", ""))
                item["_clean_tracto"] = self._clean_key(item.get("tracto", ""))
                item["_clean_destino"] = self._clean_key(item.get("destino", ""))
                records.append(item)

            logger.info(f"✅ OpenPyXL extrajo exitosamente {len(records)} registros.")
            return records
        except Exception as e:
            logger.warning(f"Aviso en _parse_xlsx_openpyxl: {e}. Se utilizará el parser XML nativo.")
            return []

    def _save_diagnostic(self, path: Optional[Path], records: List[Dict[str, Any]], error_msg: Optional[str] = None):
        """Guarda un reporte diagnóstico en JSON para monitorear la salud de la carga de datos."""
        try:
            diag_file = Path(__file__).resolve().parent.parent.parent / "data" / "monitoreo_status.json"
            diag_file.parent.mkdir(parents=True, exist_ok=True)
            diag_data = {
                "timestamp": datetime.now().isoformat(),
                "file_path": str(path) if path else self.excel_path_str,
                "file_exists": path.exists() if path else False,
                "file_size_bytes": path.stat().st_size if (path and path.exists()) else 0,
                "total_records": len(records),
                "error": error_msg,
                "sample_tims": [r.get("tim") for r in records[:10]],
                "target_tim_676169276": next((r for r in records if r.get("_clean_tim") == "676169276"), None)
            }
            with open(diag_file, "w", encoding="utf-8") as f:
                json.dump(diag_data, f, ensure_ascii=False, indent=2)
        except Exception as ex:
            logger.warning(f"No se pudo guardar diagnóstico: {ex}")

    def _load_records(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Carga y parsea la información de la hoja 'Perú' (Tabla3) en memoria.
        Utiliza caché basado en la fecha de modificación (mtime) del archivo.
        """
        path = self._get_excel_path()
        if not path:
            logger.warning(f"⚠️ No se encontró el archivo de monitoreo en: {self.excel_path_str}")
            self._save_diagnostic(None, [], error_msg=f"Archivo no encontrado en {self.excel_path_str}")
            return []

        try:
            current_mtime = path.stat().st_mtime
            current_size = path.stat().st_size
        except Exception:
            current_mtime = 0.0
            current_size = 0

        # Si no se fuerza el refresco y tanto la fecha de modificación como el tamaño son idénticos, reutilizar caché
        if not force_refresh and self._cached_records is not None:
            if current_mtime == self._last_mtime and current_size == self._last_size and current_mtime > 0:
                return self._cached_records

        logger.info(f"🔄 Cargando reporte de monitoreo de unidades desde: {path} (mtime={current_mtime}, size={current_size})...")
        buffer = self._read_bytes_safely(path)
        if not buffer:
            self._save_diagnostic(path, [], error_msg="No se pudo leer búfer de bytes del archivo (bloqueo o permisos)")
            return self._cached_records or []

        # Intentar primero con OpenPyXL; si falla o no está instalado, usar el parser XML nativo
        records = self._parse_xlsx_openpyxl(buffer)
        if not records:
            logger.info("Ejecutando parser nativo XML (zipfile + ElementTree)...")
            records = self._parse_xlsx_xml(buffer)

        self._cached_records = records
        self._last_mtime = current_mtime
        self._last_size = current_size
        self._save_diagnostic(path, records)
        logger.info(f"✅ Se cargaron exitosamente {len(records)} registros de monitoreo de transporte.")
        return records

    def _parse_datetime(self, val: Any) -> Optional[datetime]:
        """Parsea fechas en diversos formatos de Excel (texto, serial number, etc.)."""
        if not val:
            return None
        if isinstance(val, datetime):
            return val
        if isinstance(val, (int, float)):
            try:
                if float(val) > 30000:
                    return datetime(1899, 12, 30) + timedelta(days=float(val))
            except Exception:
                pass
        s = str(val).strip()
        try:
            f = float(s)
            if f > 30000:
                return datetime(1899, 12, 30) + timedelta(days=f)
        except Exception:
            pass

        for fmt in (
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%d-%m-%Y %H:%M:%S",
            "%d-%m-%Y %H:%M"
        ):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue

        m = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})\s*(\d{1,2}):(\d{2})', s)
        if m:
            d, mth, y, h, mn = map(int, m.groups())
            try:
                return datetime(y, mth, d, h, mn)
            except Exception:
                pass

        return None

    def _is_same_trip_time_window(self, dt1: Optional[datetime], dt2: Optional[datetime], raw_str1: str = "", raw_str2: str = "") -> bool:
        """
        Valida si dos registros pertenecen al mismo viaje verificando que FIN DE CARGA
        se encuentre dentro de una ventana de tolerancia de ±2 horas.
        """
        if dt1 and dt2:
            diff_seconds = abs((dt1 - dt2).total_seconds())
            return diff_seconds <= 2 * 3600  # 2 horas = 7200 segundos

        if dt1 and raw_str2:
            dt2_cand = self._parse_datetime(raw_str2)
            if dt2_cand:
                return abs((dt1 - dt2_cand).total_seconds()) <= 2 * 3600

        if raw_str1 and raw_str2:
            d1 = raw_str1[:10].replace("-", "/")
            d2 = raw_str2[:10].replace("-", "/")
            if d1 == d2 and len(d1) >= 8:
                return True

        return False

    def _enrich_with_trip_itinerary(self, item: Dict[str, Any], all_records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analiza si la unidad realiza un viaje con carga ÚNICA o COMPARTIDA,
        identificando todas las paradas (Punto 1, 2, 3...) del camión dentro de la ventana
        de ±2 horas de FIN DE CARGA, y el orden en que visitará cada tienda.
        """
        target_placa = item.get("_clean_placa") or item.get("_clean_tracto")
        target_tracto = item.get("_clean_tracto")
        target_dt = self._parse_datetime(item.get("fin_de_carga"))
        target_tim = item.get("_clean_tim")

        if not target_placa and not target_tracto:
            item["tipo_carga"] = item.get("carga") or "UNICA"
            item["total_puntos"] = 1
            item["itinerario_paradas"] = []
            item["descripcion_viaje"] = "Viaje a punto único."
            return item

        related_stops = []
        for r in all_records:
            match_p = False
            if target_placa:
                match_p = (r.get("_clean_placa") == target_placa or r.get("_clean_tracto") == target_placa)
            if not match_p and target_tracto:
                match_p = (r.get("_clean_tracto") == target_tracto or r.get("_clean_placa") == target_tracto)

            if not match_p:
                continue

            r_dt = self._parse_datetime(r.get("fin_de_carga"))
            if target_dt and r_dt:
                if not self._is_same_trip_time_window(target_dt, r_dt):
                    continue
            elif target_dt or r_dt:
                if not self._is_same_trip_time_window(target_dt, r_dt, item.get("fin_de_carga", ""), r.get("fin_de_carga", "")):
                    continue

            related_stops.append(r)

        if not related_stops:
            related_stops = [item]

        def get_punto_num(row):
            p_str = str(row.get("punto", "")).strip()
            try:
                nums = re.findall(r'\d+', p_str)
                return int(nums[0]) if nums else 99
            except Exception:
                return 99

        related_stops.sort(key=get_punto_num)

        itinerario = []
        seen_tims = set()
        for idx, s in enumerate(related_stops, start=1):
            s_tim = s.get("tim", "")
            if s_tim in seen_tims:
                continue
            seen_tims.add(s_tim)

            p_num = get_punto_num(s)
            if p_num == 99:
                p_num = idx

            itinerario.append({
                "punto": p_num,
                "tienda": s.get("destino", ""),
                "tim": s_tim,
                "fin_de_carga": s.get("fin_de_carga", "")
            })

        itinerario.sort(key=lambda x: x["punto"])

        tiendas_distintas = set(x["tienda"] for x in itinerario if x["tienda"])
        total_puntos_count = len(itinerario)
        es_compartido = (total_puntos_count > 1 or len(tiendas_distintas) > 1 or "COMPARTID" in str(item.get("carga", "")).upper())

        item["tipo_carga"] = "COMPARTIDO" if es_compartido else "UNICA"
        item["total_puntos"] = max(total_puntos_count, len(tiendas_distintas), 1)
        item["itinerario_paradas"] = itinerario

        punto_tim_consultada = None
        for step in itinerario:
            if target_tim and self._clean_key(step["tim"]) == target_tim:
                punto_tim_consultada = step["punto"]
                break

        item["punto_entrega_tim_consultada"] = punto_tim_consultada or get_punto_num(item)

        if es_compartido and len(itinerario) > 1:
            ruta_texto = " ➔ ".join([f"Punto {s['punto']}: Tienda {s['tienda']}" for s in itinerario])
            orden_msg = ""
            if punto_tim_consultada:
                if punto_tim_consultada == 1:
                    orden_msg = f"La TIM consultada ({item.get('tim')}) se entregará en 1ER LUGAR (primera parada, Tienda {item.get('destino')})."
                elif punto_tim_consultada == len(itinerario):
                    primera = itinerario[0]
                    orden_msg = f"El camión irá PRIMERO a la tienda {primera['tienda']} (Punto 1) y entregará la TIM consultada ({item.get('tim')}) en ÚLTIMO LUGAR (Punto {punto_tim_consultada}, Tienda {item.get('destino')})."
                else:
                    primera = itinerario[0]
                    orden_msg = f"El camión irá primero a la tienda {primera['tienda']} (Punto 1) y entregará la TIM consultada ({item.get('tim')}) en {punto_tim_consultada}° lugar (Punto {punto_tim_consultada}, Tienda {item.get('destino')})."

            item["descripcion_viaje"] = (
                f"Viaje con carga COMPARTIDA ({len(itinerario)} paradas). "
                f"Ruta programada de la unidad (Placa {item.get('placa')} / Tracto {item.get('tracto')}): {ruta_texto}. "
                f"{orden_msg}"
            )
        else:
            item["descripcion_viaje"] = f"Viaje con carga ÚNICA (exclusivo para Tienda {item.get('destino')}, 1 punto de entrega)."

        return item

    def buscar_monitoreo(
        self,
        tim: Optional[Any] = None,
        placa: Optional[str] = None,
        tienda: Optional[str] = None,
        tracto: Optional[str] = None,
        status: Optional[str] = None,
        force_refresh: bool = False,
        limit: int = 15
    ) -> List[Dict[str, Any]]:
        """
        Busca registros en el reporte de monitoreo en tiempo real por TIM, placa, tienda o tracto.
        """
        records = self._load_records(force_refresh=force_refresh)
        if not records:
            return []

        clean_tim = self._clean_key(tim)
        clean_placa = self._clean_key(placa)
        clean_tienda = self._clean_key(tienda)
        clean_tracto = self._clean_key(tracto)
        clean_status = self._clean_key(status)

        coincidencias = []
        for r in records:
            # 1. Filtro por TIM: Si se pasa TIM y coincide exactamente o parcialmente
            if clean_tim:
                if clean_tim != r["_clean_tim"] and clean_tim not in r["_clean_tim"]:
                    continue

            # 2. Filtro por Placa (puede coincidir con la placa de carreta O con la placa del tracto)
            if clean_placa:
                match_placa = (clean_placa == r["_clean_placa"] or clean_placa in r["_clean_placa"])
                match_tracto = (clean_placa == r["_clean_tracto"] or clean_placa in r["_clean_tracto"])
                if not (match_placa or match_tracto):
                    if not (clean_tim and (clean_tim == r["_clean_tim"] or clean_tim in r["_clean_tim"])):
                        continue

            # 3. Filtro por Tienda destino
            if clean_tienda:
                if clean_tienda != r["_clean_destino"] and clean_tienda not in r["_clean_destino"]:
                    continue

            # 4. Filtro por Tracto
            if clean_tracto:
                if clean_tracto != r["_clean_tracto"] and clean_tracto not in r["_clean_tracto"]:
                    continue

            # 5. Filtro por Status
            if clean_status:
                if clean_status not in self._clean_key(r.get("status", "")):
                    continue

            # Enriquecer con análisis de itinerario de viaje (Compartido vs Único y secuencia de paradas)
            enriched = self._enrich_with_trip_itinerary(dict(r), records)
            res = {k: v for k, v in enriched.items() if not k.startswith("_")}
            coincidencias.append(res)
            if len(coincidencias) >= limit:
                break

        return coincidencias


# Instancia singleton del servicio para todo el backend
monitoreo_service = MonitoreoService()
