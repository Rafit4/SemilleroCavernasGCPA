# Pipeline CRISM MTRDR SR

Pipeline en Python para descargar, procesar y analizar productos **CRISM MTRDR SR** (Refined Spectral Summary Parameters) usando los **60 índices espectrales de Viviano-Beck et al. (2014)**.

## Objetivos del pipeline

| Módulo | Función |
|--------|---------|
| `download` | Descarga cubos SR desde [ODE REST API](https://oderest.rsl.wustl.edu/) |
| `process` | Convierte ENVI (.img/.hdr) a HDF5 para procesamiento rápido |
| `maps` | Mapas minerales (índices individuales + browse products RGB) |
| `detect` | Detección binaria de minerales por umbrales adaptativos |
| `classify` | Clasificación de unidades geológicas (K-means, firmas, supervisado) |
| `run` | Ejecuta el flujo completo sobre una escena |

## Instalación rápida

```bash
cd Semillero
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e .
```

## Uso básico

```bash
# 1. Descargar cubos SR
python -m crism_pipeline download --pdsid "FRT00009*" --max-products 2

# 2. Convertir a HDF5
python -m crism_pipeline process --input data/raw/frt00009001_07_if163j_mtr3

# 3. Mapas minerales (browse MAF, PHY, HYD, CAR, FEM)
python -m crism_pipeline maps --input data/processed/FRT00009001_07_SR163J_MTR3.h5

# 4. Detección de olivina y carbonatos
python -m crism_pipeline detect --input data/processed/escena.h5 --mineral olivine mg_carbonate

# 5. Clasificación de unidades (K-means)
python -m crism_pipeline classify --input data/processed/escena.h5 --method kmeans --n-clusters 5

# Pipeline completo
python -m crism_pipeline run --input data/raw/frt00009001_07_if163j_mtr3
```

## Estructura del proyecto

```
Semillero/
├── config/
│   ├── pipeline.yaml          # Rutas, ODE, parámetros de stretch/clasificación
│   └── viviano2014.yaml       # Browse products, minerales, reglas de detección
├── data/
│   ├── raw/                   # Descargas ODE (.img, .hdr, .lbl)
│   ├── processed/             # Cubos HDF5
│   ├── maps/                  # PNG, GeoTIFF, detecciones, clasificaciones
│   └── models/                # Modelos entrenados (.joblib)
├── docs/                      # Documentación detallada
├── examples/                  # Plantillas (IDs, CSV entrenamiento)
└── src/crism_pipeline/        # Código fuente
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

## Referencia principal

> Viviano-Beck, C. E., et al. (2014). *Revised CRISM spectral parameters and summary products based on the currently detected mineral diversity on Mars.* Journal of Geophysical Research: Planets, 119. [doi:10.1002/2014JE004627](https://doi.org/10.1002/2014JE004627)

## Licencia

Uso académico / investigación. Datos CRISM: NASA PDS Geosciences Node.
