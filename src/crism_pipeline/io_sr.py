"""Lectura de cubos SR MTRDR (formato ENVI) y exportación a HDF5."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np
import spectral.io.envi as envi

from .config import pipeline_config


# Alias Viviano/config → nombres en cubos SR NASA/PDS
BAND_ALIASES: dict[str, str] = {
    "BD1900R2": "BD1900R2",
    "BD1900r2": "BD1900R2",
    "BD2500H2": "BD2500_2",
    "BD2500h2": "BD2500_2",
    "ISLOPE": "ISLOPE1",
    "ISLOPE1": "ISLOPE1",
    "BD2000": "BDI2000",
    "BDI2000": "BDI2000",
    "IRA": "IRR1",
    "IRR1": "IRR1",
}


@dataclass
class SRCube:
    """Cubo de parámetros resumidos refinados (SR)."""

    product_id: str
    data: np.ndarray  # (lines, samples, bands)
    band_names: list[str]
    map_info: dict[str, float | str]
    hdr_path: Path
    img_path: Path

    def __post_init__(self) -> None:
        self._band_index = {name.upper(): i for i, name in enumerate(self.band_names)}

    def _resolve_band_name(self, name: str) -> str:
        canonical = BAND_ALIASES.get(name, name)
        key = canonical.upper()
        if key not in self._band_index:
            raise KeyError(
                f"Banda '{name}' no encontrada. Disponibles: {self.band_names[:10]}..."
            )
        return self.band_names[self._band_index[key]]

    def band(self, name: str) -> np.ndarray:
        try:
            resolved = self._resolve_band_name(name)
            idx = self.band_names.index(resolved)
        except (KeyError, ValueError) as exc:
            raise KeyError(
                f"Banda '{name}' no encontrada. Disponibles: {self.band_names[:10]}..."
            ) from exc
        return self.data[:, :, idx]

    def bands(self, names: list[str]) -> np.ndarray:
        indices = [self.band_names.index(self._resolve_band_name(n)) for n in names]
        return self.data[:, :, indices]

    @property
    def valid_mask(self) -> np.ndarray:
        """Máscara de píxeles con al menos una banda válida (sin nodata/65535)."""
        from .stretch import valid_data_mask

        # Válido si alguna banda es utilizable
        return valid_data_mask(self.data).any(axis=2)


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
        # Formato ENVI multilínea: { name1, name2, ... }
        inner = names.strip("{}").replace("\n", " ")
        return [n.strip() for n in inner.split(",") if n.strip()]
    return [str(n).strip() for n in names]


def _strip_envi_braces(value: str | list) -> str:
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    return str(value).strip("{}")


def _parse_map_info(metadata: dict) -> dict[str, float | str]:
    """Parsea map info ENVI; la proyección puede contener comas internas."""
    info = metadata.get("map info")
    if not info:
        return {}

    parts = [p.strip() for p in _strip_envi_braces(info).split(",")]
    if len(parts) < 8:
        return {}

    # Campos fijos al final: datum, units, pixel sizes, map coords, ref pixel.
    # El resto (puede incluir comas) es el nombre de proyección.
    try:
        units = parts[-1]
        datum = parts[-2]
        pixel_size_y = float(parts[-3])
        pixel_size_x = float(parts[-4])
        map_y = float(parts[-5])
        map_x = float(parts[-6])
        ref_y = float(parts[-7])
        ref_x = float(parts[-8])
        projection = ", ".join(parts[:-8])
    except ValueError:
        return {}

    result: dict[str, float | str] = {
        "projection": projection,
        "ref_x": ref_x,
        "ref_y": ref_y,
        "map_x": map_x,
        "map_y": map_y,
        "pixel_size_x": pixel_size_x,
        "pixel_size_y": pixel_size_y,
        "datum": datum,
        "units": units,
    }

    crs = metadata.get("coordinate system string")
    if crs:
        result["crs_wkt"] = _strip_envi_braces(crs)

    proj_info = metadata.get("projection info")
    if proj_info:
        result["projection_info"] = _strip_envi_braces(proj_info)

    return result


def _build_geotransform(map_info: dict[str, float | str]) -> tuple[float, ...] | None:
    """Construye geotransform GDAL (6 elementos) desde map info ENVI."""
    try:
        ref_x = float(map_info["ref_x"])
        ref_y = float(map_info["ref_y"])
        map_x = float(map_info["map_x"])
        map_y = float(map_info["map_y"])
        ps_x = float(map_info["pixel_size_x"])
        ps_y = float(map_info["pixel_size_y"])
    except (KeyError, TypeError, ValueError):
        return None

    # ENVI: ref pixel 1-based; filas crecen hacia abajo → gt[5] negativo.
    return (
        map_x - ps_x * (ref_x - 1),
        ps_x,
        0.0,
        map_y + ps_y * (ref_y - 1),
        0.0,
        -abs(ps_y),
    )


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


def export_geotiff(cube: SRCube, out_path: Path) -> Path:
    """Exporta cubo SR a GeoTIFF multibanda con CRS, geotransform y nombres de banda."""
    import rasterio
    from rasterio.transform import Affine

    geotransform = _build_geotransform(cube.map_info)
    if geotransform is None:
        raise ValueError(
            f"No se pudo construir geotransform para {cube.product_id}. "
            "Revisa map info en el header ENVI."
        )

    lines, samples, bands = cube.data.shape
    crs = cube.map_info.get("crs_wkt")
    nodata = pipeline_config()["processing"]["nodata_value"]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile: dict = {
        "driver": "GTiff",
        "height": lines,
        "width": samples,
        "count": bands,
        "dtype": "float32",
        "compress": "lzw",
        "tiled": True,
        "BIGTIFF": "IF_SAFER",
        "nodata": nodata,
        "transform": Affine(*geotransform),
    }
    if crs:
        profile["crs"] = str(crs)

    with rasterio.open(out_path, "w", **profile) as dst:
        for i, name in enumerate(cube.band_names, start=1):
            dst.write(cube.data[:, :, i - 1], i)
            dst.set_band_description(i, name)
        dst.update_tags(
            product_id=cube.product_id,
            source="CRISM MTRDR SR",
            band_names=", ".join(cube.band_names),
        )
    return out_path


def load_cube(source: Path) -> SRCube:
    """Carga cubo SR desde directorio ENVI, .hdr/.img o HDF5 legado."""
    source = Path(source)
    if source.suffix.lower() in {".h5", ".hdf5"}:
        return load_hdf5(source)
    return load_sr_cube(source)


def export_hdf5(cube: SRCube, out_path: Path) -> Path:
    """Exporta cubo SR a HDF5 para procesamiento rápido."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    compression = pipeline_config()["processing"]["hdf5_compression"]
    str_dtype = h5py.string_dtype(encoding="utf-8")
    geotransform = _build_geotransform(cube.map_info)

    with h5py.File(out_path, "w") as hf:
        hf.create_dataset(
            "data",
            data=cube.data,
            compression=compression,
        )
        hf.create_dataset(
            "band_names",
            data=np.array(cube.band_names, dtype=str_dtype),
        )
        hf.create_dataset("valid_mask", data=cube.valid_mask)
        hf.attrs["product_id"] = cube.product_id
        hf.attrs["n_bands"] = len(cube.band_names)
        hf.attrs["band_names_list"] = ", ".join(cube.band_names)

        for k, v in cube.map_info.items():
            hf.attrs[f"map_{k}"] = str(v)

        if geotransform:
            hf.create_dataset("geotransform", data=np.array(geotransform, dtype=np.float64))
            hf.attrs["geotransform_gdal"] = ", ".join(f"{v:.10f}" for v in geotransform)

        crs = cube.map_info.get("crs_wkt")
        if crs:
            hf.attrs["crs_wkt"] = str(crs)
    return out_path


def _decode_band_names(raw_names) -> list[str]:
    names: list[str] = []
    for name in raw_names:
        if isinstance(name, bytes):
            names.append(name.decode("utf-8"))
        else:
            names.append(str(name))
    return names


def load_hdf5(path: Path) -> SRCube:
    with h5py.File(path, "r") as hf:
        data = hf["data"][:]
        band_names = _decode_band_names(hf["band_names"][:])
        map_info: dict[str, float | str] = {
            k.removeprefix("map_"): hf.attrs[k]
            for k in hf.attrs
            if k.startswith("map_")
        }
        if "crs_wkt" in hf.attrs and "crs_wkt" not in map_info:
            map_info["crs_wkt"] = hf.attrs["crs_wkt"]
        product_id = hf.attrs.get("product_id", path.stem)
    return SRCube(
        product_id=product_id,
        data=data,
        band_names=band_names,
        map_info=map_info,
        hdr_path=path,
        img_path=path,
    )
