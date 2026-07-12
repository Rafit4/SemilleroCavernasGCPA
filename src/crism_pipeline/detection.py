"""Detección de minerales mediante umbrales en índices SR (Viviano 2014)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from .config import viviano_config
from .io_sr import SRCube, load_cube
from .maps import save_geotiff


@dataclass
class DetectionResult:
    mineral: str
    label: str
    mask: np.ndarray
    coverage_pct: float
    thresholds: dict[str, float]


def _threshold_value(
    band: np.ndarray,
    valid: np.ndarray,
    mode: str,
    value: float,
) -> float:
    from .stretch import valid_data_mask

    data = band[valid & valid_data_mask(band)]
    if data.size == 0:
        return 0.0
    if mode == "percentile":
        return float(np.percentile(data, value))
    return float(value)


def detect_mineral(cube: SRCube, mineral_key: str) -> DetectionResult:
    """Aplica reglas AND definidas en config/viviano2014.yaml."""
    rules = viviano_config()["mineral_detection"]
    groups = viviano_config()["mineral_groups"]
    if mineral_key not in rules:
        raise KeyError(f"Mineral '{mineral_key}' sin reglas. Opciones: {list(rules)}")

    valid = cube.valid_mask
    mask = np.ones(valid.shape, dtype=bool)
    thresholds: dict[str, float] = {}

    for cond in rules[mineral_key]["conditions"]:
        index = cond["index"]
        band = cube.band(index)
        thr = _threshold_value(
            band,
            valid,
            cond.get("threshold_mode", "percentile"),
            cond["threshold"],
        )
        thresholds[index] = thr
        op = cond.get("operator", "gt")
        if op == "gt":
            mask &= (band > thr) & valid
        elif op == "lt":
            mask &= (band < thr) & valid
        elif op == "gte":
            mask &= (band >= thr) & valid
        else:
            mask &= (band <= thr) & valid

    coverage = 100.0 * mask.sum() / max(valid.sum(), 1)
    label = groups.get(mineral_key, {}).get("label", mineral_key)
    return DetectionResult(
        mineral=mineral_key,
        label=label,
        mask=mask,
        coverage_pct=float(coverage),
        thresholds=thresholds,
    )


def detect_all(
    cube: SRCube,
    minerals: list[str] | None = None,
) -> dict[str, DetectionResult]:
    keys = minerals or list(viviano_config()["mineral_detection"].keys())
    return {k: detect_mineral(cube, k) for k in keys}


def save_detection_map(
    cube: SRCube,
    result: DetectionResult,
    out_dir: Path,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    mask_u8 = result.mask.astype(np.uint8) * 255
    png_path = out_dir / f"{cube.product_id}_{result.mineral}_detection.png"

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    axes[0].imshow(mask_u8, cmap="gray", interpolation="nearest")
    axes[0].set_title(f"Detección: {result.label}")
    axes[0].axis("off")

    overlay = np.zeros((*result.mask.shape, 3), dtype=np.uint8)
    overlay[result.mask] = [255, 0, 0]
    axes[1].imshow(overlay, interpolation="nearest")
    axes[1].set_title(f"Cobertura: {result.coverage_pct:.2f}%")
    axes[1].axis("off")
    fig.suptitle(cube.product_id)
    fig.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    tif_path = out_dir / f"{cube.product_id}_{result.mineral}_detection.tif"
    save_geotiff(mask_u8, tif_path, cube)
    return png_path


def run_detection_pipeline(
    source: Path,
    out_dir: Path,
    minerals: list[str] | None = None,
) -> dict[str, DetectionResult]:
    cube = load_cube(source)
    results = detect_all(cube, minerals)
    for res in results.values():
        save_detection_map(cube, res, out_dir)
    return results
