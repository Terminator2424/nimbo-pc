"""Punto de entrada del .exe: sin argumentos abre la ventana; con argumentos funciona como la línea de comandos."""

import sys

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args == ["--tray"]:
        from nimbo.ui import run

        raise SystemExit(run(start_hidden="--tray" in args))
    from nimbo.cli import main

    raise SystemExit(main(args))
