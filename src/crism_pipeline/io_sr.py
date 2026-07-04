"""Lectura de cubos SR MTRDR (formato ENVI) y exportación a HDF5."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np
import spectral.io.envi as envi

from .config import pipeline_config


@dataclass
class SRCube:
    """Cubo de parámetros resumidos refinados (SR)."""

    product_id: str
    data: np.ndarray  # (lines, samples, bands)
    band_names: list[str]
    map_info: dict[str, float | str]
    hdr_path: Path
    img_path: Path

    def band(self, name: str) -> np.ndarray:
        try:
            idx = self.band_names.index(name)
        except ValueError as exc:
            raise KeyError(
                f"Banda '{name}' no encontrada. Disponibles: {self.band_names[:10]}..."
            ) from exc
        return self.data[:, :, idx]

    def bands(self, names: list[str]) -> np.ndarray:
        indices = [self.band_names.index(n) for n in names]
        return self.data[:, :, indices]

    @property
    def valid_mask(self) -> np.ndarray:
        """Máscara de píxeles con al menos una banda válida."""
        nodata = pipeline_config()["processing"]["nodata_value"]
        stacked = self.data
        finite = np.isfinite(stacked)
        not_nodata = stacked != nodata
        return finite.any(axis=2) & not_nodata.any(axis=2)


def find_sr_pair(directory: Path) -> tuple[Path, Path]:
    """Localiza el par .hdr/.img SR en un directorio de producto."""
    hdr_files = sorted(directory.glob("*_SR*J_MTR3.HDR"))
    hdr_files += sorted(directory.glob("*_sr*J_mtr3.hdr"))
    if not hdr_files:
        raise FileNotFoundError(f"No se encontró cubo SR en {directory}")
    hdr = hdr_files[0]
    img = hdr.with_suffix(".img")
    if not img.exists():
        img = hdr.with_suffix(".IMG")
    if not img.exists():
        raise FileNotFoundError(f"IMG asociado no encontrado para {hdr}")
    return hdr, img


def _parse_band_names(metadata: dict) -> list[str]:
    names = metadata.get("band names")
    if names is None:
        raise ValueError("El header ENVI no contiene 'band names'")
    if isinstance(names, str):
        # Formato ENVI: {name1, name2, ...}
        inner = names.strip("{}")
        return [n.strip() for n in inner.split(",")]
    return list(names)


def _parse_map_info(metadata: dict) -> dict[str, float | str]:
    info = metadata.get("map info")
    if not info:
        return {}
    if isinstance(info, str):
        parts = info.strip("{}").split(",")
        parts = [p.strip() for p in parts]
    else:
        parts = list(info)
    keys = [
        "projection",
        "ref_x",
        "ref_y",
        "pixel_easting",
        "pixel_northing",
        "lon",
        "lat",
        "x_pixel_size",
        "y_pixel_size",
    ]
    return {k: parts[i] if i < len(parts) else "" for i, k in enumerate(keys)}


def load_sr_cube(path: Path) -> SRCube:
    """Carga un cubo SR desde directorio o archivo .hdr."""
    if path.is_dir():
        hdr_path, img_path = find_sr_pair(path)
    else:
        hdr_path = path
        img_path = path.with_suffix(".img")
        if not img_path.exists():
            img_path = path.with_suffix(".IMG")

    img = envi.open(str(hdr_path), str(img_path))
    metadata = img.metadata
    band_names = _parse_band_names(metadata)
    data = np.asarray(img.load(), dtype=np.float32)
    product_id = _product_id_from_path(hdr_path)

    return SRCube(
        product_id=product_id,
        data=data,
        band_names=band_names,
        map_info=_parse_map_info(metadata),
        hdr_path=hdr_path,
        img_path=img_path,
    )


def _product_id_from_path(hdr_path: Path) -> str:
    stem = hdr_path.stem.upper()
    match = re.search(r"(FRT|HRL|HRS)[0-9A-F]+_\d+_SR\d+J_MTR3", stem)
    return match.group(0) if match else hdr_path.stem


def export_hdf5(cube: SRCube, out_path: Path) -> Path:
    """Exporta cubo SR a HDF5 para procesamiento rápido."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    compression = pipeline_config()["processing"]["hdf5_compression"]
    with h5py.File(out_path, "w") as hf:
        hf.create_dataset(
            "data",
            data=cube.data,
            compression=compression,
        )
        hf.create_dataset(
            "band_names",
            data=np.array(cube.band_names, dtype="S32"),
        )
        hf.create_dataset("valid_mask", data=cube.valid_mask)
        hf.attrs["product_id"] = cube.product_id
        for k, v in cube.map_info.items():
            hf.attrs[f"map_{k}"] = str(v)
    return out_path


def load_hdf5(path: Path) -> SRCube:
    with h5py.File(path, "r") as hf:
        data = hf["data"][:]
        band_names = [b.decode() if isinstance(b, bytes) else str(b) for b in hf["band_names"][:]]
        map_info = {
            k.replace("map_", ""): hf.attrs[k]
            for k in hf.attrs
            if k.startswith("map_")
        }
        product_id = hf.attrs.get("product_id", path.stem)
    return SRCube(
        product_id=product_id,
        data=data,
        band_names=band_names,
        map_info=map_info,
        hdr_path=path,
        img_path=path,
    )
