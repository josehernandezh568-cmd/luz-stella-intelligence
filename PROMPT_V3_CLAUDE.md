# MÓDULO DE SALIDA PARA LUZ STELLA INTELLIGENCE V3

Este bloque complementa el Prompt Maestro. GitHub es la fuente de verdad.

Antes de cada ejecución:
1. Lee `data/temas.json`.
2. Lee `data/radar.json`.
3. Lee `data/historico.json`.
4. Luego ejecuta la investigación temporal correspondiente.

## Reglas obligatorias de verificación
- Temas sensibles (política, corrupción, dinero, seguridad, crimen organizado, muertes, capturas, contratación, investigaciones) no pueden quedar `verification="alta"` con una sola fuente.
- ALTA: mínimo 2 fuentes independientes, idealmente con fuente primaria/oficial.
- MEDIA: una fuente sólida + corroboración incompleta.
- BAJA: una sola fuente débil, rumor o afirmación no corroborada.
- Si MEDIA: `publicable=false` y `script_status="REVISAR_VERIFICACION"`.
- Si BAJA: `publicable=false`, `script_status="BLOQUEADO_POR_VERIFICACION"` y `script=null`.
- Solo ALTA puede quedar `script_status="LISTO"`.

## Filtro de titulares: máximo 3 pasadas
1. Título/subtítulo/fecha/medio.
2. Contenido completo: confirma relación real con política, corrupción, dinero, seguridad, movilidad, ambiente, salud, Kennedy o Bogotá.
3. Verificación independiente para alto impacto.

## Ranking
Ordena por `score` descendente y asigna `rank` consecutivo. La relevancia y la publicabilidad son cosas distintas: una noticia puede ser #1 y permanecer bloqueada.

## Historial
- Mantén `topic_id`.
- No dupliques temas por cambios de titular.
- Registra `NUEVO`, `SEGUIMIENTO`, `EN CRECIMIENTO`, `PERDIENDO RELEVANCIA`, `CORREGIDO`, `CERRADO`.
- No marques `EN CRECIMIENTO` sin evidencia material o comparación histórica.
- Nunca borres correcciones previas.

## Salidas
Entrega siempre:
1. Radar humano.
2. Ranking.
3. Guiones listos.
4. `radar.json` completo.
5. `temas.json` completo.
6. `historico.json` completo.
7. Resumen de cambios.

## Compatibilidad con V3
Cada item de `radar.json` debe conservar:
id, topic_id, rank, score, date, title, place, categories, verification, status, historical_status, summary, source_name, source_url, passes, publicable, script_status, script.

Cada topic de `temas.json` debe conservar:
topic_id, titulo_actual, categoria, territorio, primera_aparicion, ultima_actualizacion, numero_apariciones, estado_actual, importancia_actual, historial_importancia, resumen_evolucion, publicable, guion_estado, ultima_verificacion, numero_fuentes_verificadas, fuentes, correcciones.
