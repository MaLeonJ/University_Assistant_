# Guía Completa de Comandos y Scripts para Copiado de Archivos en Terminal

Esta guía reúne de forma estructurada todas las soluciones tratadas sobre cómo copiar/mover archivos entre carpetas mediante comandos de consola y Python, junto con su terminología técnica en inglés.

---

## 1. Copiado Básico en Terminal (`cp`)

El comando fundamental para copiar el contenido de una carpeta a otra en Linux/POSIX es:

```bash
cp /home/leon/GoogleDrive/Obsidian/Notebook/Terminal/Logs/* /home/leon/Documentos/logs_prueba/
```

### Anatomía del Comando (*Anatomy of the Command*)

* **`cp` (Copy Command):** Utilidad estándar en sistemas Unix/Linux para copiar archivos y directorios.
* **Ruta de Origen (*Source Path*):** `/home/leon/GoogleDrive/Obsidian/Notebook/Terminal/Logs/`
* **Comodín (*Wildcard* `*`):** Selecciona todos los archivos contenidos dentro del directorio especificado.
* **Ruta de Destino (*Destination Path*):** `/home/leon/Documentos/logs_prueba/`

---

## 2. Variaciones del Comando de Terminal (*Common Variations*)

### A. Crear la carpeta destino si no existe (*Create Directory on the Fly*)
Crea la carpeta de destino automáticamente usando `mkdir -p` antes de ejecutar la copia:

```bash
mkdir -p /home/leon/Documentos/logs_prueba/ && cp /home/leon/GoogleDrive/Obsidian/Notebook/Terminal/Logs/* /home/leon/Documentos/logs_prueba/
```

### B. Copiar subcarpetas de forma recursiva (*Recursive Copy*)
Agrega la bandera `-r` (*recursive*) para copiar también las carpetas internas y todo su contenido:

```bash
cp -r /home/leon/GoogleDrive/Obsidian/Notebook/Terminal/Logs/* /home/leon/Documentos/logs_prueba/
```

### C. Omitir duplicados / No sobrescribir (*Safe Copy / No-Clobber*)
Usa `-n` (*no-clobber*) para ignorar los archivos que ya existan en la carpeta destino:

```bash
cp -n /home/leon/GoogleDrive/Obsidian/Notebook/Terminal/Logs/* /home/leon/Documentos/logs_prueba/
```

### D. Modo interactivo (*Interactive Mode*)
Usa `-i` (*interactive*) para pedir confirmación manual (`y/n`) antes de sobrescribir cada archivo:

```bash
cp -i /home/leon/GoogleDrive/Obsidian/Notebook/Terminal/Logs/* /home/leon/Documentos/logs_prueba/
```

### E. Sobrescribir solo si el origen es más reciente (*Update Mode*)
Usa `-u` (*update*) para actualizar el archivo de destino únicamente si la versión de origen es más nueva:

```bash
cp -u /home/leon/GoogleDrive/Obsidian/Notebook/Terminal/Logs/* /home/leon/Documentos/logs_prueba/
```

### F. Crear respaldos numerados (*Numbered Backups*)
Genera una copia de respaldo con sufijo numerado (ej. `archivo.txt.~1~`) para los archivos duplicados:

```bash
cp --backup=numbered /home/leon/GoogleDrive/Obsidian/Notebook/Terminal/Logs/* /home/leon/Documentos/logs_prueba/
```

### G. Mover en lugar de copiar (*Move Files*)
Para reemplazar `cp` y transferir los archivos eliminando los originales:

```bash
mv /home/leon/GoogleDrive/Obsidian/Notebook/Terminal/Logs/* /home/leon/Documentos/logs_prueba/
```

---

## 3. Automatización con Script de Python

Si prefieres realizar el copiado de manera programática controlando la existencia de duplicados:

```python
import shutil
from pathlib import Path

# Definir rutas de origen y destino
origen = Path("/home/leon/GoogleDrive/Obsidian/Notebook/Terminal/Logs")
destino = Path("/home/leon/Documentos/logs_prueba")

# Crear la carpeta de destino si no existe
destino.mkdir(parents=True, exist_ok=True)

# Recorrer y copiar los archivos
for archivo in origen.glob("*"):
    if archivo.is_file():
        archivo_destino = destino / archivo.name

        # Evitar sobrescribir si el archivo ya existe
        if archivo_destino.exists():
            print(f"Omitido (ya existe): {archivo.name}")
        else:
            shutil.copy2(archivo, archivo_destino)
            print(f"Copiado: {archivo.name}")
```

* **`shutil.copy2`**: Copia el archivo preservando fechas y metadatos.
* **Para copiar subcarpetas completas en Python**:
  ```python
  shutil.copytree(origen, destino, dirs_exist_ok=True)
  ```

---

## 4. Terminología Técnica en Inglés (*Nomenclature & Glossary*)

### Términos para referirse a comandos de consola

| Término en Inglés | Contexto / Uso |
| :--- | :--- |
| **Command-Line Commands / CLI Commands** | Nombre técnico general (interfaz de línea de comandos). Ideal para documentación. |
| **Shell Commands / Bash Commands** | Específico según el intérprete de comandos utilizado (Unix/Linux/macOS). |
| **Terminal Commands** | Expresión informal empleada en conversaciones o foros. |
| **One-Liner** | Comando complejo combinado en una sola línea de ejecución. |
| **OS / System Commands** | Denominación cuando se ejecutan comandos del SO desde un lenguaje de programación. |

### Tabla de Parámetros de `cp` (*Quick Flag Reference*)

| Flag / Parameter | English Name | Description |
| :--- | :--- | :--- |
| `*` | Wildcard | Selects all files/folders inside the source path. |
| `-r` | Recursive | Includes all subdirectories and their contents. |
| `-n` | No-clobber | Prevents overwriting existing destination files. |
| `-i` | Interactive | Prompts for confirmation before overwriting. |
| `-u` | Update | Copies only if the source file is newer than destination. |
| `--backup=numbered` | Backup | Keeps duplicate files by adding a numerical suffix. |
