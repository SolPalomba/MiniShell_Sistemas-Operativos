# MiniShell de archivos con auditoría transaccional

Trabajo Práctico Integrador – Sistemas Operativos (UNAHUR), 2C-2026.
Opción 4 (Intermedio): Sistema de archivos. Lenguaje: Python 3.

**Integrantes:** [AZAME, Mateo] · [PALOMBA, Sol] · [SALVATIERRA, Sofia]
**Docentes:** Ing. Gabriel Esquivel · Prof. Agüero Marisol

## Qué hace

Mini-shell interactiva de mantenimiento de archivos. Usa el módulo `os`, que expone las llamadas al sistema (`os.open`, `os.read`, `os.write`, `os.close`, `os.rename`, `os.unlink`, `os.link`, etc.). Cada comando queda registrado en `audit.log` con fecha y hora, PID de la shell, comando y resultado (OK, FALLO con `errno`, o CANCELADO).

| Comando | Acción |
|---|---|
| `ls [ruta]` | lista con inodo, permisos, enlaces y tamaño |
| `cd`, `pwd`, `mkdir` | navegar y crear carpetas |
| `cp [-r] origen destino` | copia con `os.open/read/write/close`; verifica con SHA-256; `-r` recursiva (copia los enlaces simbólicos como enlaces) |
| `mv origen destino` | `os.rename()`; si es otro sistema de archivos (`EXDEV`), copia + borra |
| `rm [-r] ruta` | elimina archivo o carpeta (`-r` con confirmación) |
| `ln [-s] origen nuevo` | enlace duro o simbólico |
| `stat ruta`, `cat archivo` | metadatos del inodo y contenido |
| `help`, `exit` | ayuda y salida |

Precondiciones: existencia del origen, no sobrescribir un destino existente, origen distinto del destino, carpeta no copiada dentro de sí misma y captura de errores de permisos.

## Archivos

| Archivo | Función |
|---|---|
| `main.py` | bucle principal de la shell y tabla de comandos |
| `comandos.py` | implementación de los comandos y sus precondiciones |
| `auditoria.py` | escritura de `audit.log` y traducción de errores a `errno` |

## Ejecutar

Requiere Python 3 en Linux. No usa librerías externas.

```bash
python3 main.py
```

Los nombres con espacios se escriben entre comillas. Cada módulo tiene pruebas propias: `python3 comandos.py` y `python3 auditoria.py`.

## Ejemplo de `audit.log`

```
2026-11-16T12:43:52 | PID 160 | cp a.txt b.txt | OK (Copiado mediante descriptores de archivo: a.txt -> b.txt)
2026-11-16T12:43:52 | PID 160 | cp a.txt b.txt | FALLO (errno=17 (EEXIST): El archivo destino ya existe: b.txt)
2026-11-16T12:43:52 | PID 160 | rm -r carpeta | CANCELADO (Borrado cancelado: carpeta)
```

## Limitaciones

No hay comando de restauración desde el log.

## Video demostrativo
(https://drive.google.com/file/d/1xuFagLgClJnxgeBBMv0JenoHf3tRZTHx/view?usp=sharing)
