# Luz Stella Intelligence V3

## Novedades
- Radar priorizado por score.
- Filtro por categoría, verificación, estado histórico y publicabilidad.
- Centro de guiones con bloqueo visual para noticias no verificadas.
- Seguimiento por `topic_id`.
- Evolución de importancia por tema.
- Fuentes acumuladas por tema.
- Correcciones históricas visibles.
- Gráficos de categorías, volumen por corte, verificación y estados históricos.

## Instalación
Sube toda la estructura al repositorio y reemplaza:
- `index.html`
- `data/radar.json`
- `data/temas.json`
- `data/historico.json`

Conserva la carpeta `prompts/`.

GitHub Pages:
Settings → Pages → Deploy from a branch → `main` → `/ (root)`.

## Flujo diario
1. Ejecuta el radar en Claude.
2. Descarga/copias los 3 JSON completos.
3. Reemplaza `data/radar.json` y `data/temas.json`.
4. `data/historico.json` debe conservar todos los cortes anteriores y agregar el nuevo.
5. Commit.
6. El dashboard se actualiza automáticamente.

## Regla crítica
Que una noticia tenga ranking alto no significa que sea publicable. El dashboard muestra ambas dimensiones por separado.
