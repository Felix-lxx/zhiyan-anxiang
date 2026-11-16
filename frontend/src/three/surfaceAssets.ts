/** CC0 photography from Poly Haven, downloaded and checksum-verified locally.
 * See public/assets/surfaces/SOURCES.md. No CDN requests occur at runtime. */
export const surfaceAssets = {
  asphalt: 'asphalt_02', paving: 'concrete_pavement', plaster: 'plastered_wall_02',
  grass: 'leafy_grass', brick: 'brick_wall_001', tile: 'floor_tiles_02', wood: 'wood_floor',
} as const

export type PhotographicSurface = keyof typeof surfaceAssets
