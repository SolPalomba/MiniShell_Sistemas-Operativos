import errno  # Módulo para mapear códigos de error numéricos del SO a nombres (ej: ENOENT -> 2)
import os  # Módulo para interactuar con las llamadas al sistema operativo (SysCalls)
from datetime import datetime  # Para obtener la fecha y hora actual en los registros de auditoría

# Ruta ABSOLUTA del log, fijada al iniciar: así, aunque el operador use "cd", el registro sigue
# escribiéndose siempre en el mismo archivo (el de la carpeta desde donde se lanzó la shell).
LOG_PATH = os.path.abspath("audit.log")


def auditar(comando: str, exito: bool, detalle: str = "", estado: str = "") -> None:
    """
    Registra cada operación ejecutada en el archivo audit.log usando SysCalls directas.
    
    Recibe: el comando ingresado (str), si fue exitoso (bool), un detalle opcional (str)
    y, opcionalmente, un estado propio (por ejemplo "CANCELADO") que reemplaza a OK/FALLO.
    Usa la bandera O_APPEND para garantizar que la escritura sea atómica en el Kernel.
    """
    # Obtenemos la fecha y hora actual formateada en texto (ISO 8601 con precisión de segundos)
    timestamp = datetime.now().isoformat(timespec="seconds")
    
    # Determinamos el estado según el valor booleano
    estado = estado or ("OK" if exito else "FALLO")
    
    # Construimos la línea que se guardará en el log junto con el PID del proceso actual (os.getpid())
    linea_log = f"{timestamp} | PID {os.getpid()} | {comando} | {estado} ({detalle})\n"

    # SysCall os.open: Abre el archivo en modo solo escritura (O_WRONLY), lo crea si no existe (O_CREAT)
    # y posiciona el puntero siempre al final (O_APPEND). Los permisos 0o644 son lectura/escritura para el dueño.
    fd = os.open(LOG_PATH, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    
    try:
        # SysCall os.write: Escribe los bytes codificados en UTF-8 directamente a través del descriptor (fd)
        os.write(fd, linea_log.encode("utf-8"))
    finally:
        # SysCall os.close: Cierra el descriptor de archivo para liberar el recurso en la tabla del Kernel
        os.close(fd)


def obtener_descripcion_error(error: OSError) -> str:
    """
    Convierte una excepción OSError en un texto claro indicando el número de errno.
    
    Recibe: la excepción OSError capturada.
    Devuelve: una cadena formateada con el código errno y su significado.
    """
    # errno.errorcode nos da el nombre en texto del código de error (ej: 2 -> ENOENT)
    codigo_nombre = errno.errorcode.get(error.errno, "ERR_UNKNOWN")
    
    # Devolvemos el mensaje formateado con el número de error y la descripción del SO
    return f"errno={error.errno} ({codigo_nombre}): {error.strerror}"


# --- Bloque de prueba ---
# Este código solo se ejecuta si corremos "python3 auditoria.py" directamente
if __name__ == "__main__":
    print("Ejecutando pruebas unitarias para el módulo de auditoría...")

    # Prueba 1: Auditar un evento exitoso
    auditar("cp archivo1.txt archivo2.txt", True, "Copiado correctamente")
    print("  [✓] Prueba 1: Registro de éxito escrito en audit.log")

    # Prueba 2: Auditar un evento fallido
    auditar("rm archivo_inexistente.txt", False, "errno=2 (ENOENT): No tal archivo o directorio")
    print("  [✓] Prueba 2: Registro de fallo escrito en audit.log")

    # Prueba 3: Formatear un error de OSError simulado
    error_simulado = OSError(errno.ENOENT, "No existe el archivo especificado")
    desc = obtener_descripcion_error(error_simulado)
    print(f"  [✓] Prueba 3: Descripción de error capturada -> {desc}")

    print("\nPruebas finalizadas. Podés revisar el contenido generado en 'audit.log'.")