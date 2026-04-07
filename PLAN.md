# Plan de Implementación — DocSearch CLI (Fase 1)

## Objetivo

Construir el pipeline completo de extracción, segmentación e indexación como CLI verificable antes de añadir la capa MCP.

---

## Estructura de carpetas

```
SearchDocs/
├── pyproject.toml
├── .gitignore
├── PLAN.md
├── src/
│   └── docsearch/
│       ├── __init__.py
│       ├── cli.py                  # Entry point CLI (Typer o argparse)
│       ├── config.py               # Config via env vars
│       ├── ingestion/
│       │   ├── __init__.py
│       │   ├── scanner.py          # Escaneo de carpeta, detección de cambios vs SQLite
│       │   └── watcher.py          # Watchdog + debounce → dispara reindexación
│       ├── extraction/
│       │   ├── __init__.py
│       │   └── extractor.py        # Wrapper Kreuzberg → ExtractedDoc normalizado
│       ├── segmentation/
│       │   ├── __init__.py
│       │   └── segmenter.py        # Segmentación por tipo: PDF/DOCX/MD/XLSX/CSV/TXT
│       ├── index/
│       │   ├── __init__.py
│       │   └── bm25_index.py       # Wrapper BM25X: add/update/delete/search
│       ├── metadata/
│       │   ├── __init__.py
│       │   ├── db.py               # aiosqlite, init schema, queries CRUD
│       │   └── models.py           # Dataclasses internos
│       └── cache/
│           ├── __init__.py
│           └── store.py            # Caché JSON por archivo en .cache/
└── tests/
    ├── test_extraction.py
    ├── test_segmentation.py
    ├── test_index.py
    └── test_cli.py
```

---

## Schema SQLite

```sql
CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT    NOT NULL UNIQUE,
    hash        TEXT    NOT NULL,        -- sha256 del contenido
    mtime       REAL    NOT NULL,
    size        INTEGER NOT NULL,
    mime_type   TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'pending',  -- pending | indexed | error
    indexed_at  REAL,
    error_msg   TEXT
);

CREATE TABLE IF NOT EXISTS segments (
    id              TEXT    PRIMARY KEY,  -- sha256(path + location_label + location_index)
    file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    content         TEXT    NOT NULL,
    location_type   TEXT    NOT NULL,    -- page | sheet | section | block | table
    location_label  TEXT    NOT NULL,    -- "Page 3", "Sheet: Ventas", "# Introducción"
    location_index  INTEGER NOT NULL,
    char_count      INTEGER NOT NULL
);
```

---

## Modelos internos (`models.py`)

```python
@dataclass
class FileRecord:
    path: str
    hash: str
    mtime: float
    size: int
    mime_type: str
    status: str  # pending | indexed | error

@dataclass
class ExtractedDoc:
    path: str
    text: str
    mime_type: str
    metadata: dict

@dataclass
class Segment:
    id: str
    file_path: str
    content: str
    location_type: str   # page | sheet | section | block | table
    location_label: str  # "Page 3", "Sheet: Ventas", "# Introducción"
    location_index: int

@dataclass
class SearchResult:
    segment_id: str
    score: float
    file_path: str
    mime_type: str
    location_type: str
    location_label: str
    content: str
    snippet: str         # ~200 chars alrededor del match
```

---

## Estrategia de segmentación por tipo

| Tipo        | Unidad de segmento                                      |
|-------------|---------------------------------------------------------|
| PDF         | Por página                                              |
| DOCX        | Por sección delimitada por heading H1–H3                |
| MD / TXT    | Por heading `#`, luego por bloque de párrafos si no hay |
| XLSX        | Por hoja → por tabla contigua (rango con datos)         |
| CSV         | Por tabla (archivo completo, o fragmentos de N filas)   |

Cada segmento conserva `location_type`, `location_label` y `location_index` para citas precisas.

---

## Caché local (`.cache/`)

Un archivo JSON por documento, nombrado `{sha256_of_path}.json`:

```json
{
  "path": "/docs/informe.pdf",
  "hash": "abc123...",
  "extracted_text": "...",
  "metadata": {},
  "segments": [
    {
      "id": "...",
      "location_type": "page",
      "location_label": "Page 1",
      "location_index": 1,
      "content": "..."
    }
  ]
}
```

El índice BM25X se persiste en `.cache/bm25_index/` usando la persistencia nativa de bm25x (se le pasa el path al constructor). No usar pickle.

---

## Config (`config.py`)

| Variable               | Default                        |
|------------------------|--------------------------------|
| `DOCSEARCH_FOLDER`     | requerido                      |
| `DOCSEARCH_CACHE_DIR`  | `{folder}/.cache`              |
| `DOCSEARCH_DB_PATH`    | `{cache_dir}/docsearch.db`     |
| `DOCSEARCH_TOP_K`      | `10`                           |
| `DOCSEARCH_DEBOUNCE`   | `1.0` segundos                 |

---

## Comandos CLI

```
docsearch index <carpeta>       Indexar o reindexar la carpeta completa
docsearch search <query>        Buscar en el corpus indexado
docsearch list                  Listar archivos indexados con su estado
docsearch status                Mostrar resumen del corpus (N archivos, N segmentos)
docsearch reindex <archivo>     Forzar reindexación de un archivo específico
```

### Output de `docsearch search`

Por cada resultado:
```
[1] archivo.pdf — Page 3  (score: 0.87)
    "...snippet del texto encontrado con contexto suficiente..."
```

---

## Flujo de inicialización / `docsearch index`

1. Leer config
2. Inicializar SQLite (crear tablas si no existen)
3. Cargar o reconstruir índice BM25X desde segmentos en SQLite
4. Escanear carpeta → comparar hashes con SQLite → detectar nuevos / modificados / eliminados
5. Para cada cambio: extraer → segmentar → actualizar caché → actualizar SQLite → actualizar índice
6. Guardar índice BM25X en disco

## Flujo de `docsearch search`

1. Recibir query
2. Normalización básica (lowercase, strip)
3. Ejecutar búsqueda BM25X sobre segmentos
4. Recuperar top-k resultados con metadatos desde SQLite
5. Generar snippet
6. Imprimir resultados formateados

## Flujo de `docsearch reindex <archivo>`

1. Calcular hash y metadatos del archivo
2. Eliminar segmentos del archivo en SQLite e índice BM25X
3. Reextraer contenido con Kreuzberg
4. Regenerar segmentos
5. Actualizar caché, SQLite e índice

---

## Dependencias (`pyproject.toml`)

```toml
[project]
name = "docsearch"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    "kreuzberg",
    "bm25x",
    "watchdog",
    "aiosqlite",
    "typer",
]

[project.scripts]
docsearch = "docsearch.cli:app"
```

---

## Orden de implementación

**Implementar y verificar cada módulo antes de pasar al siguiente.**

1. `models.py` — dataclasses internos
2. `config.py` — lectura de env vars
3. `metadata/db.py` — schema SQLite y queries CRUD
4. `extraction/extractor.py` — wrapper Kreuzberg
5. `segmentation/segmenter.py` — segmentación por tipo
6. `index/bm25_index.py` — wrapper BM25X
7. `cache/store.py` — caché JSON por archivo
8. `ingestion/scanner.py` — escaneo y detección de cambios
9. `ingestion/watcher.py` — Watchdog + debounce
10. `cli.py` — comandos CLI que orquestan todo lo anterior

---

## Lo que queda fuera de esta fase

- Servidor MCP (Fase 2)
- OCR
- Filtros avanzados / query expansion
- Búsqueda multi-paso