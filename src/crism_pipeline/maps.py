"""Generación de mapas minerales a partir de cubos SR."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio

from .config import viviano_config
from .io_sr import SRCube, load_cube
from .stretch import stretch_band, stretch_rgb


def _geotransform(cube: SRCube, width: int, height: int):
    from .io_sr import _build_geotransform

    mi = cube.map_info
    if not mi:
        return None, None
    try:
        gt = _build_geotransform(mi)
        if gt is None:
            return None, None
        transform = rasterio.Affine(*gt)
        crs = mi.get("crs_wkt")
        if crs:
            crs = str(crs).strip("{}")
        return transform, crs
    except (TypeError, ValueError):
        return None, None


def save_geotiff(array: np.ndarray, out_path: Path, cube: SRCube, count: int = 1):
    height, width = array.shape[:2]
    transform, crs = _geotransform(cube, width, height)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": count,
        "dtype": array.dtype,
        "compress": "lzw",
    }
    if transform and crs:
        profile["crs"] = crs
        profile["transform"] = transform
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        if count == 1:
            dst.write(array, 1)
        else:
            for i in range(count):
                dst.write(array[:, :, i], i + 1)



def render_index_map(
    cube: SRCube,
    index_name: str,
    out_dir: Path,
    *,
    save_geotiff_flag: bool = True,
) -> Path:
    """Mapa en escala de grises de un índice individual."""
    band = cube.band(index_name)
    stretched = stretch_band(band, index_name)

    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / f"{cube.product_id}_{index_name}.png"
    tif_path = out_dir / f"{cube.product_id}_{index_name}.tif"

    fig, ax = plt.subplots(figsize=(10, 8))
    im = ax.imshow(stretched, cmap="gray", interpolation="nearest")
    ax.set_title(f"{index_name} — {cube.product_id}")
    ax.axis("off")
    plt.colorbar(im, ax=ax, fraction=0.03)
    fig.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    if save_geotiff_flag:
        save_geotiff(stretched, tif_path, cube)
    return png_path


def render_browse_product(
    cube: SRCube,
    browse_code: str,
    out_dir: Path,
    *,
    save_geotiff_flag: bool = True,
) -> Path:
    """Genera mapa RGB tipo browse product (Viviano 2014 Tabla 3)."""
    cfg = viviano_config()["browse_products"]
    if browse_code not in cfg:
        raise KeyError(f"Browse '{browse_code}' no definido. Opciones: {list(cfg)}")

    spec = cfg[browse_code]
    r_name, g_name, b_name = spec["rgb"]
    rgb = stretch_rgb(
        cube.band(r_name),
        cube.band(g_name),
        cube.band(b_name),
        (r_name, g_name, b_name),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / f"{cube.product_id}_{browse_code}.png"
    tif_path = out_dir / f"{cube.product_id}_{browse_code}.tif"

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.imshow(rgb, interpolation="nearest")
    ax.set_title(f"{browse_code} — {spec['name']} — {cube.product_id}")
    ax.axis("off")
    fig.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    if save_geotiff_flag:
        save_geotiff(rgb, tif_path, cube, count=3)
    return png_path


def render_mineral_group_maps(
    cube: SRCube,
    out_dir: Path,
    groups: list[str] | None = None,
) -> list[Path]:
    """Mapas del índice principal de cada grupo mineral."""
    mineral_cfg = viviano_config()["mineral_groups"]
    targets = groups or list(mineral_cfg.keys())
    outputs: list[Path] = []

    for key in targets:
        if key not in mineral_cfg:
            continue
        primary = mineral_cfg[key]["primary"]
        outputs.append(render_index_map(cube, primary, out_dir / "indices"))
        browse = mineral_cfg[key].get("browse")
        if browse:
            outputs.append(render_browse_product(cube, browse, out_dir / "browse"))
    return outputs


def generate_all_maps(
    source: Path,
    out_dir: Path,
    *,
    browse_codes: list[str] | None = None,
    mineral_groups: list[str] | None = None,
) -> list[Path]:
    cube = load_cube(source)
    outputs: list[Path] = []

    codes = browse_codes or ["MAF", "PHY", "HYD", "CAR", "FEM"]
    for code in codes:
        outputs.append(render_browse_product(cube, code, out_dir / "browse"))

    outputs.extend(render_mineral_group_maps(cube, out_dir, mineral_groups))
    return outputs
