---
tags: [proyecto, documentacion, arquitectura]
fecha: 2026-08-23
---

# 🔬 Funcionamiento interno — Asistente Universitario

> Documentación técnica completa del programa: librerías, módulos, funciones,
> flujos de datos, persistencia y decisiones de diseño. Si vas a tocar código,
> lee esto primero. Complementa a `ARQUITECTURA.md` (que es la vista de alto nivel).

---

## 1. Visión general

El sistema es un bot personal de Telegram que convierte mensajes en
investigaciones académicas documentadas:

```
mensaje/foto ──▶ parser ──▶ searcher (web) ──▶ llm (IA) ──▶ writer (.md) ──▶ Telegram
                                    │                            │
                                    └── usage (cuota) ◀──────────┘
                                                                 └──▶ syncer ──▶ Obsidian
```

Proceso único, sin base de datos servidor: todo estado vive en archivos
(`documentos/`, `data/usage.json`, `logs/bot.log`). Un solo usuario autorizado;
todo lo demás se ignora silenciosamente.

---

## 2. Librerías externas (por qué cada una)

### python-telegram-bot `==22.8`
Framework async para bots. Conceptos que usa el proyecto:

| Concepto | Rol aquí |
|---|---|
| `Application` | Objeto central; se construye con `Application.builder().token(TOKEN).build()` |
| Polling (`run_polling`) | El bot pregunta a los servidores de Telegram si hay updates (long polling HTTP). No requiere IP pública ni webhook |
| `Update` | Envoltorio de todo evento entrante; expone `.message`, `.callback_query`, `.effective_user` |
| `CommandHandler` | Dispara con `/comando`; pasa `(update, context)` |
| `MessageHandler(filters)` | Captura texto (`filters.TEXT & ~filters.COMMAND`) o fotos (`filters.PHOTO`) |
| `CallbackQueryHandler` | Captura toques en botones inline (`callback_data` string) |
| `add_error_handler(fn)` | Red de seguridad: toda excepción no manejada en un handler cae en `on_error()` |
| `reply_text(parse_mode="Markdown")` | Respuestas con formato |

Detalle importante: PTB tipa `update.message` y `update.callback_query` como
opcionales (`Message | None`) aunque los filtros garanticen lo contrario; el
código documenta esa invariante con `assert`.

### ddgs `==9.15.0`
Cliente de búsqueda DuckDuckGo sin API key. Uso:
```python
with DDGS() as ddgs:                      # context manager (sesión HTTP)
    ddgs.text(f"{tema} explicación", max_results=N)
```
Devuelve iterables de dicts con claves `title`, `href`, `body` — el proyecto los
normaliza a `{title, url, snippet}`.

### google-genai `==2.19.0`
SDK oficial de Google Gemini. Se importa *dentro* de la función (import perezoso):
```python
client = genai.Client(api_key=...)        # cliente REST síncrono
client.models.generate_content(
    model=AI_MODEL,
    contents=[prompt] o [prompt, types.Part.from_bytes(data, mime)],
    config={"system_instruction": ...},
)
```
`Part.from_bytes` es lo que habilita visión (leer fotos) sin OCR externo.

### openai `==3.3.1`
Cliente estándar OpenAI. La gracia: sirve para **cualquier API compatible**
cambiando `base_url`. Aquí apunta a OpenRouter:
```python
OpenAI(api_key=..., base_url="https://openrouter.ai/api/v1")
.chat.completions.create(model=..., messages=[{role, content}, ...])
```
Para visión, el `content` del mensaje usuario es una lista:
`[{"type": "text", ...}, {"type": "image_url", "image_url": {"url": "data:<mime>;base64,<b64>"}}]`.

### python-dotenv `==1.2.3`
`load_dotenv(BASE_DIR / ".env")` con ruta explícita — funciona sin importar el
directorio desde donde se lance `python main.py`.

### Stdlib protagonista
- `asyncio.to_thread` — corre funciones bloqueantes (IA, descarga de fotos) sin trabar el event loop de PTB.
- `logging.handlers.RotatingFileHandler` — log a archivo que rota por tamaño.
- `hashlib.md5` + `shutil.copy2` — comparación y copia incremental al vault.
- `pathlib.Path` — todas las rutas; `re` — parseo y extracción de errores del log.
- `json` — contador diario y respuesta estructurada de la visión.

---

## 3. Mapa de módulos y reglas de dependencia

```
main.py ──────────────▶ bot.py (orquestador Telegram)
                          │
     ┌────────┬──────────┼───────────┬────────────┐
     ▼        ▼          ▼           ▼            ▼
  parser   searcher   analyzer    writer      syncer
              │         │                        │
              │         ▼                        ▼
              │       llm.py                    (config)
              │      ┌────┴────┐
              │   gemini   openai-compat
              ▼
           (config)
  usage.py ◀── analyzer (registra consumo)
  logsetup.py ◀── bot.py (al importar configura logging global)
  config.py ◀── TODOS (única fuente de verdad de rutas/tokens/env)
```

Reglas: `config.py` no depende de nadie; `llm.py` no sabe de prompts ni de
Telegram; `analyzer.py` conoce prompts + llm + usage; `bot.py` orquesta pero no
implementa lógica de negocio.

---

## 4. Arranque: ciclo de vida

1. `python main.py` → importa `bot.main()` y lo ejecuta.
2. Al **importar** `asistente.bot` ocurren dos efectos: `setup_logging()`
   (crea `logs/bot.log`, adjunta handler rotativo + consola a la raíz, baja
   `httpx` a WARNING) y se cargan todas las constantes de `config`.
3. `main()`: `validate()` revisa TELEGRAM_TOKEN, AI_API_KEY, AUTHORIZED_USER_ID
   y coherencia AI_PROVIDER/AI_MODEL. Si falta algo → `SystemExit` con lista clara.
4. Construcción de la `Application` y registro de **10 handlers** en orden:
   7 comandos (`start help menu docs sync uso logs`), 1 `CallbackQueryHandler`,
   2 `MessageHandler` (texto-no-comando, foto) y 1 error handler.
5. `run_polling()` entra en bucle infinito: getUpdates → despachar → repetir.
   Terminar con Ctrl+C; PTB cierra limpio.

⚠️ Dos instancias simultáneas → Telegram responde **409 Conflict**. Por eso
existe el hábito `pkill -f "python main.py"` antes de relanzar.

---

## 5. Flujo completo: mensaje de texto

### 5.1 Recepción y autorización
`handle_message(update, ctx)`: primero `authorized(update)` — compara
`update.effective_user.id` con `AUTHORIZED_USER_ID` (si es `0`, acepta a
cualquiera: útil para tests). No autorizado → return silencioso.

### 5.2 Parseo — `parser.parse_message(text)`
- Vacío → `None` (el bot responde con la ayuda).
- Con `:` → `head:body`: título = `head.strip(" .")`, temas = partir `body` por
  la regex `SEPARATORS = [,;\n]+`, limpiando `" .-"` de cada tema.
  Título vacío o cero temas → `None`.
- Sin `:` → separar igual; un solo tema ⇒ título = primeras 6 palabras;
  varios ⇒ título genérico `"Investigación"`.

`slugify(text)`: minúsculas → tabla áéíóúñ→aeioun → `re.sub('[^a-z0-9]+' , '-')`
→ trim de guiones → máximo 60 chars → fallback `"documento"`.

### 5.3 Investigación — `bot.research(update, title, topics)`
Avisa al usuario, luego **secuencialmente** por cada tema:

**a) Búsqueda — `searcher.search_topic(topic, max_results)`**
Consulta literal `"{topic} explicación"` (el sufijo mejora resultados
didácticos). Hasta `RETRIES=3` intentos; entre fallo y fallo duerme
`2*intento` s (backoff simple). Acumula resultados normalizados y retorna al
primer intento con datos. Si todo falla → lista vacía (no lanza).

**b) Síntesis — `analyzer.analyze_topic(topic, results)`**
Sin resultados → nota informativa (no gasta IA). Con resultados arma la lista
de fuentes `- **título** — snippet (URL: url)` y la inyecta en `PROMPT`
(instrucciones: definición/contexto, conceptos clave con cursivas y término en
inglés, ejemplos concretos/código, aplicaciones, tabla final, 600–1000
palabras, español, sin enlaces en el cuerpo). Todo bajo `SYSTEM_PROMPT`
(persona didáctica, no inventar).
Llama `llm.generate(...)`. Solo si hay texto no-vacío registra consumo
(`register_call()`). Cualquier excepción o respuesta vacía → `_fallback()`:
documento igual generado con snippets crudos (degradación elegante).

### 5.4 Escritura — `writer.write_document(title, topics, sections, results_by_topic)`
Ruta: `documentos/<YYYY>/<MM-mes>/<DD_HH-MM>_<slug>.md`; si existe, sufijo
`-2`, `-3`… Contenido:
1. Frontmatter YAML (`tags: [universidad, investigacion]`, `fecha`, `hora`)
2. `# Título` + párrafo introductorio + línea de firma
3. `## Índice` numerado de temas
4. Por tema: `## N. tema` + sección generada + separador
5. `## Fuentes consultadas` — `_sources_section()` numera URLs **deduplicadas
   globalmente** (set `seen`, chequeado al insertar), agrupadas por tema;
   sin fuentes → sección omitida.

Después `update_index(dir_mes)` **regenera desde disco** `00_Índice.md`:
frontmatter propio, total de docs, bloque ```dataview``` (TABLE hora/fecha FROM
#investigacion WHERE file.folder = this.file.folder) y wikilinks
`[[stem|Título]]` ordenados descendente. Como se reconstruye leyendo la
carpeta (ignorando el propio índice), borrar un documento lo saca del índice
en la próxima escritura: auto-sanable.

Helpers de lectura: `_doc_title()` primera línea `# ` o stem; `_hora()` valor
de frontmatter `hora:` con `-`→`:`.

### 5.5 Respuesta
Reply con nombre del archivo + `used/limit` de hoy (`usage.get_usage`) y menú
inline (`show_menu`).

---

## 6. Flujo completo: foto 📷

`handle_photo`:
1. Guardia de autorización.
2. **Atajo barato**: si el caption contiene `:`, se intenta `parse_message`;
   si produce título+temas, va directo a `research` (cero cuota de visión).
3. Sin caption útil: avisa, toma la foto más grande (`photo[-1]` — Telegram
   entrega varias resoluciones), `await photo.get_file()` y
   `download_as_bytearray()` → `bytes`.
4. `asyncio.to_thread(extract_topics_from_image, data, "image/jpeg")`: la
   llamada HTTP de Gemini/OpenRouter es bloqueante; `to_thread` evita congelar
   el event loop mientras tanto.
5. `extract_topics_from_image` envía `VISION_PROMPT` pidiendo **JSON estricto**
   `{"title": ..., "topics": [...]}`, le quita fences ```json si vienen, hace
   `json.loads`, valida no-vacío, registra consumo y devuelve tupla; cualquier
   fallo → `None` → mensaje de error amable al usuario.
6. Éxito: confirma lo leído y entra a `research` normal.

---

## 7. Capa de IA — `llm.py`

Función única pública:
```python
generate(prompt: str, *, system: str, images: list[tuple[bytes, str]] | None = None) -> str
```

Dispatch por `config.AI_PROVIDER`:
- `"gemini"` → `_generate_gemini` (SDK propio; imágenes vía
  `types.Part.from_bytes`; `system_instruction` en config; silencia el warning
  AFC del SDK bajando el logger `google_genai` a ERROR).
- `"openrouter"` → `_generate_openai_compatible` (cliente `openai` con
  `base_url` de `OPENAI_BASE_URLS`; imágenes como data-URI base64).
- Otro → `ValueError`. Sin `AI_API_KEY` → `RuntimeError`.

Detalles finos:
- Cliente OpenAI es **singleton** (`_openai_client` global + fábrica perezosa):
  una sola conexión reutilizada por la vida del proceso.
- `content` tipado `str | list[dict[str, Any]]`: string plano cuando no hay
  imágenes (máxima compatibilidad), lista multimodal cuando las hay.
- La función **propaga excepciones**: quién decide qué hacer ante fallo es
  `analyzer` (política de fallback), no el transporte.

Cambiar de proveedor = editar 2-3 líneas de `.env`. Groq existió en esta capa
y se retiró (bloqueo regional desde Venezuela).

---

## 8. Interfaz de Telegram

### Menú inline
`MENU_KEYBOARD` — 5 botones con `callback_data`: `docs`, `uso`, `sync`,
`logs`, `ayuda`. `button(update, ctx)` hace `query.answer()` y enruta por ese
string; cada rama llama a la misma función pura que el comando equivalente
(`docs_text()`, `format_usage()`, …) y edita el mensaje original
(`edit_message_text`) manteniendo el teclado.

### Comandos
| Comando | Función | Fuente de datos |
|---|---|---|
| `/start`, `/help` | `start` | `HELP_TEXT` + menú |
| `/menu` | `menu` → `show_menu` | teclado |
| `/docs` | `docs_command` | `docs_text()` sobre disco real |
| `/sync` | `sync_command` | `sync_documents()` |
| `/uso` | `uso_command` | `format_usage()` |
| `/logs` | `logs_command` | `logs_text()` sobre `bot.log` |

`docs_text()`: `writer.list_months()` recorre años/meses descendente saltando
meses vacíos; muestra máx `MAX_DOCS_MOSTRADOS=12` con tamaño KB y nota
"…y N más". `month_label()` da formato "Agosto 2026".

### Observabilidad — `/logs`
`_recent_error_blocks()` lee `logs/bot.log` (OSError → []), detecta cabeceras
con regex `^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ `, filtra nivel `ERROR`
(campo 3 del split) y agrupa las líneas siguientes (tracebacks sin timestamp,
tope de 40 líneas) como parte del bloque. Devuelve los últimos 10 bloques.
`logs_text()` los renderiza más-recientes-primero dentro de fences ``` hasta
~3500 chars. Sin errores → mensaje verde. **Los errores nunca se envían solos
al chat**: se consultan bajo demanda (decisión de diseño explícita).

### Error handler global — `on_error`
Contrato PTB: recibe `(update, context)` donde `context.error` es la excepción.
Hace `logger.error(..., exc_info=context.error)` → traceback completo al
archivo rotativo. El bot sigue vivo; el usuario ni se entera salvo porque el
comando afectado no respondió.

---

## 9. Sincronización — `syncer.py`

`sync_documents()`:
1. Sin `documentos/` → ceros.
2. `mkdir` del destino (vault).
3. Para cada `*.md` recursivo ordenado: ruta relativa → destino espejo.
4. `_igual(src, dst)`: primero tamaño (`st_size`) — rechazo barato; luego
   **MD5** en chunks de 64 KB. ¿Por qué no fechas? El vault vive en un montaje
   **rclone/GDrive FUSE que no preserva mtimes**; comparar fechas daría falsos
   positivos/negativos. Hash es la única verdad.
5. Distinto → `shutil.copy2`. Contadores `nuevos` / `actualizados`.
6. **Nunca borra** del vault aunque el origen desaparezca (protección
   deliberada contra pérdida accidental).

`sync_text(resultado)` formatea el reporte con destino incluido.

---

## 10. Persistencia y estado

| Archivo | Quién escribe | Formato / política |
|---|---|---|
| `documentos/**.md` | writer | jerárquico año/mes, frontmatter, índice mensual |
| `data/usage.json` | usage | `{"date": "YYYY-MM-DD", "count": N}`; si la fecha difiere de hoy, `_load()` descarta → reset diario automático |
| `logs/bot.log` (+`.1`…`.3`) | logsetup | texto plano, rota a 5 MB, conserva 3 respaldos |
| `.env` | humano | tokens; jamás commiteado |

El contador es **local y aproximado**: el límite real lo impone el proveedor.

---

## 11. Configuración — `config.py`

Resuelve `BASE_DIR` desde la ubicación del propio archivo (independiente del
cwd). Variables (todas con default sensato):

| Variable | Default | Efecto |
|---|---|---|
| `TELEGRAM_TOKEN` | — | requerido |
| `AUTHORIZED_USER_ID` | 0 (=todos) | ID Telegram autorizado |
| `AI_PROVIDER` | gemini | `gemini \| openrouter` (`VALID_PROVIDERS`) |
| `AI_API_KEY` | — | requerida |
| `AI_MODEL` | según proveedor | override puntual |
| `AI_DAILY_LIMIT` | 100 | solo cosmético (/uso) |
| `SEARCH_MAX_RESULTS` | 5 | fuentes por tema |
| `OUTPUT_DIR` / `OBSIDIAN_DIR` / `DATA_DIR` / `LOG_DIR` | rutas del repo/vault | redirigibles (clave para tests) |

Defaults de modelo: `gemini-3.6-flash` · `nvidia/nemotron-nano-12b-v2-vl:free`.
Los catálogos gratuitos rotan; si un modelo muere, cambiar `AI_MODEL`.

---

## 12. Calidad: cómo se prueba este código

Principio: **lógica pura directo; bordes con stubs**.

| Módulo testeado | Estrategia |
|---|---|
| parser, writer, syncer, usage | funciones puras sobre carpetas temporales (`tmp_path`) — nada de mocks |
| searcher | clase `FakeDDGS` con lista de efectos (excepción o datos); `time.sleep` parcheado |
| llm | stubs del SDK: `StubCompletions` captura kwargs del chat; `google.genai.Client` reemplazado por stub que captura model/contents/config |
| analyzer | `generate` y `register_call` monkeyparcheados; se prueban éxito, vacío, excepción y JSON de visión |
| config.validate | combinaciones de env incompleta/inválida |
| bot | fakes `FakeMessage/FakeQuery/FakeChat` (grabadoras de llamadas); handlers async ejecutados con `asyncio.run`; pipeline de investigación parcheado |

Fixtures (`tests/conftest.py`):
- `output_dirs` — redirige `OUTPUT_DIR`/`OBSIDIAN_DIR` de writer y syncer.
- `usage_file` / `write_usage` — contador temporal.
- autouse `sin_log_a_archivo` — desmonta el RotatingFileHandler durante los
  tests (no contaminan tu `bot.log` real).
- En test_bot, autouse además neutraliza `AUTHORIZED_USER_ID=0` (el `.env`
  real no debe filtrarse en las pruebas).

Estado: **91 tests, 97% cobertura con ramas**, ruff (lint+format) y mypy
estrictos en `asistente/` y `tests/`, hooks pre-commit (higiene + ruff).
La suite cazó un bug real: dedup de fuentes solo entre temas, no intra-tema.

Comandos:
```bash
pytest --cov                 # suite + cobertura
ruff check . && ruff format .
mypy asistente/ tests/
pre-commit run --all-files
```

---

## 13. Decisiones técnicas y sus razones (resumen honesto)

- **Polling, no webhook** — uso personal local: cero infraestructura.
- **Secuencial por tema** — simple y protege cuota; el paralelismo
  (`asyncio.gather`) es la Fase 3 del roadmap.
- **MD5, no mtimes** — consecuencia directa del montaje rclone.
- **Fallback en cascada** — búsqueda vacía o IA caída nunca rompen: el
  documento sale con snippets crudos y queda marcado.
- **Capa multi-proveedor** — anti lock-in y portátil de CV; Groq retirado por
  geo-bloqueo, la abstracción hizo el cambio trivial.
- **Errores al archivo, consulta por demanda** — el bot no spamea tracebacks
  al chat; `/logs` es la ventana.
- **Índice regenerado desde disco** — fuente única de verdad = filesystem;
  imposible que el índice mienta.

## 14. Límites actuales (roadmap activo)

Fase 3 pendiente: paralelizar temas, cache SQLite de búsquedas/análisis,
dataclass `SearchResult`, cadena de proveedores con circuit breaker.
Fase 4-5: full-text search (`/buscar`), export PDF, systemd/Docker.

## 15. Orden sugerido de lectura del código

1. `config.py` → 2. `parser.py` → 3. `searcher.py` → 4. `llm.py` →
5. `analyzer.py` → 6. `writer.py` → 7. `syncer.py` → 8. `usage.py` →
9. `logsetup.py` → 10. `bot.py` (el más grande, deja el orquestador para el final).
