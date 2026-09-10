"""spectro — extractor de absorbancia desde video del espectrofotometro.

El paquete convierte un video de la pantalla del equipo en una serie temporal
absorbancia vs tiempo (CSV). El pipeline completo esta descrito en
``docs/ARQUITECTURA.md``; cada modulo documenta su rol en su propio docstring.

    video -> extract -> runs/<id>/frames/ -> qc -> read -> report -> CSV
"""

__version__ = "1.0.0"
