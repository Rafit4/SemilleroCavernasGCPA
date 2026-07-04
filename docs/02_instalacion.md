# 2. Instalación y configuración

## 2.1 Requisitos

- Python 3.10 o superior
- Windows, Linux o macOS
- ~2 GB de espacio por escena CRISM (cubo SR + derivados)

## 2.2 Instalación

```bash
cd C:\Users\57319\Documents\2026\Semillero
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

Verificar:

```bash
python -m crism_pipeline --help
```

## 2.3 Archivos de configuración

### `config/pipeline.yaml`

| Sección | Propósito |
|---------|-----------|
| `ode` | Parámetros de la API REST de ODE |
| `paths` | Rutas de datos (`raw`, `processed`, `maps`, `models`) |
| `stretch` | Reglas de estiramiento para visualización (Viviano §5.3) |
| `classification` | Features por defecto, número de clusters |
| `detection` | Percentil de umbral por defecto |

### `config/viviano2014.yaml`

| Sección | Propósito |
|---------|-----------|
| `browse_products` | Definición RGB de cada browse product |
| `mineral_groups` | Índice principal por grupo mineral |
| `mineral_detection` | Reglas AND para detección binaria |
| `unit_signatures` | Firmas espectrales para clasificación por firmas |

## 2.4 Personalización

### Añadir un mineral a detección

Editar `config/viviano2014.yaml`:

```yaml
mineral_detection:
  mi_mineral:
    conditions:
      - index: D2300
        threshold_mode: percentile
        threshold: 90
      - index: BD2210_2
        threshold_mode: percentile
        threshold: 85
```

Luego:

```bash
python -m crism_pipeline detect --input escena.h5 --mineral mi_mineral
```

### Cambiar features de clasificación

En `config/pipeline.yaml`, sección `classification.default_features`.

## 2.4 Variables de entorno (opcional)

No son obligatorias. El pipeline usa rutas relativas al directorio raíz del proyecto.

## 2.5 Solución de problemas

| Error | Causa probable | Solución |
|-------|----------------|----------|
| `Banda 'X' no encontrada` | Nombre distinto en .HDR | Inspeccionar `band names` del header ENVI |
| `No se encontró cubo SR` | Solo descargó IF, no SR | Repetir descarga; verificar patrón `*_SR*J_MTR3*` |
| `rasterio` falla en GeoTIFF | Sin info de proyección | Normal si el header no tiene `map info`; PNG sigue generándose |
| Descarga lenta | Muchos archivos por producto | Usar `--max-products` para pruebas |
