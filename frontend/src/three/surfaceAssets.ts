/** CC0 photography from Poly Haven, downloaded and checksum-verified locally.
 * See public/assets/surfaces/SOURCES.md. No CDN requests occur at runtime. */
export const surfaceAssets = {
  asphalt: 'asphalt_02', paving: 'concrete_pavement', plaster: 'plastered_wall_02',
} as const

export type PhotographicSurface = keyof typeof surfaceAssets
