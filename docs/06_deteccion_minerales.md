# 6. Detección de minerales

## 6.1 Objetivo

Producir **mapas binarios** (presente/ausente) para minerales o grupos minerales usando reglas multi-índice definidas en `config/viviano2014.yaml`.

## 6.2 Comando

```bash
# Un mineral
python -m crism_pipeline detect \
  --input data/processed/escena.h5 \
  --mineral olivine

# Varios minerales
python -m crism_pipeline detect \
  --input data/processed/escena.h5 \
  --mineral olivine hcp mg_carbonate phyllosilicate_fe_mg

# Todos los minerales configurados
python -m crism_pipeline detect --input data/processed/escena.h5
```

## 6.3 Minerales disponibles

| Clave | Mineral / grupo |
|-------|-----------------|
| `olivine` | Olivina |
| `lcp` | Piroxeno bajo Ca |
| `hcp` | Piroxeno alto Ca |
| `phyllosilicate_fe_mg` | Filosilicatos Fe/Mg |
| `phyllosilicate_al` | Filosilicatos Al |
| `mg_carbonate` | Carbonato Mg |
| `hydrated_silica` | Sílice hidratada |
| `monohydrated_sulfate` | Sulfato monohidratado |
| `polyhydrated_sulfate` | Sulfato polihidratado |
| `hematite` | Hematita / Fe cristalino |

## 6.4 Lógica de detección

Cada mineral tiene **condiciones AND**. Ejemplo para olivina:

```yaml
olivine:
  conditions:
    - index: OLINDEX3
      threshold_mode: percentile
      threshold: 92        # píxel > percentil 92 de la escena
    - index: BDI1000VIS
      threshold_mode: percentile
      threshold: 85
```

Para HCP se añade condición `LCPINDEX2` con `operator: lt` (menor que percentil 70) para favorecer piroxeno alto Ca sobre bajo Ca.

## 6.5 Salidas

```
data/maps/<product_id>/detection/
├── <product_id>_olivine_detection.png    # máscara + overlay
├── <product_id>_olivine_detection.tif    # GeoTIFF binario
└── ...
```

La consola reporta **cobertura %** (fracción de píxeles válidos detectados).

## 6.6 Ajuste de umbrales

Los percentiles por defecto (85–92) son conservadores. Para escenas ruidosas:

- **Subir** percentil → menos falsos positivos, más falsos negativos.
- **Bajar** percentil → más detecciones, más riesgo de ruido.

Editar `config/viviano2014.yaml` → sección `mineral_detection`.

También puedes usar `threshold_mode: fixed` con un valor absoluto:

```yaml
- index: OLINDEX3
  threshold_mode: fixed
  threshold: 0.05
```

## 6.7 Validación científica

La detección automatizada es un **primer filtro**, no un diagnóstico definitivo:

1. Verificar píxeles detectados en browse product correspondiente (ej. MAF para olivina).
2. Extraer espectro del cubo IF en esas coordenadas si hay ambigüedad.
3. Comparar con biblioteca MICA / literatura del sitio.

## 6.8 Uso programático

```python
from pathlib import Path
from crism_pipeline.detection import run_detection_pipeline

results = run_detection_pipeline(
    Path("data/processed/escena.h5"),
    Path("data/maps/detection"),
    minerals=["olivine", "mg_carbonate"],
)
for key, res in results.items():
    print(res.label, res.coverage_pct, res.thresholds)
```
