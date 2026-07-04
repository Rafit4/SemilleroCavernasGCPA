"""Estiramiento de parámetros SR según Viviano-Beck et al. (2014) §5.3."""

from __future__ import annotations

import numpy as np

from .config import pipeline_config


def _percentile_limits(arr: np.ndarray, lo: float, hi: float) -> tuple[float, float]:
    valid = arr[np.isfinite(arr)]
    if valid.size == 0:
        return 0.0, 1.0
    return float(np.percentile(valid, lo)), float(np.percentile(valid, hi))


def stretch_band(
    band: np.ndarray,
    band_name: str,
    *,
    global_upper: float | None = None,
) -> np.ndarray:
    """
    Estira una banda SR a rango 0–255 (uint8) para visualización.

    Parámetros en local_percentile_params usan percentiles 0.1–99.9 de la escena.
    El resto usa límite inferior fijo en 0 y superior = max(percentil global 99, local 99.9).
    """
    cfg = pipeline_config()["stretch"]
    local_params = set(cfg["local_percentile_params"])
    out = np.zeros_like(band, dtype=np.float32)
    valid = np.isfinite(band)

    if band_name in local_params:
        vmin, vmax = _percentile_limits(
            band[valid],
            cfg["local_lower_pct"],
            cfg["local_upper_pct"],
        )
    else:
        vmin = cfg["fixed_lower"]
        local_hi = _percentile_limits(band[valid], 0.0, cfg["local_upper_pct"])[1]
        g_hi = global_upper if global_upper is not None else local_hi
        vmax = max(g_hi, local_hi)

    if vmax <= vmin:
        vmax = vmin + 1e-6

    scaled = (band - vmin) / (vmax - vmin)
    scaled = np.clip(scaled, 0.0, 1.0)
    out[valid] = scaled[valid] * 255.0
    return out.astype(np.uint8)


def stretch_rgb(
    r: np.ndarray,
    g: np.ndarray,
    b: np.ndarray,
    names: tuple[str, str, str],
) -> np.ndarray:
    """Genera imagen RGB uint8 (H, W, 3)."""
    channels = [
        stretch_band(r, names[0]),
        stretch_band(g, names[1]),
        stretch_band(b, names[2]),
    ]
    return np.stack(channels, axis=-1)
