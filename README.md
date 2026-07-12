# Pipeline CRISM MTRDR SR

Pipeline en Python para descargar, procesar y analizar productos **CRISM MTRDR SR** (Refined Spectral Summary Parameters) usando los **60 índices espectrales de Viviano-Beck et al. (2014)**.

Desarrollado en el contexto del **GCPA** (Grupo de investigación en Ciencias Planetarias y Astrobiología).

## Objetivos del pipeline

| Módulo | Función |
|--------|---------|
| `download` | Descarga cubos SR desde [ODE REST API](https://oderest.rsl.wustl.edu/) |
| `maps` | Mapas minerales (índices individuales + browse products RGB) |
| `detect` | Detección binaria de minerales por umbrales adaptativos |
| `classify` | Clasificación de unidades geológicas (K-means, firmas, supervisado) |
| `run` | Ejecuta maps + detect + classify sobre el cubo ENVI descargado |
| `export` | *(Opcional)* Copia GeoTIFF para QGIS |
| GUI | Interfaz CustomTkinter (`crism-pipeline-gui`) — no altera el CLI |

## Instalación rápida

```bash
cd Semillero
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e .
```

## Interfaz gráfica

Misma lógica que el CLI, con branding GCPA, barra de progreso (%) por archivo/escena y acceso a la documentación.

```powershell
.venv\Scripts\activate
$env:PYTHONPATH='src'
python -m crism_pipeline.gui
# o, tras pip install -e .:
crism-pipeline-gui
```

Manual: [docs/08_manual_gui.md](docs/08_manual_gui.md)

## Uso básico (CLI)

```bash
# 1. Descargar cubos SR (SearchResults.txt exportado desde ODE Map Search)
python -m crism_pipeline download --ids-file SearchResults.txt

# 2. Mapas minerales (browse MAF, PHY, HYD, CAR, FEM) — directo desde ENVI
python -m crism_pipeline maps --input data/raw/frt000084c9_07_if166j_mtr3

# 3. Detección de olivina y carbonatos
python -m crism_pipeline detect --input data/raw/frt000084c9_07_if166j_mtr3 --mineral olivine mg_carbonate

# 4. Clasificación de unidades (K-means)
python -m crism_pipeline classify --input data/raw/frt000084c9_07_if166j_mtr3 --method kmeans --n-clusters 5

# Pipeline completo (sin conversión intermedia)
python -m crism_pipeline run --input data/raw/frt000084c9_07_if166j_mtr3
```

**En QGIS:** abre el archivo `.IMG` (no el `.hdr`) de `data/raw/` — ya incluye CRS y 60 bandas con nombre.

## Estructura del proyecto

```
Semillero/
├── assets/                    # Logo GCPA (referencia)
├── config/
│   ├── pipeline.yaml          # Rutas, ODE, parámetros de stretch/clasificación
│   └── viviano2014.yaml       # Browse products, minerales, reglas de detección
├── data/
│   ├── raw/                   # Descargas ODE (.img, .hdr, .lbl) — fuente principal
│   ├── processed/             # Exportaciones opcionales (GeoTIFF)
│   ├── maps/                  # PNG, GeoTIFF, detecciones, clasificaciones
│   └── models/                # Modelos entrenados (.joblib)
├── docs/                      # Documentación detallada + manual GUI
├── examples/                  # Plantillas (IDs, CSV entrenamiento)
└── src/crism_pipeline/        # Código fuente (+ assets/ logo)
```

## Documentación

| Documento | Contenido |
|-----------|-----------|
| [docs/01_conceptos.md](docs/01_conceptos.md) | CRISM, MTRDR, SR, índices Viviano 2014 |
| [docs/02_instalacion.md](docs/02_instalacion.md) | Entorno, dependencias, configuración |
| [docs/03_descarga.md](docs/03_descarga.md) | Descarga automatizada desde ODE |
| [docs/04_pipeline_procesamiento.md](docs/04_pipeline_procesamiento.md) | Flujo general y formatos |
| [docs/05_mapas_minerales.md](docs/05_mapas_minerales.md) | Browse products y mapas temáticos |
| [docs/06_deteccion_minerales.md](docs/06_deteccion_minerales.md) | Detección binaria por mineral |
| [docs/07_clasificacion_unidades.md](docs/07_clasificacion_unidades.md) | Clasificación geológica |
| [docs/08_manual_gui.md](docs/08_manual_gui.md) | Manual de la interfaz gráfica |

## Referencia principal

> Viviano-Beck, C. E., et al. (2014). *Revised CRISM spectral parameters and summary products based on the currently detected mineral diversity on Mars.* Journal of Geophysical Research: Planets, 119. [doi:10.1002/2014JE004627](https://doi.org/10.1002/2014JE004627)

## Licencia

Uso académico / investigación. Datos CRISM: NASA PDS Geosciences Node.
