import errno  # Módulo con constantes numéricas de errores del sistema (ENOENT, EEXIST, etc.)
import hashlib  # Hash SHA-256 para verificar la integridad de las copias
import os  # Módulo para llamadas directas al sistema operativo (SysCalls de archivos e inodos)
import stat  # Constantes para reconocer el tipo de archivo (S_ISDIR, S_ISLNK, S_ISREG)
import sys  # Para vaciar la salida estándar antes de escribir (cmd_cat)

TAMANO_BLOQUE = 64 * 1024  # Tamaño del buffer de lectura/escritura (64 KB)


def _resolver_destino(origen: str, destino: str) -> str:
    """
    Si el destino es un directorio existente, el archivo se coloca ADENTRO del mismo
    (igual que el cp/mv reales: 'cp a.txt carpeta' -> 'carpeta/a.txt').
    """
    if os.path.isdir(destino):
        return os.path.join(destino, os.path.basename(os.path.normpath(origen)))
    return destino


class OperacionCancelada(Exception):
    """El operador respondió 'no' a una confirmación (se registra como CANCELADO)."""


def _confirmar(pregunta: str) -> bool:
    """Pide confirmación por consola. Cualquier respuesta distinta de 's'/'si' cuenta como NO."""
    try:
        respuesta = input(f"  {pregunta} (s/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return respuesta in ("s", "si", "sí")


def _hash_archivo(ruta: str) -> str:
    """SHA-256 del contenido de un archivo, leído con os.open / os.read / os.close."""
    h = hashlib.sha256()
    fd = os.open(ruta, os.O_RDONLY)
    try:
        while True:
            bloque = os.read(fd, TAMANO_BLOQUE)
            if not bloque:
                break
            h.update(bloque)
    finally:
        os.close(fd)
    return h.hexdigest()


def _copiar_archivo(origen: str, destino: str) -> str:
    """
    Copia el contenido de un archivo usando SysCalls: open, read, write, close.
    Función auxiliar usada por cmd_cp y por cmd_mv (cuando rename no alcanza).
    Al terminar compara el hash SHA-256 del origen y de la copia (integridad).
    Devuelve el hash (hexadecimal) de la copia.
    """
    destino_creado = False
    # SysCall os.open: Abre el origen en modo solo lectura (O_RDONLY)
    fd_in = os.open(origen, os.O_RDONLY)
    try:
        # Obtenemos los permisos originales del archivo mediante os.fstat sobre el descriptor
        modo_permisos = os.fstat(fd_in).st_mode & 0o777

        # SysCall os.open: Crea el destino para escritura (O_WRONLY | O_CREAT).
        # O_EXCL garantiza que si el archivo se creó justo antes de abrirlo, la llamada falle atómicamente.
        fd_out = os.open(destino, os.O_WRONLY | os.O_CREAT | os.O_EXCL, modo_permisos)
        destino_creado = True
        print(f"  [fd] origen={fd_in}  destino={fd_out}")
        try:
            # Bucle de copia por bloques de bytes
            while True:
                # SysCall os.read: Lee hasta TAMANO_BLOQUE bytes desde la posición actual del puntero
                bloque = os.read(fd_in, TAMANO_BLOQUE)

                # Si os.read devuelve 0 bytes, alcanzamos el Fin de Archivo (EOF)
                if not bloque:
                    break

                # SysCall os.write: puede escribir MENOS bytes de los pedidos (escritura parcial),
                # por eso repetimos hasta haber escrito todo el bloque.
                vista = memoryview(bloque)
                while vista:
                    escritos = os.write(fd_out, vista)
                    vista = vista[escritos:]
        finally:
            # Cierra el descriptor del archivo destino
            os.close(fd_out)

        # Verificación de integridad: el hash de la copia tiene que coincidir con el del origen
        hash_origen = _hash_archivo(origen)
        hash_copia = _hash_archivo(destino)
        if hash_origen != hash_copia:
            raise OSError(errno.EIO, f"La copia no coincide con el origen (hash distinto): {destino}")
        print(f"  [hash SHA-256] {hash_copia[:16]}...  -> integridad OK")
        return hash_copia
    except OSError:
        # Si algo falló a mitad de camino no dejamos una copia incompleta
        if destino_creado:
            try:
                os.unlink(destino)
            except OSError:
                pass
        raise
    finally:
        # Cierra el descriptor del archivo origen
        os.close(fd_in)


def _copiar_ruta(origen: str, destino: str) -> int:
    """
    Copia un archivo, un enlace simbólico o (recursivamente) una carpeta.
    Los enlaces simbólicos se copian COMO ENLACES (no se copia el archivo al que apuntan).
    Devuelve la cantidad de elementos copiados.
    """
    st = os.lstat(origen)  # lstat: no sigue enlaces simbólicos

    if stat.S_ISLNK(st.st_mode):
        objetivo = os.readlink(origen)
        os.symlink(objetivo, destino)
        print(f"  [enlace simbólico] {destino} -> {objetivo}")
        return 1

    if stat.S_ISDIR(st.st_mode):
        # Se crea con permisos de escritura para poder llenarla; al final se le ponen los originales
        os.mkdir(destino, 0o700)
        total = 1
        for nombre in sorted(os.listdir(origen)):
            total += _copiar_ruta(os.path.join(origen, nombre), os.path.join(destino, nombre))
        os.chmod(destino, stat.S_IMODE(st.st_mode))
        return total

    if stat.S_ISREG(st.st_mode):
        _copiar_archivo(origen, destino)
        return 1

    raise OSError(errno.ENOTSUP, f"Tipo de archivo no soportado: {origen}")


def _borrar_rec(ruta: str) -> None:
    """Borra un archivo, un enlace o una carpeta con todo su contenido (primero los hijos, al final la carpeta)."""
    if os.path.isdir(ruta) and not os.path.islink(ruta):
        for nombre in os.listdir(ruta):
            _borrar_rec(os.path.join(ruta, nombre))
        os.rmdir(ruta)
    else:
        os.unlink(ruta)


def cmd_ls(ruta: str = ".") -> str:
    """
    Muestra el contenido de un directorio junto con inodo, permisos, nlink y tamaño.

    Recibe: la ruta a listar (str, por defecto el directorio actual ".").
    Devuelve: un resumen en texto de la cantidad de elementos listados.
    Lanza: OSError (ENOENT) si la ruta no existe.
    """
    # lexists (y no exists): también reconoce enlaces simbólicos rotos como entradas válidas
    if not os.path.lexists(ruta):
        raise OSError(errno.ENOENT, f"No existe la ruta: {ruta}")

    # Si es un directorio obtenemos la lista de nombres; si es un archivo, usamos solo su nombre
    # (os.listdir lanza PermissionError / EACCES si no tenemos permiso de lectura sobre el directorio)
    es_directorio = os.path.isdir(ruta)
    archivos = os.listdir(ruta) if es_directorio else [ruta]

    # Imprimimos la cabecera de la tabla formateada
    print(f"\n{'INODO':>10} {'PERMISOS':<11} {'NLINK':>6} {'TAMAÑO':>10} NOMBRE")
    print("-" * 55)

    # Recorremos cada elemento de forma ordenada
    for nombre in sorted(archivos):
        # Construimos la ruta completa para consultar sus metadatos
        ruta_completa = os.path.join(ruta, nombre) if es_directorio else nombre

        # SysCall os.lstat: Obtiene la estructura stat del inodo (sin seguir enlaces simbólicos)
        st = os.lstat(ruta_completa)

        # Convertimos el modo de permisos a formato octal (ej: 0o100644 -> '0644')
        permisos = oct(st.st_mode)[-4:]

        # Si es un enlace simbólico, mostramos a dónde apunta (readlink)
        if os.path.islink(ruta_completa):
            nombre = f"{nombre} -> {os.readlink(ruta_completa)}"

        # Imprimimos el número de inodo (st_ino), permisos, contador de enlaces (st_nlink) y tamaño (st_size)
        print(f"{st.st_ino:>10} {permisos:<11} {st.st_nlink:>6} {st.st_size:>10} {nombre}")

    print("-" * 55)
    return f"{len(archivos)} elementos listados"


def cmd_cp(*args: str) -> str:
    """
    Copia un archivo (o una carpeta con -r) usando llamadas al sistema de bajo nivel:
    os.open, os.read, os.write y os.close. Verifica la copia con un hash SHA-256.

    Uso: cp [-r] <origen> <destino>
    Devuelve: mensaje confirmando la copia por descriptores.
    Lanza: OSError según la falla (ENOENT, EISDIR, EEXIST, EINVAL, EACCES).
    """
    args = list(args)
    recursivo = bool(args) and args[0] == "-r"
    if recursivo:
        args.pop(0)
    if len(args) != 2:
        raise OSError(errno.EINVAL, "Uso: cp [-r] <origen> <destino>")
    origen, destino = args

    # Precondición 1: El origen debe existir
    if not os.path.exists(origen):
        raise OSError(errno.ENOENT, f"El archivo origen no existe: {origen}")

    # Precondición 2: Una carpeta solo se copia con -r
    es_carpeta = os.path.isdir(origen)
    if es_carpeta and not recursivo:
        raise OSError(errno.EISDIR, f"El origen es un directorio (usá cp -r): {origen}")

    # Precondición 3: Permiso de lectura sobre el origen (se informa antes de intentar abrir)
    permisos = os.R_OK | os.X_OK if es_carpeta else os.R_OK
    if not os.access(origen, permisos):
        raise OSError(errno.EACCES, f"Sin permiso de lectura sobre el origen: {origen}")

    # Si el destino es una carpeta existente, copiamos adentro de ella
    destino = _resolver_destino(origen, destino)

    # Una carpeta no puede copiarse dentro de sí misma (la copia no terminaría nunca)
    if es_carpeta:
        real_origen, real_destino = os.path.realpath(origen), os.path.realpath(destino)
        if real_destino == real_origen or real_destino.startswith(real_origen + os.sep):
            raise OSError(errno.EINVAL, f"No se puede copiar una carpeta dentro de sí misma: {origen}")

    # Precondición 4: Evitar sobreescritura accidental si el destino ya existe
    # (lexists: también detecta un enlace simbólico en ese lugar, aunque esté roto)
    if os.path.lexists(destino):
        # Caso especial: origen y destino son el MISMO inodo (mismo archivo o enlace duro)
        if os.path.exists(destino) and os.path.samefile(origen, destino):
            raise OSError(errno.EINVAL, f"Origen y destino son el mismo archivo (mismo inodo): {origen}")
        raise OSError(errno.EEXIST, f"El archivo destino ya existe: {destino}")

    try:
        total = _copiar_ruta(origen, destino)
    except OSError:
        # Una copia recursiva fallida no debe dejar una carpeta a medio copiar
        if es_carpeta and os.path.lexists(destino):
            try:
                _borrar_rec(destino)
            except OSError:
                pass
        raise
    if es_carpeta:
        return f"Carpeta copiada recursivamente ({total} elementos): {origen} -> {destino}"
    return f"Copiado mediante descriptores de archivo: {origen} -> {destino}"


def cmd_mv(origen: str, destino: str) -> str:
    """
    Renombra o mueve una entrada de directorio a través de la llamada al sistema rename(2).
    Si origen y destino están en filesystems distintos (EXDEV), rename no puede y se
    hace copia + borrado del origen.

    Recibe: ruta origen (str) y ruta destino (str o directorio).
    Devuelve: mensaje confirmando el movimiento.
    Lanza: OSError (ENOENT, EEXIST, EACCES).
    """
    # Verificamos que el origen exista (lexists: acepta también enlaces simbólicos rotos)
    if not os.path.lexists(origen):
        raise OSError(errno.ENOENT, f"El origen no existe: {origen}")

    # Si el destino es una carpeta existente, movemos adentro de ella
    destino = _resolver_destino(origen, destino)

    # Verificamos que el destino no exista previamente
    if os.path.lexists(destino):
        raise OSError(errno.EEXIST, f"El destino ya existe: {destino}")

    inodo_antes = os.lstat(origen).st_ino
    try:
        # SysCall os.rename: Modifica la entrada de directorio apuntando al MISMO inodo (no copia bloques)
        os.rename(origen, destino)
        inodo_despues = os.lstat(destino).st_ino
        return f"Renombrado con rename(2): inodo antes={inodo_antes}, después={inodo_despues} (el mismo): {origen} -> {destino}"
    except OSError as e:
        # EXDEV: "cross-device link". Un inodo solo existe dentro de UN filesystem,
        # así que mover entre dos filesystems obliga a copiar los datos y borrar el original.
        if e.errno != errno.EXDEV:
            raise

    print("  [rename] falló con EXDEV: otro sistema de archivos. Se hace copia + borrado.")
    try:
        _copiar_ruta(origen, destino)
    except OSError:
        if os.path.lexists(destino):
            _borrar_rec(destino)  # no dejar una copia a medias
        raise
    _borrar_rec(origen)
    return f"Movido entre filesystems (EXDEV): copia + unlink, inodo NUEVO ({os.lstat(destino).st_ino}): {origen} -> {destino}"


def cmd_rm(*args: str) -> str:
    """
    Elimina un archivo con la SysCall unlink(2), o una carpeta con rmdir(2).
    Con -r elimina la carpeta y todo su contenido (pide confirmación).

    Uso: rm [-r] <ruta>
    Lanza: OSError (ENOENT, ENOTEMPTY, EACCES) y OperacionCancelada si el operador responde que no.
    """
    args = list(args)
    recursivo = bool(args) and args[0] == "-r"
    if recursivo:
        args.pop(0)
    if len(args) != 1:
        raise OSError(errno.EINVAL, "Uso: rm [-r] <ruta>")
    ruta = args[0]

    # lexists: permite eliminar también enlaces simbólicos rotos
    if not os.path.lexists(ruta):
        raise OSError(errno.ENOENT, f"No existe la ruta: {ruta}")

    # Un enlace simbólico a un directorio se borra con unlink (NO con rmdir): se borra el link, no el destino
    if os.path.isdir(ruta) and not os.path.islink(ruta):
        if recursivo:
            if not _confirmar(f"Se borrará '{ruta}' y TODO su contenido. ¿Seguro?"):
                raise OperacionCancelada(f"Borrado cancelado: {ruta}")
            _borrar_rec(ruta)
            return f"Carpeta eliminada con todo su contenido: {ruta}"
        # SysCall os.rmdir: Elimina un directorio vacío (si tiene contenido -> ENOTEMPTY)
        os.rmdir(ruta)
        return f"Carpeta vacía eliminada: {ruta}"

    st = os.lstat(ruta)
    # SysCall os.unlink: Remueve el enlace del nombre al inodo y decrementa st_nlink en 1.
    # Los bloques de datos se liberan recién cuando nlink llega a 0 y nadie lo tiene abierto.
    os.unlink(ruta)
    if st.st_nlink == 1:
        estado = "0 enlaces: el kernel libera el inodo y los bloques si nadie lo tiene abierto"
    else:
        estado = "el inodo sigue vivo"
    return f"Eliminado {ruta}: nlink del inodo {st.st_ino}: {st.st_nlink} -> {st.st_nlink - 1} ({estado})"


def cmd_stat(ruta: str) -> str:
    """
    Muestra en pantalla los metadatos de bajo nivel almacenados en el inodo del archivo.

    Recibe: la ruta del archivo (str).
    Devuelve: resumen del inodo y nlink.
    Lanza: OSError (ENOENT).
    """
    # Verificamos la existencia de la ruta (lexists: también enlaces simbólicos rotos)
    if not os.path.lexists(ruta):
        raise OSError(errno.ENOENT, f"No existe el archivo: {ruta}")

    # SysCall os.lstat: Obtiene la estructura stat directamente del Kernel
    st = os.lstat(ruta)
    print(f"\n[METADATOS DE INODO] {ruta}")
    print(f"  • Número de Inodo : {st.st_ino}")
    print(f"  • Enlaces (nlink) : {st.st_nlink}")
    print(f"  • Tamaño en bytes : {st.st_size}")
    print(f"  • Permisos octales: {oct(st.st_mode)[-4:]}")
    print(f"  • UID / GID       : {st.st_uid} / {st.st_gid}")
    return f"Inodo {st.st_ino}, nlink {st.st_nlink}"


def cmd_ln(*args: str) -> str:
    """
    Crea un ENLACE DURO (nueva entrada de directorio que apunta al MISMO inodo) o,
    con -s, un ENLACE SIMBÓLICO (un archivo especial con su propio inodo que guarda una ruta).
    Sirve para demostrar el conteo de referencias (nlink) al combinarlo con stat y rm.

    Uso: ln [-s] <origen> <enlace>
    Lanza: OSError (ENOENT, EEXIST, EPERM si el origen es un directorio).
    """
    args = list(args)
    simbolico = bool(args) and args[0] == "-s"
    if simbolico:
        args.pop(0)
    if len(args) != 2:
        raise OSError(errno.EINVAL, "Uso: ln [-s] <origen> <enlace>")
    origen, enlace = args

    if os.path.lexists(enlace):
        raise OSError(errno.EEXIST, f"El enlace ya existe: {enlace}")

    if simbolico:
        # SysCall os.symlink: crea un archivo nuevo (inodo propio) cuyo contenido es la ruta de destino
        os.symlink(origen, enlace)
        return f"Enlace simbólico creado: {enlace} -> {origen} (inodo propio {os.lstat(enlace).st_ino})"

    if not os.path.lexists(origen):
        raise OSError(errno.ENOENT, f"El origen no existe: {origen}")
    # SysCall os.link: crea otra entrada de directorio al mismo inodo y hace st_nlink += 1
    os.link(origen, enlace)
    return f"Enlace duro creado: {enlace} -> inodo {os.lstat(origen).st_ino}, nlink = {os.lstat(origen).st_nlink}"


def cmd_mkdir(ruta: str) -> str:
    """Crea una carpeta con la SysCall mkdir(2). Lanza OSError (EEXIST, ENOENT, EACCES)."""
    os.mkdir(ruta, 0o755)
    return f"Carpeta creada: {ruta}"


def cmd_cd(ruta: str) -> str:
    """Cambia el directorio actual del proceso con chdir(2). Lanza OSError (ENOENT, ENOTDIR, EACCES)."""
    os.chdir(ruta)
    return f"Directorio actual: {os.getcwd()}"


def cmd_pwd() -> str:
    """Devuelve el directorio actual (getcwd)."""
    return os.getcwd()


def cmd_cat(ruta: str) -> str:
    """Muestra el contenido de un archivo, leyéndolo con os.open / os.read / os.close."""
    fd = os.open(ruta, os.O_RDONLY)
    total = 0
    try:
        while True:
            bloque = os.read(fd, TAMANO_BLOQUE)
            if not bloque:
                break
            total += len(bloque)
            sys.stdout.write(bloque.decode("utf-8", errors="replace"))
    finally:
        os.close(fd)
    sys.stdout.flush()
    return f"{total} bytes leídos de {ruta}"


# --- Bloque de prueba ---
# Este código solo se ejecuta si corremos "python3 comandos.py" directamente
if __name__ == "__main__":
    print("Ejecutando pruebas unitarias para el módulo de comandos...")

    archivo_test = "test_origen.txt"
    archivo_copia = "test_destino.txt"
    archivo_renombrado = "test_renombrado.txt"
    archivo_enlace = "test_enlace.txt"

    # Limpieza previa de pruebas anteriores
    for f in [archivo_test, archivo_copia, archivo_renombrado, archivo_enlace]:
        if os.path.lexists(f):
            os.unlink(f)

    # 1. Creamos un archivo de prueba con SysCalls
    fd = os.open(archivo_test, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    os.write(fd, b"Texto de prueba para comprobar llamadas al sistema.\n")
    os.close(fd)
    print(f"  [✓] Archivo temporal '{archivo_test}' creado.")

    # 2. Prueba cmd_stat
    print("\n--- Probando cmd_stat ---")
    res_stat = cmd_stat(archivo_test)
    print(f"  [✓] Resultado stat: {res_stat}")

    # 3. Prueba cmd_cp
    print("\n--- Probando cmd_cp ---")
    res_cp = cmd_cp(archivo_test, archivo_copia)
    print(f"  [✓] Resultado cp: {res_cp}")

    # 4. Prueba cmd_ls
    print("\n--- Probando cmd_ls ---")
    res_ls = cmd_ls(".")
    print(f"  [✓] Resultado ls: {res_ls}")

    # 5. Prueba cmd_mv
    print("\n--- Probando cmd_mv ---")
    res_mv = cmd_mv(archivo_copia, archivo_renombrado)
    print(f"  [✓] Resultado mv: {res_mv}")

    # 6. Prueba cmd_ln + rm: el contador de enlaces sube y baja, los datos siguen vivos
    print("\n--- Probando cmd_ln y conteo de referencias ---")
    print(f"  [✓] {cmd_ln(archivo_test, archivo_enlace)}")
    cmd_rm(archivo_test)
    print(f"  [✓] Tras rm del original: {cmd_stat(archivo_enlace)} (los datos siguen accesibles)")

    # 7. Prueba cmd_rm
    print("\n--- Probando cmd_rm ---")
    res_rm1 = cmd_rm(archivo_enlace)
    res_rm2 = cmd_rm(archivo_renombrado)
    print(f"  [✓] Resultado rm (enlace): {res_rm1}")
    print(f"  [✓] Resultado rm (renombrado): {res_rm2}")

    print("\nPruebas unitarias de comandos completadas con éxito.")
