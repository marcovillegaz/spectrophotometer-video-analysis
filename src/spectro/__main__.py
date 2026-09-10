"""Entrypoint del paquete: ``python -m spectro <comando>``.

Delega en :func:`spectro.cli.main`, que define los subcomandos.
"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
