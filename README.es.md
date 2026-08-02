# Doclex

*[English](README.md) · Español*

Un CLI que convierte una carpeta local de documentos en un corpus buscable y citable. Apuntá a una carpeta; la extracción, segmentación, indexación y seguimiento de cambios ocurren automáticamente.

## Por qué

[Kreuzberg](https://github.com/Goldziher/kreuzberg) extrae texto. BM25X indexa strings. Ninguno de los dos sabe qué es un "archivo", cuándo cambió, ni cómo convertir un match en una cita. Doclex es la capa de orquestación que los une para que nunca tengas que pensar en el pipeline vos mismo:

- **Enchufar y listo** — apuntá a una carpeta. Extracción, segmentación estructural, indexación y seguimiento de cambios ocurren automáticamente; no hay ningún pipeline que armar.
- **SQLite es la fuente de verdad** — el hash, mtime y estado de indexación de cada archivo viven en un solo lugar, así que Doclex siempre sabe exactamente qué cambió y reprocesa solo eso.
- **Local por diseño** — todo corre en tu máquina, nada sale de ahí. Sin embeddings, sin base de datos vectorial, sin nube.
- **Determinístico** — scoring léxico BM25, sin similitud de caja negra.
- **Trazable** — cada resultado cita su archivo, página/hoja/sección, y score.
- **Incremental** — solo reprocesa los archivos que realmente cambiaron.

## Instalación

Requiere Python ≥3.12 y [uv](https://docs.astral.sh/uv/).

```bash
git clone <repo-url>
cd doclex
uv sync
```

## Inicio rápido

```bash
# registrar una carpeta como proyecto
uv run doclex add mydocs ./ruta/a/tus/documentos

# construir el índice
uv run doclex index --project mydocs

# buscar
uv run doclex search "presupuesto trimestral" --project mydocs
```

```
[1] presupuesto_2024.pdf — página 3  (score: 4.812)
    "...se aprobó el presupuesto trimestral con un incremento del 12% en..."

[2] notas.md — Planificación  (score: 2.107)
    "...hay que revisar los supuestos del presupuesto antes de..."
```

## Recorrido completo

Un flujo típico del día a día, desde un proyecto vacío hasta mantenerlo sincronizado:

```bash
# 1. registrá la carpeta que querés buscar
doclex add contratos ~/Documentos/legal/contratos

# 2. construí el índice — extrae, segmenta e indexa cada archivo soportado
doclex index --project contratos
```
```
Processing: 42 new, 0 modified, 0 deleted
✓ Done.
```
```bash
# 3. buscá
doclex search "cláusula de rescisión" --project contratos
```
```
[1] Contrato_2023_AcmeCorp.pdf — Sección 9.2  (score: 6.104)
    "...cualquiera de las partes podrá rescindir este Acuerdo con 30 días de preaviso..."

[2] acuerdo_proveedor_v3.docx — Rescisión  (score: 5.887)
    "...la rescisión por conveniencia requiere 60 días de preaviso a..."
```
```bash
# 4. revisá qué está indexado
doclex status --project contratos
```
```
Folder       ~/Documentos/legal/contratos
Indexed      42 files
Segments     318
BM25 index   318 docs
Disk state   up to date
```
```bash
# 5. aparece un contrato nuevo en disco — reindexar lo detecta automáticamente
doclex index --project contratos
```
```
Processing: 1 new, 0 modified, 0 deleted
✓ Done.
```
```bash
# 6. ver todos los proyectos registrados
doclex list
```
```
Name        Folder
contratos   /home/vos/Documentos/legal/contratos
```
```bash
# 7. terminaste con él — desregistralo y purgá su caché/índice
doclex remove contratos
```

Cada proyecto es independiente — registrá tantas carpetas no solapadas como necesites, cada una con su propia caché e índice:

```bash
doclex add politicas-rrhh ~/Documentos/rrhh
doclex index --project politicas-rrhh
doclex search "días de vacaciones" --project politicas-rrhh --top 5
```

## Proyectos

Todos los comandos operan sobre un **proyecto registrado** — un nombre vinculado a una carpeta — en vez de un flag `--folder` suelto. Esto mantiene la resolución de carpetas sin ambigüedad y permite que Doclex rechace carpetas solapadas (una subcarpeta registrada como su propio proyecto duplicaría silenciosamente la indexación y la caché):

```bash
doclex add mydocs ./ruta/a/tus/documentos
doclex add mydocs ./otra       # error: el nombre ya existe
doclex add sub ./ruta/a/tus/documentos/subcarpeta   # error: se solapa con 'mydocs'
doclex remove mydocs           # desregistra y purga su caché/índice
```

## Comandos

| Comando | Descripción |
|---|---|
| `doclex add <nombre> <carpeta>` | Registra una carpeta bajo un nombre de proyecto |
| `doclex list` | Lista los proyectos registrados |
| `doclex remove <nombre>` | Elimina un proyecto y purga su caché/índice |
| `doclex index --project <nombre>` | Escanea e indexa (incremental por defecto) |
| `doclex search <query> --project <nombre>` | Busca e imprime resultados con citas |
| `doclex status --project <nombre>` | Muestra el estado del corpus/índice |

Corré `doclex <comando> --help` para ver todos los flags y ejemplos.

### Flags en la práctica

```bash
# forzar una re-extracción completa
doclex index --project mydocs --force

# reindexar archivos puntuales después de editarlos
doclex index --project mydocs --file informe.pdf --file notas.docx

# más resultados, texto completo del segmento en vez de un snippet
doclex search "evaluación de riesgo" --project mydocs --top 20 --full

# listar cada archivo indexado y su estado
doclex status --project mydocs --all --filter error
```

## Arquitectura

```
carpeta → escaneo/watch → extracción (Kreuzberg) → segmentación → índice BM25X
                                                          ↕
                                                  SQLite (archivos, segmentos)
```

| Capa | Responsabilidad |
|---|---|
| **Ingestion** | Escanea la carpeta de un proyecto, hashea archivos para detectar nuevos/modificados/eliminados, ignora su propio directorio de caché |
| **Extraction** | Delega en [Kreuzberg](https://github.com/Goldziher/kreuzberg) para convertir cada archivo en texto plano, normalizado a un formato interno |
| **Segmentation** | Divide el texto siguiendo la estructura natural del archivo — nunca chunking ciego por tamaño fijo (PDF → página, XLSX → hoja, DOCX → sección, TXT/MD → bloque) |
| **Index** | Indexa segmentos (no archivos completos) con BM25X; soporta agregar/actualizar/eliminar de forma incremental |
| **Metadata** | SQLite guarda el hash, mtime, tamaño, tipo MIME y estado de indexación de cada archivo, más qué segmentos le pertenecen |

Una caché local guarda el texto extraído y los segmentos generados por archivo, así los archivos sin cambios nunca se reprocesan.

## Tipos de archivo soportados

PDF · TXT · Markdown · DOCX · XLSX · CSV

## Principios de diseño

Doclex está construido para ser local por diseño, incremental, explicable, determinístico y barato de correr. Deliberadamente **no**:

- usa embeddings ni base de datos vectorial
- sube archivos a ningún lado
- depende de servicios externos para buscar
- corre OCR por defecto
- genera respuestas — recupera evidencia, no la interpreta

## Stack

Python · [Typer](https://typer.tiangolo.com/) · [Kreuzberg](https://github.com/Goldziher/kreuzberg) · BM25X · Watchdog · SQLite

## Desarrollo

```bash
uv sync --extra dev
uv run pytest
```
