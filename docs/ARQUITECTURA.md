# Arquitectura — Asistente Universitario

## Visión general

Bot de Telegram que recibe mensajes del usuario (ej. "temario corte 1: qué es bases de datos, bases de datos relacionales..."), los analiza, investiga los temas en la web y genera un documento `.md` con la investigación en la carpeta de Documentos.

**Fase 1 (actual): solo mensajes de texto.**
**Fase 2 (futura): fotos del pizarrón con OCR.**

```
┌─────────┐     ┌──────────────────┐     ┌──────────────┐     ┌────────────┐
│ Telegram │────▶│   Bot (Python)   │────▶│  Búsqueda    │────▶│ Generador  │
│ (chat)  │◀────│  aiogram/PTB     │     │  web         │     │ de .md     │
└─────────┘     └────────┬─────────┘     └──────────────┘     └─────┬──────┘
                         │                                          ▼
                          ▼                                   documentos/
                   ┌──────────────┐                    ├── 2026/
                   │ Gemini API   │                    │   └── 08-agosto/
                   │ (análisis)   │                    │       ├── 00_Índice.md
                   └──────────────┘                    │       └── 22_21-30_temario-corte-1.md
                                                       └── ...
```

## Stack elegido

| Componente | Tecnología | Por qué |
|---|---|---|
| Lenguaje | **Python 3.12** | Ecosistema maduro para bots y NLP |
| Bot de Telegram | **python-telegram-bot** (v21+) | Asíncrono, bien documentado |
| Búsqueda web | **duckduckgo-search** (`ddgs`) | Gratis, sin API key (alternativa: Google Custom Search API) |
| Análisis / resumen | **Capa multi-proveedor** (`llm.py`): Google Gemini u OpenRouter, seleccionable por `.env` | Sin lock-in de proveedor; Gemini ofrece multimodal nativo gratuito y OpenRouter cientos de modelos con una sola clave (API OpenAI-compatible) |

> Elección de IA: el proveedor se cambia editando solo `AI_PROVIDER`, `AI_API_KEY`
> y `AI_MODEL` en `.env`, sin tocar código. OpenRouter expone API
> estándar OpenAI-compatible; Gemini usa su SDK propio (`google-genai`). La capa
> abstrae texto y visión. Groq se descartó: acceso bloqueado desde Venezuela.
> Fallback opcional: LM Studio si no hay internet.
| Salida | Archivos **Markdown** con fecha/hora | Formato pedido |

> Nota: si más adelante quieres resultados de Google "puros", se cambia el módulo de búsqueda por **Google Custom Search JSON API** (requiere API key). El resto del sistema no cambia porque estará aislado en un módulo propio.

## Módulos

```
Asistente Universitario/
├── main.py               # Punto de entrada: python main.py
├── asistente/            # Paquete principal
│   ├── __init__.py
│   ├── bot.py            # Handlers de Telegram y menú
│   ├── parser.py         # Detecta intención: ¿es un temario/lista de temas?
│   ├── searcher.py       # Búsqueda web de cada tema (aislado, reemplazable)
│   ├── llm.py            # Capa multi-proveedor de IA (gemini/openrouter)
│   ├── analyzer.py       # Prompts y síntesis: usa la capa llm
│   ├── writer.py         # Genera el .md en documentos/año/mes/ + índice mensual
│   ├── syncer.py         # Copia incremental de documentos/ al vault de Obsidian
│   ├── usage.py          # Contador diario de llamadas a la IA (data/usage.json)
│   ├── logsetup.py       # Logging a consola + archivo rotativo (logs/bot.log)
│   └── config.py         # Rutas, tokens, modelo y límites (.env)
├── docs/
│   ├── ARQUITECTURA.md
│   └── ejemplo-formato-investigacion.md
├── data/                 # Estado en runtime (usage.json)
├── documentos/           # Salida: documentos generados por fecha
└── requirements.txt
```

### Flujo de un mensaje

1. **Recepción** — `bot.py` recibe el mensaje vía polling (webhook no necesario en local).
2. **Parseo** — `parser.py` extrae título ("temario corte 1") y lista de temas separados por comas o saltos de línea.
3. **Investigación** — `searcher.py` busca cada tema (top N resultados, ej. 3–5 URLs + snippets).
4. **Análisis** — `analyzer.py` envía los resultados al proveedor de IA configurado (vía `llm.py`) para sintetizar una explicación por tema.
5. **Escritura** — `writer.py` crea el documento:
   - Estructura jerárquica por fecha (estilo diario): `documentos/<año>/<MM-mes>/<DD_HH-MM>_<slug>.md`
     ej. `documentos/2026/08-agosto/22_21-30_temario-corte-1.md`
   - Frontmatter YAML (`tags: [universidad, investigacion]`, `fecha`, `hora`) compatible con dataview de Obsidian.
   - Índice mensual `00_Índice.md` por carpeta de mes, regenerado en cada escritura, con bloque `dataview` + wikilinks estilo vault.
   - Encabezado con fecha/hora, título y temas tratados.
   - Sección por tema: explicación + fuentes consultadas.
6. **Respuesta** — el bot confirma al usuario con la ruta del archivo creado.

## Calidad y tooling

- **Empaquetado**: `pyproject.toml` único — dependencias runtime fijadas (`==`),
  extras `dev` (pytest, ruff, mypy, pre-commit), configuración centralizada de
  todas las herramientas. Instalación: `pip install -e ".[dev]"`.
- **Ruff**: lint (E,W,F,I,UP,B,SIM,C4,RUF) + formateo canónico. Los prompts de
  `analyzer.py` quedan exentos del límite de línea (prosa).
- **Mypy**: chequeo estricto sobre `asistente/` y `tests/`. Las invariantes de
  PTB (message/query presentes por filtro) se documentan con `assert`.
- **Pytest**: 91 tests, 97% de cobertura con ramas. Módulos puros testeables
  directamente; searcher/llm/analyzer/bot con stubs (sin red ni claves).
  Fixtures aíslan `documentos/`, vault, `usage.json` y el archivo de log.
- **Pre-commit**: higiene de archivos + ruff-check --fix + ruff-format.

## Decisiones de diseño

- **Polling** en vez de webhook: más simple para uso personal/local.
- **Búsqueda secuencial por tema** con manejo de errores: si falla la búsqueda de un tema, se marca en el doc y continúa con los demás.
- **Gemini con reintentos**: si se agota la cuota gratuita diaria, el documento se genera igual con los snippets crudos de búsqueda (degradación elegante).
- **Capa multi-proveedor** (`llm.py`): `analyzer.py` no sabe qué proveedor usa; cambiar de IA es editar `.env` (decisión orientada a evitar lock-in y a portabilidad del CV).
- **Logging dual con rotación**: consola + `logs/bot.log` (5 MB × 3 respaldos). Los errores de handlers los captura un error handler global que registra el traceback al archivo sin interrumpir el bot ni enviar mensajes al chat.
- **Observabilidad desde el propio bot**: `/logs` o el botón 📋 Registros muestran los últimos bloques de error extraídos del archivo (comando y traceback incluidos), para diagnóstico sin abrir la terminal.
- **Un solo usuario autorizado** (tu chat ID): el bot ignora mensajes de otras personas.
- **Sincronización manual e incremental** (`/sync` o botón 🔄): copia `documentos/` al vault de Obsidian (`OBSIDIAN_DIR`, default `~/GoogleDrive/Obsidian/Notebook/Universidad`). Compara tamaño + hash MD5 porque rclone/GDrive no preserva mtimes. Solo añade/actualiza; nunca borra nada del vault.

## Fase 2 (futuro): fotos del pizarrón

- Handler de fotos en el bot → descarga imagen → se envía **directamente a la IA multimodal** (lee el pizarrón, manuscrito incluido) → el texto extraído entra al mismo flujo desde el paso 2.
- No se necesita Tesseract ni OCR externo. La arquitectura modular permite agregar esto sin tocar `searcher.py` ni `writer.py`. La visión funciona con Gemini (nativa) y con proveedores OpenAI-compatibles (imagen en base64), siempre que el modelo elegido soporte imágenes.

## Configuración (.env)

| Variable | Descripción |
|---|---|
| `TELEGRAM_TOKEN` | Token del bot (@BotFather) |
| `AI_PROVIDER` | Proveedor de IA: `gemini` (default) u `openrouter` |
| `AI_API_KEY` | Clave del proveedor elegido |
| `AI_MODEL` | Modelo específico; si se omite se usa el default del proveedor |
| `AUTHORIZED_USER_ID` | ID de Telegram del único usuario autorizado |
| `SEARCH_MAX_RESULTS` | Resultados web por tema (default 5) |
| `AI_DAILY_LIMIT` | Límite diario de llamadas IA mostrado en `/uso` (default 100) |
| `OUTPUT_DIR` / `OBSIDIAN_DIR` / `DATA_DIR` | Rutas opcionales sobreescribibles |

Models default por proveedor: Gemini `gemini-3.5-flash`, OpenRouter
`nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` (visión). El catálogo gratuito de
OpenRouter rota: verifica los límites vigentes en openrouter.ai/models.
