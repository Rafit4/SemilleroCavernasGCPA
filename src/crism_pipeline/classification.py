"""Clasificación de unidades geológicas a partir de índices SR."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from .config import pipeline_config, viviano_config
from .io_sr import SRCube
from .maps import load_cube, save_geotiff


def _feature_stack(cube: SRCube, feature_names: list[str]) -> np.ndarray:
    missing = [f for f in feature_names if f not in cube.band_names]
    if missing:
        raise KeyError(f"Bandas no encontradas en cubo SR: {missing}")
    stack = cube.bands(feature_names)
    return stack


def _sample_pixels(
    features: np.ndarray,
    valid: np.ndarray,
    n_samples: int,
    random_state: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Muestrea píxeles válidos para clasificación."""
    rows, cols, n_bands = features.shape
    idx = np.argwhere(valid)
    if idx.size == 0:
        raise ValueError("No hay píxeles válidos en el cubo")
    rng = np.random.default_rng(random_state)
    if len(idx) > n_samples:
        sel = rng.choice(len(idx), size=n_samples, replace=False)
        idx = idx[sel]
    yx = idx
    X = features[yx[:, 0], yx[:, 1], :]
    return X, yx


def _build_pseudo_labels(
    cube: SRCube,
    unit_signatures: dict,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """
    Genera etiquetas débiles (pseudo-ground-truth) comparando perfiles
    espectrales de unidades con la media de cada índice en la escena.
    Útil cuando no hay polígonos de entrenamiento.
    """
    feature_names: list[str] = []
    for sig in unit_signatures.values():
        feature_names.extend(sig.get("high", []))
        feature_names.extend(sig.get("low", []))
    feature_names = sorted(set(feature_names))

    stack = _feature_stack(cube, feature_names)
    valid = cube.valid_mask
    rows, cols, _ = stack.shape
    scores = np.zeros((rows, cols, len(unit_signatures)), dtype=np.float32)
    unit_names = list(unit_signatures.keys())

    for ui, (uname, sig) in enumerate(unit_signatures.items()):
        score = np.zeros((rows, cols), dtype=np.float32)
        for idx_name in sig.get("high", []):
            band = cube.band(idx_name)
            p90 = np.nanpercentile(band[valid], 90) or 1.0
            score += band / max(p90, 1e-6)
        for idx_name in sig.get("low", []):
            band = cube.band(idx_name)
            p90 = np.nanpercentile(band[valid], 90) or 1.0
            score -= band / max(p90, 1e-6)
        scores[:, :, ui] = score

    labels = np.full((rows, cols), -1, dtype=np.int16)
    best = np.argmax(scores, axis=2)
    max_score = np.max(scores, axis=2)
    labels[(max_score > 0) & valid] = best[(max_score > 0) & valid]
    return labels, np.array(feature_names), unit_names


def classify_unsupervised(
    cube: SRCube,
    *,
    n_clusters: int | None = None,
    feature_names: list[str] | None = None,
) -> tuple[np.ndarray, dict]:
    cfg = pipeline_config()["classification"]
    n_clusters = n_clusters or cfg["default_n_clusters"]
    feature_names = feature_names or cfg["default_features"]
    features = _feature_stack(cube, feature_names)
    valid = cube.valid_mask

    X, yx = _sample_pixels(
        features,
        valid,
        cfg["sample_pixels_per_scene"],
        cfg["random_state"],
    )
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)

    km = KMeans(n_clusters=n_clusters, random_state=cfg["random_state"], n_init=10)
    km.fit(Xs)

    rows, cols, _ = features.shape
    label_map = np.full((rows, cols), -1, dtype=np.int16)
    all_idx = np.argwhere(valid)
    X_all = features[all_idx[:, 0], all_idx[:, 1], :]
    preds = km.predict(scaler.transform(X_all))
    label_map[all_idx[:, 0], all_idx[:, 1]] = preds

    meta = {
        "method": "kmeans",
        "n_clusters": n_clusters,
        "features": feature_names,
        "scaler": scaler,
        "model": km,
    }
    return label_map, meta


def classify_supervised(
    cube: SRCube,
    training_csv: Path,
    *,
    feature_names: list[str] | None = None,
) -> tuple[np.ndarray, dict, str]:
    """
    Clasificación supervisada con CSV de entrenamiento.

    Columnas requeridas: row, col, unit
    (coordenadas en píxeles del cubo SR y nombre de unidad)
    """
    cfg = pipeline_config()["classification"]
    feature_names = feature_names or cfg["default_features"]
    df = pd.read_csv(training_csv)
    required = {"row", "col", "unit"}
    if not required.issubset(df.columns):
        raise ValueError(f"CSV debe contener columnas: {required}")

    features = _feature_stack(cube, feature_names)
    X = features[df["row"].astype(int), df["col"].astype(int), :]
    y = df["unit"].astype(str)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=cfg["random_state"], stratify=y
    )
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)

    clf = RandomForestClassifier(n_estimators=200, random_state=cfg["random_state"])
    clf.fit(X_train_s, y_train)
    report = classification_report(y_test, clf.predict(X_test_s))

    valid = cube.valid_mask
    rows, cols, _ = features.shape
    label_map = np.full((rows, cols), -1, dtype=np.int16)
    classes = list(clf.classes_)
    class_to_id = {c: i for i, c in enumerate(classes)}

    all_idx = np.argwhere(valid)
    X_all = features[all_idx[:, 0], all_idx[:, 1], :]
    preds = clf.predict(scaler.transform(X_all))
    for i, (r, c) in enumerate(all_idx):
        label_map[r, c] = class_to_id[preds[i]]

    meta = {
        "method": "random_forest",
        "features": feature_names,
        "classes": classes,
        "scaler": scaler,
        "model": clf,
    }
    return label_map, meta, report


def classify_signature_based(
    cube: SRCube,
) -> tuple[np.ndarray, dict]:
    """Clasificación basada en firmas espectrales predefinidas (config)."""
    signatures = viviano_config()["unit_signatures"]
    labels, feature_names, unit_names = _build_pseudo_labels(cube, signatures)
    meta = {
        "method": "signature",
        "features": list(feature_names),
        "classes": unit_names,
    }
    return labels, meta


def save_classification_map(
    cube: SRCube,
    label_map: np.ndarray,
    meta: dict,
    out_dir: Path,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / f"{cube.product_id}_{meta['method']}_units.png"

    masked = np.ma.masked_where(label_map < 0, label_map)
    fig, ax = plt.subplots(figsize=(10, 8))
    im = ax.imshow(masked, cmap="tab10", interpolation="nearest")
    ax.set_title(f"Unidades — {meta['method']} — {cube.product_id}")
    ax.axis("off")
    if meta.get("classes"):
        cbar = plt.colorbar(im, ax=ax, fraction=0.03)
        cbar.set_ticks(range(len(meta["classes"])))
        cbar.set_ticklabels(meta["classes"])
    fig.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    tif_path = out_dir / f"{cube.product_id}_{meta['method']}_units.tif"
    save_geotiff(label_map.astype(np.int16), tif_path, cube)

    meta_path = out_dir / f"{cube.product_id}_{meta['method']}_meta.json"
    serializable = {k: v for k, v in meta.items() if k not in {"scaler", "model"}}
    serializable["classes"] = meta.get("classes", [])
    meta_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")

    if "model" in meta:
        import joblib

        joblib.dump(
            {"model": meta["model"], "scaler": meta.get("scaler"), "features": meta["features"]},
            out_dir / f"{cube.product_id}_{meta['method']}_model.joblib",
        )
    return png_path


def run_classification_pipeline(
    source: Path,
    out_dir: Path,
    method: str = "kmeans",
    *,
    n_clusters: int | None = None,
    training_csv: Path | None = None,
) -> tuple[np.ndarray, dict]:
    cube = load_cube(source)

    if method == "kmeans":
        labels, meta = classify_unsupervised(cube, n_clusters=n_clusters)
    elif method == "signature":
        labels, meta = classify_signature_based(cube)
    elif method == "supervised":
        if not training_csv:
            raise ValueError("method=supervised requiere --training-csv")
        labels, meta, report = classify_supervised(cube, training_csv)
        report_path = out_dir / f"{cube.product_id}_classification_report.txt"
        out_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
    else:
        raise ValueError(f"Método desconocido: {method}")

    save_classification_map(cube, labels, meta, out_dir)
    return labels, meta
