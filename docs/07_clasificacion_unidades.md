# 7. Clasificación de unidades geológicas

## 7.1 Objetivo

Segmentar la escena en **unidades espectrales** usando combinaciones de índices SR. Tres métodos disponibles:

| Método | Cuándo usarlo |
|--------|---------------|
| `kmeans` | Exploración sin etiquetas; descubrir unidades espectrales |
| `signature` | Comparar con unidades predefinidas en config |
| `supervised` | Tienes polígonos/píxeles de entrenamiento etiquetados |

## 7.2 K-means (no supervisado)

```bash
python -m crism_pipeline classify \
  --input data/processed/escena.h5 \
  --method kmeans \
  --n-clusters 5
```

**Proceso:**
1. Extrae features (índices SR por defecto en `pipeline.yaml`).
2. Muestrea hasta 50 000 píxeles válidos.
3. Estandariza y aplica K-means.
4. Asigna cluster a todos los píxeles válidos.

**Salida:** mapa con clusters 0…N-1 (requiere interpretación manual).

## 7.3 Clasificación por firmas (`signature`)

```bash
python -m crism_pipeline classify \
  --input data/processed/escena.h5 \
  --method signature
```

Usa `unit_signatures` en `config/viviano2014.yaml`:

```yaml
unit_signatures:
  basaltic_soil:
    label: Suelo basáltico
    high: [R770, BDI1000VIS]
    low: [D2300, BD1900_2]
  clay_unit:
    label: Unidad arcillosa
    high: [D2300, D2200, BD1900r2]
    low: [OLINDEX3]
```

Cada píxel se asigna a la unidad con mayor score (índices altos suman, bajos restan).

**Limitación:** método heurístico; validar con mapas browse y geología de contexto.

## 7.4 Clasificación supervisada

Prepara un CSV con píxeles etiquetados (coordenadas en filas/columnas del cubo SR):

```csv
row,col,unit
120,340,olivine_rich
200,410,clay_unit
350,280,basaltic_soil
```

Ver plantilla: `examples/training_pixels.example.csv`

```bash
python -m crism_pipeline classify \
  --input data/processed/escena.h5 \
  --method supervised \
  --training-csv examples/mi_entrenamiento.csv
```

**Modelo:** Random Forest (200 árboles) con validación hold-out 75/25.

**Salidas adicionales:**
- `*_classification_report.txt` — precision/recall por unidad
- `*_random_forest_model.joblib` — modelo reutilizable

### Cómo obtener coordenadas de entrenamiento

1. Abre browse product en QGIS o matplotlib.
2. Identifica píxeles representativos de cada unidad.
3. Anota `row` (línea) y `col` (muestra) — origen arriba-izquierda.

## 7.5 Features por defecto

Definidos en `config/pipeline.yaml`:

```yaml
default_features:
  - OLINDEX3
  - LCPINDEX2
  - HCPINDEX2
  - D2300
  - D2200
  - BD1900r2
  - BD2100_2
  - SINDEX2
  - BD2500H2
  - BDI1000VIS
  - R770
```

Estos índices capturan variabilidad máfica, hidratación y albedo.

## 7.6 Interpretación del mapa de unidades

```
data/maps/<product_id>/classification/
├── <product_id>_kmeans_units.png
├── <product_id>_kmeans_units.tif
├── <product_id>_kmeans_meta.json
└── <product_id>_kmeans_model.joblib
```

Para K-means, correlaciona cada cluster con:
- Browse products (MAF, PHY, HYD)
- Mapas de detección mineral
- Morfología (albedo VNA)

## 7.7 Flujo integrado recomendado

```
1. maps (MAF, PHY, HYD)     → identificar unidades visualmente
2. detect (minerales clave)  → confirmar presencia
3. classify (kmeans)         → segmentar escena
4. Etiquetar clusters       → CSV de entrenamiento
5. classify (supervised)    → mapa final con nombres geológicos
```

## 7.8 Uso programático

```python
from pathlib import Path
from crism_pipeline.classification import run_classification_pipeline

labels, meta = run_classification_pipeline(
    Path("data/processed/escena.h5"),
    Path("data/maps/classification"),
    method="kmeans",
    n_clusters=6,
)
print(meta["classes"])
```

## 7.9 Consideraciones

- **Correlación espacial:** píxeles vecinos no son independientes; la validación cruzada estándar puede ser optimista.
- **Mezclas:** un píxel puede contener varios minerales; la clasificación dura (una etiqueta) es una simplificación.
- **Multi-escena:** entrenar por escena o combinar features normalizadas por percentil si trabajas múltiples FRT.
