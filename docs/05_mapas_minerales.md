# 5. Mapas minerales

## 5.1 Objetivo

Generar mapas temáticos a partir de índices SR: mapas de índice individual (escala de grises) y **browse products** RGB (Viviano 2014, Tabla 3).

## 5.2 Comando

```bash
python -m crism_pipeline maps \
  --input data/processed/FRT00009001_07_SR163J_MTR3.h5 \
  --browse MAF PHY HYD CAR FEM PAL
```

## 5.3 Estiramiento (stretch)

El pipeline implementa las reglas de Viviano §5.3:

- **Parámetros locales** (R770, R600, SH600_2, …): percentiles 0.1–99.9 de la escena.
- **Resto de índices**: límite inferior fijo en 0; superior = max(percentil global 99, local 99.9).

Esto evita perder detecciones débiles sin sobreestimar el ruido de fondo.

## 5.4 Interpretación de browse products

### MAF — Mineralogía máfica

| Color dominante | Interpretación tentativa |
|-----------------|--------------------------|
| Rojo | Olivina, filosilicatos Fe (absorción ~1 μm) |
| Verde/cian | LCP (piroxeno bajo Ca, absorción ~2 μm) |
| Azul/magenta | HCP (piroxeno alto Ca) |

### PHY — Filosilicatos

| Color | Interpretación tentativa |
|-------|--------------------------|
| Rojo/magenta | Fe/Mg-OH (filosilicatos Fe/Mg) |
| Verde/cian | Al/Si-OH (filosilicatos Al, sílice hidratada) |
| Azul | Otros hidratados (sulfatos, carbonatos, hielo) |

### HYD — Minerales hidratados

| Color | Interpretación tentativa |
|-------|--------------------------|
| Magenta | Sulfatos polihidratados (1900 + 2400 nm) |
| Amarillo/verde | Sulfatos monohidratados (2100 nm) |
| Azul | Arcillas, carbonatos, zeolitas |

### CAR — Carbonatos

| Color | Interpretación tentativa |
|-------|--------------------------|
| Blanco azulado/amarillento | Carbonato de Mg |
| Rojo/magenta | Filosilicatos Fe/Mg (confusión posible) |

### FEM — Minerales de hierro

| Color | Interpretación tentativa |
|-------|--------------------------|
| Rojo | Óxidos férricos nanofásicos |
| Azul | Superficies más máficas / menos polvo |
| Amarillo/verde | Textura compactada o hematita cristalina |

## 5.5 Mapas de índice individual

Además de browse products, el pipeline genera mapas en escala de grises del **índice principal** de cada grupo mineral definido en `mineral_groups` (config).

Ejemplo de salida:

```
data/maps/<product_id>/indices/<product_id>_OLINDEX3.png
data/maps/<product_id>/indices/<product_id>_OLINDEX3.tif
```

## 5.6 Uso programático

```python
from pathlib import Path
from crism_pipeline.maps import load_cube, render_browse_product, render_index_map

cube = load_cube(Path("data/processed/escena.h5"))
render_browse_product(cube, "MAF", Path("data/maps/test"))
render_index_map(cube, "HCPINDEX2", Path("data/maps/test"))
```

## 5.7 Buenas prácticas

1. Siempre revisar **varios browse products** antes de concluir un mineral.
2. Comparar con **VNA** (albedo VNIR) para separar efectos morfológicos de espectrales.
3. Documentar Product ID, fecha de procesamiento y browse usados en publicaciones.
