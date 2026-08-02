Antes de escribir cualquier código, genera un plan de implementación completo con estructura de carpetas, módulos, schema SQLite y tools MCP. Espera confirmación antes de proceder.

---

# DocSearch MCP

Servidor MCP para búsqueda local dentro de documentos usando **extracción de texto + segmentación estructural + BM25**.

El objetivo es permitir que un agente de IA pueda consultar una carpeta local con documentos heterogéneos y recuperar fragmentos relevantes con citas precisas.

---

## Objetivo

Construir un servidor MCP que permita buscar información dentro de archivos locales sin usar embeddings, sin base de datos vectorial y sin depender de servicios externos.

Debe funcionar sobre una carpeta local configurable y mantener un índice actualizado automáticamente cuando los archivos cambian.

---

## Alcance

El sistema debe:

* escanear una carpeta local
* detectar archivos compatibles
* extraer su contenido a texto
* segmentar el contenido en unidades buscables
* indexar esos segmentos con BM25
* actualizar el índice cuando los archivos cambien
* exponer herramientas MCP para búsqueda y recuperación de resultados

---

## Tipos de archivo soportados

El sistema debe estar diseñado para soportar al menos:

* PDF
* TXT
* Markdown
* DOCX
* XLSX
* CSV

La extracción debe delegarse a Kreuzberg.

---

## Arquitectura general

El sistema se compone de cinco partes principales:

### 1. Ingestion Layer

Responsable de descubrir archivos dentro de una carpeta y decidir cuándo un archivo debe procesarse o reprocesarse.

Debe detectar:

* archivos nuevos
* archivos modificados
* archivos eliminados

Debe ignorar carpetas internas del sistema como `.cache` o equivalentes.

---

### 2. Extraction Layer

Responsable de convertir archivos a texto utilizable.

Debe usar Kreuzberg como backend de extracción.

La salida de esta capa no debe depender directamente del formato original del extractor, sino normalizarse a una estructura interna propia.

---

### 3. Segmentation Layer

Responsable de dividir el contenido en unidades buscables.

No se debe indexar el archivo completo como una sola unidad, ni usar chunking ciego por tamaño fijo.

La segmentación debe seguir la estructura natural del documento según el tipo de archivo:

* PDF → página o bloque
* XLSX → hoja o tabla
* DOCX → sección o heading
* TXT / MD → bloque o heading
* CSV → tabla o fragmento tabular

Cada segmento debe conservar referencia clara a su archivo de origen y su ubicación exacta.

---

### 4. Index Layer

Responsable de indexar y consultar segmentos usando BM25.

Debe usar BM25X como motor principal.

La unidad de indexación debe ser el segmento, no el archivo completo.

Debe soportar:

* agregar segmentos nuevos
* actualizar segmentos de un archivo modificado
* eliminar segmentos de un archivo borrado
* buscar top-k resultados

---

### 5. Metadata Layer

Responsable de mantener el estado del corpus y del índice.

Debe usar SQLite.

Debe almacenar al menos:

* ruta del archivo
* hash del archivo
* fecha de modificación
* tamaño
* tipo MIME
* estado de indexación
* relación entre archivo y segmentos indexados

Esto se usa para saber qué archivos deben reprocesarse y para mantener consistencia entre disco, caché e índice.

---

## Caché local

El sistema debe mantener una caché local derivada del contenido procesado.

La caché debe permitir evitar reprocesar archivos sin cambios y facilitar depuración.

Debe almacenar por archivo:

* texto completo extraído
* metadatos
* segmentos generados

La caché no debe ser la fuente principal de búsqueda, pero sí la fuente intermedia entre extracción e indexación.

---

## Actualización automática

El sistema debe monitorear la carpeta configurada en tiempo real usando Watchdog.

Cuando un archivo se crea, modifica o elimina, el sistema debe:

1. detectar el cambio
2. aplicar debounce
3. revalidar el estado real del archivo
4. reprocesar solo lo necesario
5. actualizar caché, SQLite e índice BM25

Además del monitoreo por eventos, el sistema debe poder ejecutar reconciliación completa al iniciar.

---

## Flujo de indexación

### Al iniciar

* escanear la carpeta objetivo
* comparar archivos actuales con el estado en SQLite
* detectar nuevos, modificados y eliminados
* procesar cada cambio
* construir o actualizar índice
* activar el monitor de archivos

### Cuando cambia un archivo

* recalcular hash y metadatos
* reextraer contenido
* regenerar segmentos
* reemplazar en índice solo los segmentos de ese archivo
* actualizar caché y manifiesto

---

## Flujo de búsqueda

Cuando un agente realiza una consulta:

1. recibir query de texto
2. aplicar normalización básica
3. ejecutar búsqueda BM25 sobre segmentos
4. recuperar top-k resultados
5. devolver resultados enriquecidos con metadatos y contexto

---

## Resultado esperado de una búsqueda

Cada resultado debe incluir:

* texto del segmento encontrado
* score de relevancia
* archivo de origen
* tipo de archivo
* ubicación interna:

  * página
  * hoja
  * sección
  * bloque
* snippet o texto resumido del match
* identificador estable del segmento

---

## Requisitos de diseño

El sistema debe ser:

* local-first
* incremental
* explicable
* determinista
* barato en recursos
* fácil de depurar

Debe priorizar:

* precisión léxica
* trazabilidad
* simplicidad operacional

sobre:

* semántica profunda
* recuperación por embeddings
* razonamiento generativo durante búsqueda

---

## Lo que no debe hacer

El sistema no debe:

* usar embeddings
* usar base de datos vectorial
* subir archivos a la nube
* depender de servicios externos para búsqueda
* hacer OCR por defecto
* generar respuestas directamente dentro del índice

La responsabilidad del sistema es **recuperar evidencia**, no responder preguntas por sí mismo.

---

## Integración MCP

El servidor debe exponer herramientas MCP para que un agente pueda al menos:

* buscar dentro del corpus
* listar archivos indexados
* consultar detalles de un archivo
* forzar reindexación si es necesario

La interfaz MCP debe estar pensada para que un agente pueda hacer workflows tipo:

1. buscar
2. leer evidencia
3. refinar búsqueda
4. responder usando citas

---

## Stack esperado

* Python
* MCP SDK
* Kreuzberg
* BM25X
* Watchdog
* SQLite

---

## Prioridad de implementación

### Fase 1 — CLI (MVP)

El pipeline debe implementarse y verificarse primero como CLI, antes de exponer cualquier interfaz MCP.

Primera versión funcional con:

* escaneo de carpeta
* extracción (Kreuzberg)
* segmentación estructural por tipo de archivo
* indexación BM25 (BM25X)
* búsqueda top-k desde línea de comandos
* actualización incremental (Watchdog)
* caché local y estado en SQLite

La CLI se organiza alrededor de **proyectos**: un proyecto es un nombre registrado que apunta a una carpeta. Toda resolución de carpeta pasa por un proyecto registrado — no existe un flag `--folder` suelto. Esto evita ambigüedad sobre contra qué carpeta se opera y permite detectar carpetas solapadas entre proyectos (rechazadas al registrar).

La CLI debe permitir al menos:

* `docsearch project add <nombre> <carpeta>` — registra una carpeta bajo un nombre de proyecto (rechaza nombres duplicados, carpetas inexistentes y carpetas que se solapen con un proyecto ya registrado)
* `docsearch project list` — lista los proyectos registrados
* `docsearch project remove <nombre>` — elimina un proyecto y purga siempre su caché e índice asociados
* `docsearch index --project <nombre> [--file <archivo> ...] [--force]` — indexa el proyecto de forma incremental, o reindexa archivos puntuales con `--file` (repetible), o fuerza reextracción total con `--force`
* `docsearch search <query> --project <nombre> [--top N] [--full]` — busca y muestra resultados con citas; `<query>` es un argumento posicional
* `docsearch status --project <nombre> [--file <archivo> ...] [--list] [--filter indexed|error|pending]` — muestra estado del corpus, lista archivos indexados o inspecciona archivos específicos

No existe un comando `docsearch list` ni `docsearch reindex` independientes: quedan cubiertos por `status --list` e `index --file` respectivamente.

El resultado de `docsearch search` debe mostrar por cada resultado: archivo de origen, ubicación (página / hoja / sección), score de relevancia y snippet del texto encontrado.

### Fase 2 — Servidor MCP

La capa MCP se agrega únicamente después de que el pipeline de extracción, segmentación e indexación esté verificado y funcionando correctamente vía CLI.

Las herramientas MCP son un wrapper sobre el mismo pipeline ya validado.

### Fase 3 — Futuro opcional

Posibles mejoras fuera del alcance actual:

* OCR opcional
* filtros avanzados
* query expansion
* query rewriting
* búsqueda multi-paso
* integración con agentes más complejos

---

## Resumen funcional

DocSearch MCP debe convertir una carpeta local de documentos en un corpus buscable para agentes, con actualización automática, recuperación precisa y resultados citables.

---

## Notas para Claude Code

- Instalar dependencias con uv, no con pip
- Usar pyproject.toml para gestión del proyecto
- No crear archivos de código sin antes mostrar el plan completo y recibir confirmación