# 3. Descarga automatizada desde ODE

## 3.1 Contexto

Los productos CRISM MTRDR se catalogan en el [Orbital Data Explorer (ODE)](https://ode.rsl.wustl.edu/mars/mapsearch). El pipeline usa la [API REST](https://oderest.rsl.wustl.edu/) para descargar archivos **SR** y/o **IF**.

## 3.2 Qué se descarga

Por cada observación MTRDR puedes elegir qué productos bajar (`--data`):

| Opción | Archivos | Uso |
|--------|----------|-----|
| `sr` (default) | `*_SR*J_MTR3.{IMG,HDR,LBL}` | Índices Viviano (pipeline maps/detect/classify) |
| `if` | `*_IF*J_MTR3.{IMG,HDR,LBL}` | Cubo I/F hiperespectral (validación espectral; mucho más pesado) |
| `both` | SR + IF | Ambos en el mismo directorio de producto |

Los archivos se organizan en `data/raw/<product_id>/`.

```mermaid
flowchart LR
  ODE[ODE REST / Map Search] --> Q[Consulta productos]
  Q --> F[Filtrar SR y/o IF<br/>IMG · HDR · LBL]
  F --> R[data/raw / product_id]
```

## 3.3 Métodos de descarga

### Por SearchResults.txt (recomendado si ya seleccionaste en Map Search)

Exporta los resultados desde ODE Map Search y pásalos directo al pipeline:

```bash
python -m crism_pipeline download --ids-file SearchResults.txt
python -m crism_pipeline download --ids-file SearchResults.txt --data both
python -m crism_pipeline download --ids-file SearchResults.txt --data if
```

El parser lee la columna **PRODUCT ID** del CSV de ODE. También acepta una lista simple (un ID por línea).

Alternativas:

```bash
# Un producto
python -m crism_pipeline download --pdsid FRT00009001_07_IF163J_MTR3

# Varios con comodín
python -m crism_pipeline download --pdsid "FRT00009*" --max-products 5
```

### Por bounding box (replica selección del mapa)

Coordenadas en **longitud 0–360° Este**, latitud planetocéntrica:

```bash
python -m crism_pipeline download \
  --bbox 70 75 -5 0 \
  --max-products 10
```

Donde `--bbox W_LON E_LON MIN_LAT MAX_LAT`.

## 3.4 Obtener Product IDs desde Map Search

1. En [Map Search](https://ode.rsl.wustl.edu/mars/mapsearch), filtra por **CRISM → MTRDR**.
2. Dibuja tu área de interés o usa filtros.
3. En resultados, usa **Export / Download Search Results** y guarda el `.txt`.
4. Pásalo a `--ids-file` (p. ej. `SearchResults.txt`).

## 3.5 Verificación

Tras la descarga, cada carpeta debe contener al menos:

```
data/raw/frt00009001_07_if163j_mtr3/
├── frt00009001_07_sr163j_mtr3.img
├── frt00009001_07_sr163j_mtr3.hdr
└── frt00009001_07_sr163j_mtr3.lbl
```

## 3.6 Alternativa: carrito ODE

Para lotes muy grandes, considera el carrito ODE con descarga FTP/HTTP. El pipeline asume descarga vía REST para integración directa con el procesamiento.

## 3.7 API REST (referencia)

Consulta de metadatos + URLs:

```
https://oderest.rsl.wustl.edu/live2?target=mars&query=product&results=opf&output=XML&IHID=MRO&IID=CRISM&PT=MTRDR&pdsid=FRT00009*&limit=1
```

Manual completo: [ODE REST V2.1.6 PDF](https://oderest.rsl.wustl.edu/ODE_REST_V2.1.6.pdf)
