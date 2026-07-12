"""Estiramiento de parámetros SR según Viviano-Beck et al. (2014) §5.3."""

from __future__ import annotations

import numpy as np

from .config import pipeline_config


def valid_data_mask(band: np.ndarray) -> np.ndarray:
    """Máscara de píxeles utilizables (finite y no relleno CRISM)."""
    cfg = pipeline_config()["processing"]
    ignore = {float(cfg["nodata_value"])}
    ignore.update(float(v) for v in cfg.get("ignore_values", []))
    mask = np.isfinite(band)
    for bad in ignore:
        mask &= band != bad
    # También descarta enteros 65535 por si vienen como int/float exacto
    mask &= band < 60000
    return mask


def _percentile_limits(arr: np.ndarray, lo: float, hi: float) -> tuple[float, float]:
    if arr.size == 0:
        return 0.0, 1.0
    return float(np.percentile(arr, lo)), float(np.percentile(arr, hi))


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
    out = np.zeros(band.shape, dtype=np.float32)
    valid = valid_data_mask(band)
    if not np.any(valid):
        return out.astype(np.uint8)

    sample = band[valid]

    if band_name in local_params:
        vmin, vmax = _percentile_limits(
            sample,
            cfg["local_lower_pct"],
            cfg["local_upper_pct"],
        )
    else:
        vmin = float(cfg["fixed_lower"])
        local_hi = _percentile_limits(sample, 0.0, cfg["local_upper_pct"])[1]
        g_hi = global_upper if global_upper is not None else local_hi
        # Si el límite fijo 0 queda por encima del máximo real, usa percentiles locales
        if vmin >= local_hi:
            vmin, vmax = _percentile_limits(
                sample, cfg["local_lower_pct"], cfg["local_upper_pct"]
            )
        else:
            vmax = max(float(g_hi), float(local_hi))

    if vmax <= vmin:
        vmax = vmin + 1e-6

    scaled = (band.astype(np.float64) - vmin) / (vmax - vmin)
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
