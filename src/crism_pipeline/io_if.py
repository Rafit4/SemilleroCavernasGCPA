"""Lectura de cubos CRISM MTRDR IF (I/F) y extracción de firmas espectrales."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import spectral.io.envi as envi

from .io_sr import _parse_map_info, _strip_envi_braces


@dataclass
class IFCube:
    """Cubo hiperespectral I/F (reflectancia aparente)."""

    product_id: str
    data: np.ndarray  # (lines, samples, bands) float32
    wavelengths: np.ndarray  # nm, shape (bands,)
    wavelength_units: str
    map_info: dict[str, float | str]
    hdr_path: Path
    img_path: Path
    ignore_value: float
    fwhm: np.ndarray | None = None
    default_bands: tuple[int, int, int] | None = None  # 1-based ENVI → stored 0-based

    @property
    def lines(self) -> int:
        return int(self.data.shape[0])

    @property
    def samples(self) -> int:
        return int(self.data.shape[1])

    @property
    def nbands(self) -> int:
        return int(self.data.shape[2])

    @property
    def valid_mask(self) -> np.ndarray:
        """Píxeles con al menos una banda utilizable."""
        finite = np.isfinite(self.data)
        good = (self.data != self.ignore_value) & (self.data < 60000)
        return (finite & good).any(axis=2)

    def spectrum_at(self, line: int, sample: int) -> np.ndarray:
        """Firma I/F en (line, sample). Índices 0-based."""
        if not (0 <= line < self.lines and 0 <= sample < self.samples):
            raise IndexError(
                f"Coordenada fuera de rango: line={line}, sample={sample} "
                f"(válido: 0..{self.lines - 1}, 0..{self.samples - 1})"
            )
        spec = self.data[line, sample, :].astype(np.float64, copy=True)
        bad = ~np.isfinite(spec) | (spec == self.ignore_value) | (spec >= 60000)
        spec[bad] = np.nan
        return spec

    def mean_spectrum(self, *, max_pixels: int = 80_000, seed: int = 42) -> np.ndarray:
        """Media espectral de píxeles válidos (muestreo si hay demasiados)."""
        mask = self.valid_mask
        idx = np.argwhere(mask)
        if idx.size == 0:
            return np.full(self.nbands, np.nan, dtype=np.float64)
        rng = np.random.default_rng(seed)
        if len(idx) > max_pixels:
            sel = rng.choice(len(idx), size=max_pixels, replace=False)
            idx = idx[sel]
        # (N, bands)
        stack = self.data[idx[:, 0], idx[:, 1], :].astype(np.float64, copy=False)
        bad = ~np.isfinite(stack) | (stack == self.ignore_value) | (stack >= 60000)
        stack = np.where(bad, np.nan, stack)
        return np.nanmean(stack, axis=0)

    def nearest_band(self, wavelength_nm: float) -> int:
        return int(np.argmin(np.abs(self.wavelengths - wavelength_nm)))

    def quicklook_rgb(self) -> np.ndarray:
        """RGB uint8 para vista previa (default bands del HDR o 2.5/1.5/1.0 μm)."""
        if self.default_bands is not None:
            ri, gi, bi = self.default_bands
        else:
            ri = self.nearest_band(2500)
            gi = self.nearest_band(1500)
            bi = self.nearest_band(1000)
        rgb = np.stack(
            [
                self.data[:, :, ri],
                self.data[:, :, gi],
                self.data[:, :, bi],
            ],
            axis=-1,
        ).astype(np.float64)
        bad = ~np.isfinite(rgb) | (rgb == self.ignore_value) | (rgb >= 60000)
        rgb = np.where(bad, np.nan, rgb)
        out = np.zeros(rgb.shape, dtype=np.uint8)
        for c in range(3):
            ch = rgb[:, :, c]
            valid = np.isfinite(ch)
            if not np.any(valid):
                continue
            lo, hi = np.nanpercentile(ch[valid], [2, 98])
            if hi <= lo:
                hi = lo + 1e-6
            scaled = np.clip((ch - lo) / (hi - lo), 0, 1)
            tmp = np.zeros(ch.shape, dtype=np.float64)
            tmp[valid] = scaled[valid] * 255.0
            out[:, :, c] = tmp.astype(np.uint8)
        return out


def find_if_pair(directory: Path) -> tuple[Path, Path]:
    """Localiza el par .hdr/.img IF en un directorio de producto."""
    directory = Path(directory)
    hdr_files = sorted(directory.glob("*_IF*J_MTR3.HDR"))
    hdr_files += sorted(directory.glob("*_if*j_mtr3.hdr"))
    if not hdr_files:
        raise FileNotFoundError(f"No se encontró cubo IF en {directory}")
    hdr = hdr_files[0]
    img = hdr.with_suffix(".img")
    if not img.exists():
        img = hdr.with_suffix(".IMG")
    if not img.exists():
        raise FileNotFoundError(f"IMG asociado no encontrado para {hdr}")
    return hdr, img


def list_if_products(raw_dir: Path | None = None) -> list[Path]:
    """Directorios bajo data/raw que contienen un cubo IF."""
    from .config import resolve_path

    root = Path(raw_dir) if raw_dir else resolve_path("raw")
    if not root.is_dir():
        return []
    found: list[Path] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        try:
            find_if_pair(d)
            found.append(d)
        except FileNotFoundError:
            continue
    return found


def _parse_float_list(metadata: dict, key: str) -> np.ndarray | None:
    raw = metadata.get(key)
    if raw is None:
        return None
    text = _strip_envi_braces(raw).replace("\n", " ")
    vals = [float(x.strip()) for x in text.split(",") if x.strip()]
    return np.asarray(vals, dtype=np.float64)


def _parse_default_bands(metadata: dict) -> tuple[int, int, int] | None:
    raw = metadata.get("default bands")
    if raw is None:
        return None
    text = _strip_envi_braces(raw)
    parts = [int(float(p.strip())) for p in text.split(",") if p.strip()]
    if len(parts) < 3:
        return None
    # ENVI default bands son 1-based
    return parts[0] - 1, parts[1] - 1, parts[2] - 1


def _product_id_from_hdr(hdr: Path) -> str:
    stem = hdr.stem
    match = re.search(r"(FRT|HRL|HRS)[0-9A-F]+_\d+_IF\d+J_MTR3", stem, re.I)
    return match.group(0).upper() if match else stem.upper()


def load_if_cube(path: Path) -> IFCube:
    """Carga un cubo IF desde directorio de producto o ruta .hdr/.img."""
    path = Path(path)
    if path.is_dir():
        hdr, img = find_if_pair(path)
    elif path.suffix.lower() in {".hdr", ".img"}:
        hdr = path.with_suffix(".hdr") if path.suffix.lower() == ".img" else path
        if not hdr.exists():
            hdr = path.with_suffix(".HDR")
        img = hdr.with_suffix(".img")
        if not img.exists():
            img = hdr.with_suffix(".IMG")
        if not img.exists():
            raise FileNotFoundError(f"IMG no encontrado para {hdr}")
    else:
        raise FileNotFoundError(f"Ruta IF no válida: {path}")

    img_obj = envi.open(str(hdr), str(img))
    cube = np.asarray(img_obj.load(), dtype=np.float32)
    meta = dict(img_obj.metadata)
    wavelengths = _parse_float_list(meta, "wavelength")
    if wavelengths is None or wavelengths.size == 0:
        raise ValueError(f"El header IF no contiene 'wavelength': {hdr}")
    if wavelengths.size != cube.shape[2]:
        raise ValueError(
            f"wavelength ({wavelengths.size}) != bandas ({cube.shape[2]}) en {hdr}"
        )

    ignore = meta.get("data ignore value", 65535.0)
    try:
        ignore_f = float(_strip_envi_braces(ignore))
    except (TypeError, ValueError):
        ignore_f = 65535.0

    units = str(meta.get("wavelength units", "Nanometers"))
    return IFCube(
        product_id=_product_id_from_hdr(hdr),
        data=cube,
        wavelengths=wavelengths,
        wavelength_units=units,
        map_info=_parse_map_info(meta),
        hdr_path=hdr,
        img_path=img,
        ignore_value=ignore_f,
        fwhm=_parse_float_list(meta, "fwhm"),
        default_bands=_parse_default_bands(meta),
    )


def export_spectra_csv(
    out_path: Path,
    wavelengths: np.ndarray,
    *,
    pixel: np.ndarray | None = None,
    mean: np.ndarray | None = None,
    line: int | None = None,
    sample: int | None = None,
    product_id: str = "",
) -> Path:
    """Exporta firmas a CSV (una fila por longitud de onda)."""
    if pixel is None and mean is None:
        raise ValueError("Indica al menos espectro de píxel o media.")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["wavelength_nm"]
    if pixel is not None:
        fieldnames.append("i_f_pixel")
    if mean is not None:
        fieldnames.append("i_f_mean")
    fieldnames.extend(["line", "sample", "product_id"])

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for i, wl in enumerate(wavelengths):
            row: dict[str, object] = {
                "wavelength_nm": f"{float(wl):.6f}",
                "line": "" if line is None else line,
                "sample": "" if sample is None else sample,
                "product_id": product_id,
            }
            if pixel is not None:
                val = pixel[i]
                row["i_f_pixel"] = "" if not np.isfinite(val) else f"{float(val):.8f}"
            if mean is not None:
                val = mean[i]
                row["i_f_mean"] = "" if not np.isfinite(val) else f"{float(val):.8f}"
            writer.writerow(row)
    return out_path
