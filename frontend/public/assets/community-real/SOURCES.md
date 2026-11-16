# Community context assets

Retrieved 2026-11-16 from the official Poly Haven public API.

| Asset | Included format | Source |
| --- | --- | --- |
| painted_wooden_bench | 1K glTF, binary and local textures | https://polyhaven.com/a/painted_wooden_bench |
| shrub_02 | 1K glTF, binary and local textures | https://polyhaven.com/a/shrub_02 |

License: CC0 1.0 Universal; see `CC0-LICENSE.txt` and
[Poly Haven's license statement](https://polyhaven.com/license).
No website preview renders or logos are redistributed.

Reproduce from the repository root with `python scripts/fetch-community-assets.py`.
The script selects these two meshes and four photographic surface sets, validates
official file sizes and MD5, and records SHA-256 in `asset-manifest.json`.
The manifest covers 22 files, 10,711,166 bytes, including the twelve JPEGs in
`../surfaces/`. It does not duplicate the previously supplied Kenney assets.

Runtime dependencies are local. `communitySite.ts` reserves complete footprints
outside buildings, pedestrian passages, roads, door approaches and assembly points.
`siteAssetFit.ts` fits the complete transformed bounding box with uniform scale
and ground alignment. Low quality hides scanned shrubs; failed mesh loads retain
the basic bench and planted surfaces. These presentation objects do not introduce
new physical obstacles into the authoritative simulation.

Existing trees and parked cars retain their Kenney source and license records in
the corresponding asset directories. The much larger scanned tree candidate was
excluded rather than adding its approximately 95 MB mesh dependency.
