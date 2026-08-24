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
| Tests | `pytest` | 91 tests, 97% de cobertura |
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
| `AUTHORIZED_USER_ID` | Tu ID: escribirle a [@userinfobot](https://t.me/userinfobot) |
| `OBSIDIAN_DIR` | (opcional) Carpeta de tu vault donde `/sync` copia los docs. Default: `~/GoogleDrive/Obsidian/Notebook/Universidad` |

Para cambiar de proveedor de IA solo editas esas 2-3 líneas en `.env`; el
código no cambia. Los catálogos gratuitos rotan: revisa límites vigentes en la
consola de cada proveedor.

## Uso

```bash
python main.py
```

- `/docs` — lista documentos por mes
- `/sync` — copia incremental de `documentos/` hacia tu vault de Obsidian
  (también con el botón 🔄 Sincronizar del menú)
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

- Texto y fotos del pizarrón (visión multimodal, sin OCR externo)
- Índice mensual auto-regenerado estilo Obsidian (dataview + wikilinks)
- Contador diario de llamadas IA (`/uso`)
- Sincronización incremental al vault (`/sync`)
