# Photographic PBR surface assets

Retrieved from the official Poly Haven public API. The original nine JPEGs were
added on 2026-11-09; twelve more were added on 2026-11-16. All are 1K originals,
verified against official file sizes and MD5. Reproduce the first three sets with
`scripts/fetch-surface-assets.ps1`, and the last four with
`python scripts/fetch-community-assets.py` from the repository root.

| Asset | Runtime use | Source |
| --- | --- | --- |
| asphalt_02 | Road albedo, OpenGL normal, roughness | https://polyhaven.com/a/asphalt_02 |
| concrete_pavement | Community paving albedo, OpenGL normal, roughness | https://polyhaven.com/a/concrete_pavement |
| plastered_wall_02 | Residential/interior wall albedo, OpenGL normal, roughness | https://polyhaven.com/a/plastered_wall_02 |
| leafy_grass | Planted ground albedo, OpenGL normal, roughness | https://polyhaven.com/a/leafy_grass |
| brick_wall_001 | Residential plinth albedo, OpenGL normal, roughness | https://polyhaven.com/a/brick_wall_001 |
| floor_tiles_02 | Kitchen/corridor finish albedo, OpenGL normal, roughness | https://polyhaven.com/a/floor_tiles_02 |
| wood_floor | Entry flooring and timber albedo, OpenGL normal, roughness | https://polyhaven.com/a/wood_floor |

License: CC0 1.0 Universal, https://creativecommons.org/publicdomain/zero/1.0/ .
Poly Haven's license statement: https://polyhaven.com/license .
Only assets are included; no website preview renders or logos are redistributed.
Color maps use sRGB; normal and roughness use linear data. No displacement changes
the authoritative road surface, doorway geometry or walking height.

The application serves all assets locally, with procedural fallback and per-arena
texture ownership. Low graphics quality disables normal/roughness map shading.
The 2026-11-16 files and two community meshes are recorded with SHA-256 in
`../community-real/asset-manifest.json`.
