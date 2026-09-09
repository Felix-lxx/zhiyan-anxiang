# Kenney Car Kit 3.1

- Official source: https://kenney.nl/assets/car-kit
- Download: https://kenney.nl/media/pages/assets/car-kit/1a312ec241-1775131960/kenney_car-kit.zip
- License: CC0; original License.txt included.
- Retrieved: 2026-09-06.
- Included: sedan.glb, firetruck.glb, ambulance.glb and their original colormap texture.
- Usage: static community parking / emergency staging props, loaded locally via GLTFLoader; no external request during a drill.
- Local adaptation: uniform scale to 4.2 / 6.2 / 5.2 map units, ground pivot normalized at runtime. Asset geometry unchanged.
- Parking candidates overlapping frozen building bounds or road corridors are skipped.
- These vehicles are visual context; they do not represent implemented mobile rescue agents.

Apartment blocks, charging sheds and road pavement are procedural project models tied to actual frozen dimensions and road edges. Suburban houses were not substituted for the apartment model because their floor layout would not match the continuous evacuation graph.
