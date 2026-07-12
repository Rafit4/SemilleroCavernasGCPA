"""Descarga de productos CRISM MTRDR (SR / IF) desde la API REST de ODE."""

from __future__ import annotations

import csv
import io
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Literal

from tqdm import tqdm

from .config import pipeline_config

# Archivos MTRDR pueden ser grandes (IF hiperespectral >> SR); ODE a veces corta la conexión.
_DOWNLOAD_TIMEOUT = 300
_DOWNLOAD_RETRIES = 8
_RETRY_SLEEP_S = 3.0
_CHUNK_SIZE = 1 << 20  # 1 MiB

# (nombre_archivo, fracción 0–1, mensaje)
ProgressCallback = Callable[[str, float, str], None]

DataKind = Literal["sr", "if"]
DataSelection = Literal["sr", "if", "both"]

_PRODUCT_ID_RE = re.compile(
    r"^(?:frt|hrl|hrs|ato|hsp|msw|msp|msv|vvv)\d{8}_[0-9a-z]+_[a-z0-9]+_mtr3$",
    re.IGNORECASE,
)


def parse_data_selection(selection: str | Iterable[str]) -> frozenset[DataKind]:
    """Normaliza ``sr`` / ``if`` / ``both`` (o iterable) a un conjunto de tipos."""
    if isinstance(selection, str):
        key = selection.strip().lower()
        if key == "both":
            return frozenset({"sr", "if"})
        if key in {"sr", "if"}:
            return frozenset({key})  # type: ignore[arg-type]
        raise ValueError(f"Tipo de dato inválido: {selection!r} (usa sr, if o both)")
    kinds: set[str] = set()
    for item in selection:
        kinds |= parse_data_selection(str(item))
    if not kinds:
        raise ValueError("Debe indicar al menos un tipo: sr y/o if")
    bad = kinds - {"sr", "if"}
    if bad:
        raise ValueError(f"Tipos de dato inválidos: {sorted(bad)}")
    return frozenset(kinds)  # type: ignore[arg-type]


def _is_wanted_file(filename: str, kinds: frozenset[DataKind]) -> bool:
    """True si el archivo es IMG/HDR/LBL SR y/o IF según ``kinds``."""
    name = filename.lower()
    if not name.endswith((".img", ".hdr", ".lbl")):
        return False
    if "mtr3" not in name:
        return False
    is_sr = "_sr" in name
    is_if = "_if" in name and not is_sr
    if is_sr and "sr" in kinds:
        return True
    if is_if and "if" in kinds:
        return True
    return False


# Compatibilidad
def _is_sr_file(filename: str) -> bool:
    return _is_wanted_file(filename, frozenset({"sr"}))


def parse_ids_file(path: Path) -> list[str]:
    """Extrae Product IDs desde un archivo ODE SearchResults o una lista simple.

    Formatos aceptados:
    - Export ODE ``SearchResults.txt`` (CSV con columna PRODUCT ID).
    - Texto plano con un Product ID por línea (líneas ``#`` = comentario).
    """
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines:
        return []

    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.lstrip("#").strip()
        if "PRODUCT ID" in stripped.upper() and (
            "," in stripped or "\t" in stripped
        ):
            header_idx = i
            break

    if header_idx is not None:
        header_line = lines[header_idx].lstrip("#").strip()
        data_text = "\n".join([header_line, *lines[header_idx + 1 :]])
        reader = csv.DictReader(io.StringIO(data_text), skipinitialspace=True)
        if not reader.fieldnames:
            raise ValueError(f"No se pudo leer el encabezado de {path}")

        col = next(
            (name for name in reader.fieldnames if name.strip().upper() == "PRODUCT ID"),
            None,
        )
        if col is None:
            raise ValueError(
                f"No se encontró la columna PRODUCT ID en {path}. "
                f"Columnas: {reader.fieldnames}"
            )

        ids: list[str] = []
        seen: set[str] = set()
        for row in reader:
            raw = (row.get(col) or "").strip()
            if not raw or raw.startswith("#"):
                continue
            pid = raw.split()[0] if raw else ""
            if not pid or pid in seen:
                continue
            seen.add(pid)
            ids.append(pid)
        return ids

    # Lista simple: un ID por línea
    ids = []
    seen = set()
    for line in lines:
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        # Si parece CSV de ODE sin encabezado reconocido, toma el 5.º campo
        if "," in raw and not _PRODUCT_ID_RE.match(raw.split(",")[0].strip()):
            fields = [f.strip() for f in next(csv.reader([raw]))]
            candidate = fields[4] if len(fields) >= 5 else raw
        else:
            candidate = raw.split()[0]
        if candidate in seen:
            continue
        seen.add(candidate)
        ids.append(candidate)
    return ids


def _build_query_url(**params: str | int) -> str:
    cfg = pipeline_config()["ode"]
    base = cfg["base_url"]
    query = {
        "target": cfg["target"],
        "query": "product",
        "results": "opf",
        "output": "XML",
        "IHID": cfg["ihid"],
        "IID": cfg["iid"],
        "PT": cfg["pt"],
    }
    query.update({k: str(v) for k, v in params.items() if v is not None})
    return f"{base}?{urllib.parse.urlencode(query)}"


def query_products(
    *,
    pdsid: str | None = None,
    westernlon: float | None = None,
    easternlon: float | None = None,
    minlat: float | None = None,
    maxlat: float | None = None,
    limit: int = 100,
    offset: int = 0,
) -> ET.Element:
    params: dict[str, str | int] = {"limit": limit, "offset": offset}
    if pdsid:
        params["pdsid"] = pdsid
    if all(v is not None for v in (westernlon, easternlon, minlat, maxlat)):
        params.update(
            {
                "westernlon": westernlon,
                "easternlon": easternlon,
                "minlat": minlat,
                "maxlat": maxlat,
                "loc": "f",
            }
        )
    url = _build_query_url(**params)
    with urllib.request.urlopen(url, timeout=120) as resp:
        return ET.fromstring(resp.read())


def _remote_size(url: str) -> int | None:
    """Obtiene Content-Length con HEAD (o None si no está disponible)."""
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=60) as resp:
            length = resp.headers.get("Content-Length")
            return int(length) if length else None
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TypeError):
        return None


def _download_file(
    url: str,
    dest: Path,
    *,
    retries: int = _DOWNLOAD_RETRIES,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Descarga con reintentos, reanudación (Range) y verificación de tamaño."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    expected = _remote_size(url)
    last_err: Exception | None = None

    def _report(got: int, total: int | None, msg: str = "") -> None:
        if on_progress is None:
            return
        frac = (got / total) if total and total > 0 else 0.0
        on_progress(dest.name, min(frac, 1.0), msg or dest.name)

    for attempt in range(1, retries + 1):
        try:
            existing = dest.stat().st_size if dest.exists() else 0
            if expected is not None and existing == expected and existing > 0:
                _report(existing, expected, f"Ya completo: {dest.name}")
                return dest
            if expected is not None and existing > expected:
                dest.unlink(missing_ok=True)
                existing = 0

            headers: dict[str, str] = {}
            mode = "wb"
            if existing > 0 and (expected is None or existing < expected):
                headers["Range"] = f"bytes={existing}-"
                mode = "ab"

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp:
                # Si pedimos Range y el servidor no lo soporta, reinicia.
                if existing > 0 and resp.status == 200:
                    dest.unlink(missing_ok=True)
                    existing = 0
                    mode = "wb"
                total = expected
                if total is None:
                    cl = resp.headers.get("Content-Length")
                    if cl:
                        total = existing + int(cl) if mode == "ab" else int(cl)

                label = dest.name
                got = existing
                _report(got, total, f"Descargando {label} (intento {attempt})")
                with open(dest, mode) as fh, tqdm(
                    total=total,
                    initial=existing,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    desc=label[:40],
                    leave=False,
                ) as bar:
                    while True:
                        chunk = resp.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        fh.write(chunk)
                        got += len(chunk)
                        bar.update(len(chunk))
                        _report(got, total, f"Descargando {label}")

            final_size = dest.stat().st_size
            if expected is not None and final_size != expected:
                raise urllib.error.ContentTooShortError(
                    f"retrieval incomplete: got only {final_size} out of {expected} bytes",
                    None,
                )
            if final_size == 0:
                raise OSError(f"Archivo vacío tras descarga: {dest}")
            _report(final_size, final_size if expected is None else expected, f"Listo: {dest.name}")
            return dest

        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            urllib.error.ContentTooShortError,
            TimeoutError,
            OSError,
            ConnectionError,
        ) as exc:
            last_err = exc
            time.sleep(_RETRY_SLEEP_S * attempt)

    assert last_err is not None
    raise last_err


def download_scene(
    *,
    pdsid: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    out_dir: Path,
    limit: int = 100,
    max_products: int | None = None,
    on_progress: ProgressCallback | None = None,
    data: DataSelection | Iterable[str] = "sr",
) -> list[Path]:
    """Descarga archivos SR y/o IF (IMG/HDR/LBL) para productos MTRDR."""
    kinds = parse_data_selection(data)
    out_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    offset = 0
    products_done = 0

    while True:
        kwargs: dict = {"limit": limit, "offset": offset}
        if pdsid:
            kwargs["pdsid"] = pdsid
        elif bbox:
            kwargs.update(
                {
                    "westernlon": bbox[0],
                    "easternlon": bbox[1],
                    "minlat": bbox[2],
                    "maxlat": bbox[3],
                }
            )
        else:
            raise ValueError("Debe indicar pdsid o bbox")

        root = query_products(**kwargs)
        products = root.findall(".//Product")
        if not products:
            break

        for product in products:
            pid = product.findtext("pdsid", "unknown")
            product_dir = out_dir / pid
            product_dir.mkdir(parents=True, exist_ok=True)

            for pf in product.findall(".//Product_file"):
                url = pf.findtext("URL")
                fname = pf.findtext("FileName", "")
                if not url or not _is_wanted_file(fname, kinds):
                    continue
                dest = product_dir / fname
                _download_file(url, dest, on_progress=on_progress)
                downloaded.append(dest)

            products_done += 1
            if max_products and products_done >= max_products:
                return downloaded

        if len(products) < limit:
            break
        offset += limit

    return downloaded


def download_batch(
    product_ids: list[str],
    out_dir: Path,
    *,
    on_progress: ProgressCallback | None = None,
    data: DataSelection | Iterable[str] = "sr",
) -> list[Path]:
    """Descarga SR y/o IF para una lista explícita de Product IDs."""
    kinds = parse_data_selection(data)
    label = "+".join(sorted(kinds)).upper()
    all_files: list[Path] = []
    n = len(product_ids)
    for i, pid in enumerate(tqdm(product_ids, desc=f"Descargando {label}"), start=1):
        if on_progress:
            on_progress(pid, (i - 1) / max(n, 1), f"Escena {i}/{n}: {pid} ({label})")

        def _file_progress(name: str, frac: float, msg: str, _i=i, _n=n, _pid=pid) -> None:
            if on_progress is None:
                return
            # Progreso global: escenas completadas + fracción del archivo actual
            overall = ((_i - 1) + frac) / max(_n, 1)
            on_progress(name, overall, f"[{_i}/{_n}] {_pid} · {msg}")

        files = download_scene(
            pdsid=pid,
            out_dir=out_dir,
            limit=1,
            max_products=1,
            on_progress=_file_progress if on_progress else None,
            data=kinds,
        )
        all_files.extend(files)
        if on_progress:
            on_progress(pid, i / max(n, 1), f"Completada {i}/{n}: {pid}")
    return all_files