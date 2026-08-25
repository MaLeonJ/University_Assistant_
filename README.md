# Asistente Universitario

Bot de Telegram que recibe temarios, investiga cada tema en la web y genera un
documento `.md` en `documentos/`, organizado por fecha, con sincronización a tu
vault de Obsidian. La IA es intercambiable: **Gemini u OpenRouter** con
una sola variable de configuración.

## Formato de mensaje

```
temario corte 1: qué es bases de datos, bases de datos relacionales, modelo E-R
```

## Instalación

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## Calidad

| Herramienta | Comando | Estado |
|---|---|---|
| Tests | `pytest` | 180 tests, 95% de cobertura |
| Lint + formato | `ruff check . && ruff format .` | limpio |
| Tipado | `mypy asistente/ tests/` | estricto |
| Hooks | `pre-commit install` | ruff + higiene de archivos |

Las dependencias están fijadas (`==`) en `pyproject.toml`.

## Documentación

- `docs/ARQUITECTURA.md` — diseño de alto nivel y decisiones
- `docs/FUNCIONAMIENTO-INTERNO.md` — guía exhaustiva: librerías, funciones, flujos y pruebas

## Configuración (.env)

| Variable | Dónde obtenerla |
|---|---|
| `TELEGRAM_TOKEN` | Hablar con [@BotFather](https://t.me/BotFather) → `/newbot` |
| `AI_PROVIDER` | `gemini` (default) u `openrouter` |
| `AI_API_KEY` | Gemini: https://aistudio.google.com/apikey · OpenRouter: https://openrouter.ai/keys |
| `AI_MODEL` | (opcional) Modelo del proveedor; cada uno tiene default |
| `AI_FALLBACK_MODELS` | (opcional) Modelos de respaldo separados por coma; se prueban en orden si el principal falla |
| `AUTHORIZED_USER_ID` | Tu ID: escribirle a [@userinfobot](https://t.me/userinfobot) |
| `OUTPUT_DIR` | (opcional) Carpeta donde se guardan los docs generados. Default: `documentos` |
| `OBSIDIAN_DIR` | (opcional) Carpeta destino de la sync local. Default: `~/GoogleDrive/Obsidian/Notebook/Universidad` |
| `GDRIVE_FOLDER_ID` | (opcional) ID de tu carpeta de Drive (la parte final de su URL) para el botón ☁️ Drive |

Las rutas aceptan valores absolutos, relativos al proyecto o con `~`.
Si falta la configuración de un destino, el bot lo avisa con los pasos a
seguir en lugar de romperse.

Para cambiar de proveedor de IA solo editas esas 2-3 líneas en `.env`; el
código no cambia. Los catálogos gratuitos rotan: revisa límites vigentes en la
consola de cada proveedor.

## Uso

```bash
python main.py     # bot de Telegram
asistente --help   # misma potencia desde la terminal (CLI)
```

### CLI

```bash
pip install -e .   # registra el comando `asistente`

asistente investigar "corte 1: bases de datos, modelo E-R"
asistente buscar entimema silogismo -l 5
asistente exportar pdf          # el más reciente
asistente exportar docx logica  # el mejor match
asistente drive-auth            # autoriza Google Drive y genera data/token.json
asistente uso
asistente stats
```

La CLI reutiliza exactamente los mismos módulos que el bot: lo que generes
por un lado aparece en el otro.

### Google Drive (una sola vez)

```bash
pip install -e ".[drive]"
# 1. Google Cloud Console → habilita «Google Drive API» → credenciales OAuth
#    «Aplicación de escritorio» → descarga como credentials.json (raíz del proyecto)
asistente drive-auth     # 2. abre el navegador y genera data/token.json
# 3. copia credentials.json + data/token.json al servidor
# 4. añade GDRIVE_FOLDER_ID=<ID> al .env del servidor
```

- `/docs` — lista documentos por mes
- `/buscar <términos>` — búsqueda full-text en tu biblioteca (insensible a
  acentos y plurales), ej.: `/buscar ecuaciones diferenciales`
- `/exportar pdf|docx [términos]` — convierte un documento con pandoc y te lo
  envía (el más reciente, o el mejor match de los términos)
- `/stats` — resumen de biblioteca, consumo de IA y cache
- `/sync` — abre un submenu con dos destinos: 💻 **Local** (copia incremental
  a tu vault de Obsidian) y ☁️ **Drive** (sube a tu carpeta de Google Drive
  vía API oficial; nunca borra del destino)
- `/uso` — cuota diaria de llamadas IA con barra de progreso
- `/logs` — últimos errores registrados en `logs/bot.log` (botón 📋 Registros)

## Estructura del proyecto

```
main.py              punto de entrada
asistente/           paquete: bot, parser, searcher, llm, analyzer,
                     writer, syncer, usage, config
documentos/          salida por fecha (año/mes/día_hora_tema.md)
data/                estado runtime (usage.json)
docs/                ARQUITECTURA.md y ejemplos
```

## Features

- Texto y fotos del pizarrón: la IA lee los temas y **eliges con botones** cuáles investigar
- Investigación de todos los temas en paralelo
- Cache SQLite: temas repetidos no gastan cuota de IA
- Fallback de modelos con circuit breaker si el proveedor falla
- Búsqueda full-text propia sobre la biblioteca (FTS5)
- Exportación PDF/DOCX con pandoc
- CLI completa (`asistente`) sobre el mismo pipeline que el bot
- Índice mensual auto-regenerado estilo Obsidian (dataview + wikilinks)
- Contador diario de llamadas IA (`/uso`) e historial (`/stats`)
- Sincronización incremental a Obsidian local **o Google Drive** (`/sync`)
- Mensajes guiados si falta configuración de un destino: nunca se rompe
