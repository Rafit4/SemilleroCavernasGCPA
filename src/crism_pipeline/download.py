"""Descarga de productos CRISM MTRDR SR desde la API REST de ODE."""

from __future__ import annotations

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from tqdm import tqdm

from .config import pipeline_config


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


def _is_sr_file(filename: str) -> bool:
    name = filename.lower()
    return "_sr" in name and name.endswith((".img", ".hdr", ".lbl"))


def download_scene(
    *,
    pdsid: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    out_dir: Path,
    limit: int = 100,
    max_products: int | None = None,
) -> list[Path]:
    """Descarga archivos SR (y metadatos) para uno o varios productos MTRDR."""
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
                if not url or not _is_sr_file(fname):
                    continue
                dest = product_dir / fname
                if dest.exists():
                    downloaded.append(dest)
                    continue
                urllib.request.urlretrieve(url, dest)
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
) -> list[Path]:
    """Descarga SR para una lista explícita de Product IDs."""
    all_files: list[Path] = []
    for pid in tqdm(product_ids, desc="Descargando escenas"):
        files = download_scene(pdsid=pid, out_dir=out_dir, limit=1, max_products=1)
        all_files.extend(files)
    return all_files
