"""Hoja de recortes de la ROI de varios fotogramas, para mirarlos a ojo (solo lectura).

    python .claude/skills/diagnose-reading/scripts/crops.py --run img_8110 --out hoja.png \\
        t_0000132.000.jpg t_0000171.250.jpg

Aplica la rotacion de la corrida y el corrimiento de QC de cada fotograma, igual que ``read``.
Cada recorte lleva el nombre y el estado de QC arriba. Sirve para comprobar si un valor
escrito coincide con lo que muestra el display, o si el ultimo digito esta a medio dibujar
(manchas rojizas o trazos partidos).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import argumentos, contexto  # noqa: E402


def main() -> int:
    p = argumentos(__doc__.splitlines()[0])
    p.add_argument("frames", nargs="+", help="nombres de fotograma")
    p.add_argument("--out", required=True, help="PNG de salida (usa una carpeta temporal)")
    p.add_argument("--cols", type=int, default=3, help="columnas de la hoja")
    p.add_argument("--scale", type=int, default=3, help="aumento de cada recorte")
    p.add_argument("--margin", type=int, default=6, help="pixeles de margen alrededor de la ROI")
    args = p.parse_args()
    ctx = contexto(args)

    import cv2
    import numpy as np

    from spectro.imaging import load_frame, shifted

    tiles = []
    for i, nombre in enumerate(args.frames):
        color = load_frame(ctx.frames_dir / nombre, ctx.cfg, color=True)
        roi = shifted(ctx.cfg.roi, ctx.offsets.get(nombre, (0, 0)), color.shape)
        m = args.margin
        recorte = color[max(roi.y - m, 0): roi.y + roi.h + m, max(roi.x - m, 0): roi.x + roi.w + m + 60]
        recorte = cv2.resize(recorte, None, fx=args.scale, fy=args.scale, interpolation=cv2.INTER_CUBIC)
        tile = np.full((recorte.shape[0] + 24, recorte.shape[1], 3), 30, np.uint8)
        tile[24:] = recorte
        cv2.putText(tile, f"#{i}  {nombre[2:-4]}  {ctx.statuses.get(nombre, '?')}", (4, 17),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(tile)
    alto = max(t.shape[0] for t in tiles)
    ancho = max(t.shape[1] for t in tiles)
    filas = (len(tiles) + args.cols - 1) // args.cols
    hoja = np.full((filas * alto, args.cols * ancho, 3), 10, np.uint8)
    for k, t in enumerate(tiles):
        f, c = divmod(k, args.cols)
        hoja[f * alto: f * alto + t.shape[0], c * ancho: c * ancho + t.shape[1]] = t
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(args.out, hoja)
    print(f"hoja de {len(tiles)} recortes -> {args.out} ({hoja.shape[1]}x{hoja.shape[0]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
