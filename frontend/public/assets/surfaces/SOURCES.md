# Photographic PBR surface assets

Retrieved 2026-11-09 from the official Poly Haven public API. All nine JPEGs are
1K originals, verified against the MD5 provided by that API. Reproduce with
`scripts/fetch-surface-assets.ps1` from the repository root.

| Asset | Runtime use | Source |
| --- | --- | --- |
| asphalt_02 | Road albedo, OpenGL normal, roughness | https://polyhaven.com/a/asphalt_02 |
| concrete_pavement | Community paving albedo, OpenGL normal, roughness | https://polyhaven.com/a/concrete_pavement |
| plastered_wall_02 | Residential/interior wall albedo, OpenGL normal, roughness | https://polyhaven.com/a/plastered_wall_02 |

License: CC0 1.0 Universal, https://creativecommons.org/publicdomain/zero/1.0/ .
Poly Haven's license statement: https://polyhaven.com/license .
Only assets are included; no website preview renders or logos are redistributed.
Color maps use sRGB; normal and roughness use linear data. No displacement changes
the authoritative road surface, doorway geometry or walking height.

The application serves all assets locally, with procedural fallback and per-arena
texture ownership. Low graphics quality disables normal/roughness map shading.
