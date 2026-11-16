import os  # Módulo para interactuar con el SO (directorio actual, PID)
import shlex  # Módulo para parsear comandos respetando comillas y espacios

# Importamos las funciones necesarias desde nuestros módulos auxiliares
from auditoria import auditar, obtener_descripcion_error
from comandos import (OperacionCancelada, cmd_cat, cmd_cd, cmd_cp, cmd_ln, cmd_ls, cmd_mkdir,
                      cmd_mv, cmd_pwd, cmd_rm, cmd_stat)

# Diccionario que mapea cada comando con:
# (función, mínimo de argumentos, máximo de argumentos, formato de uso)
COMANDOS = {
    "ls": (cmd_ls, 0, 1, "[ruta_opcional]"),
    "cd": (cmd_cd, 1, 1, "<carpeta>"),
    "pwd": (cmd_pwd, 0, 0, ""),
    "mkdir": (cmd_mkdir, 1, 1, "<carpeta>"),
    "cp": (cmd_cp, 2, 3, "[-r] <origen> <destino>   (-r: carpetas; verifica con hash)"),
    "mv": (cmd_mv, 2, 2, "<origen> <destino>"),
    "rm": (cmd_rm, 1, 2, "[-r] <ruta>   (-r: carpeta con todo su contenido)"),
    "stat": (cmd_stat, 1, 1, "<ruta>"),
    "ln": (cmd_ln, 2, 3, "[-s] <origen> <enlace>   (duro; -s: simbólico)"),
    "cat": (cmd_cat, 1, 1, "<archivo>"),
}


def mostrar_ayuda() -> None:
    """Imprime el listado de comandos y su sintaxis en consola."""
    print("\nComandos disponibles en MiniShell:")
    for nombre, (_, _, _, formato) in COMANDOS.items():
        print(f"  {nombre:<6} {formato}")
    print("  help   muestra esta ayuda")
    print("  exit   sale de la minishell\n")


def main() -> None:
    """
    Bucle principal REPL (Read-Eval-Print Loop) de la MiniShell.
    Lee comandos, valida argumentos, invoca SysCalls y audita cada resultado.
    """
    print("=========================================================")
    print(f"   MINISHELL DE ARCHIVOS — AUDITORÍA | PID: {os.getpid()}")
    print("=========================================================")
    print("Escribí 'help' para ver la lista de comandos disponibles.\n")

    # Bucle del intérprete de comandos
    while True:
        # 1. READ: Mostramos el prompt interactivo y capturamos el texto del usuario.
        # Se lee FUERA del try principal: si falla la lectura (Ctrl+D o Ctrl+C) hay que SALIR,
        # no seguir pidiendo comandos (antes esto generaba un bucle infinito de errores).
        try:
            prompt = f"minishell [{os.getcwd()}]> "
            entrada = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            # EOF (Ctrl+D) o interrupción (Ctrl+C): cierre ordenado y auditado
            auditar("<fin de entrada>", True, "Sesión finalizada por EOF/Ctrl+C")
            print("\nSaliendo de la MiniShell.")
            break

        # Si la línea está vacía, ignoramos y volvemos a pedir comando
        if not entrada:
            continue

        try:
            # 2. PARSE: Separamos la cadena en comando principal y sus argumentos
            partes = shlex.split(entrada)  # ValueError si hay comillas sin cerrar
            comando = partes[0].lower()
            args = partes[1:]

            # Comando de salida
            if comando in ("exit", "quit"):
                auditar(entrada, True, "Sesión finalizada")
                print("\nSaliendo de la MiniShell.")
                break

            # Comando de ayuda
            if comando == "help":
                mostrar_ayuda()
                auditar(entrada, True, "Ayuda mostrada")
                continue

            # Validación: Verificar si el comando ingresado existe
            if comando not in COMANDOS:
                print(f"[!] Comando desconocido: '{comando}'. Usá 'help'.")
                auditar(entrada, False, "Comando no reconocido")
                continue

            # Extraemos la tupla configurada en el diccionario
            funcion, minimo, maximo, formato = COMANDOS[comando]

            # 3. EXECUTE: Validación de cantidad de parámetros y ejecución de la función
            if not (minimo <= len(args) <= maximo):
                msg_error = f"Uso correcto: {comando} {formato}"
                print(f"[!] {msg_error}\n")
                auditar(entrada, False, msg_error)
                continue

            resultado = funcion(*args)

            # 4. AUDIT: Registro en audit.log tras una ejecución exitosa
            auditar(entrada, True, resultado)
            print(f"[OK] {resultado}\n")

        # El operador respondió "no" a una confirmación: se audita como CANCELADO
        except OperacionCancelada as e:
            auditar(entrada, False, str(e), estado="CANCELADO")
            print(f"[CANCELADO] {e}\n")

        # Captura de excepciones del SO (errores capturados con errno)
        except OSError as e:
            detalle_error = obtener_descripcion_error(e)
            auditar(entrada, False, detalle_error)
            print(f"[ERROR SO] {detalle_error}\n")

        # Captura de errores inesperados (ej: comillas sin cerrar en shlex.split)
        except Exception as e:
            auditar(entrada, False, str(e))
            print(f"[ERROR] {e}\n")


# --- Bloque de ejecución principal ---
if __name__ == "__main__":
    main()
