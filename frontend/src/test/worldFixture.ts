// A small OpenStreetMap world for Chennai Central tests. The alignment values are the committed metadata.json
// world_alignment; the heritage ring and platform way/397320033 are copied from osm.json (© OpenStreetMap
// contributors, ODbL); the other features are made up where a test needs a particular tag.
import type { TourWorld, TourWorldAlignment, TourWorldFeature } from '../api/types'

export const CHENNAI_ALIGNMENT: TourWorldAlignment = {
  method: 'similarity', scale: 0.855, rotation_deg: -80.104, tx: 11.27, ty: 139.93, residual_m: 6.07,
  pairs: [
    { area: 'platform_12_area', osm: 'way/397320032', osm_ref: '3;4' }, { area: 'platform_11_area', osm: 'way/397320032', osm_ref: '3;4' },
    { area: 'platform_10_area', osm: 'way/397320033', osm_ref: '5;6' }, { area: 'platform_9_area', osm: 'way/397320033', osm_ref: '5;6' },
    { area: 'platform_8_area', osm: 'way/397320034', osm_ref: '7;8' }, { area: 'platform_7_area', osm: 'way/397320034', osm_ref: '7;8' },
  ],
  platform_labels: [
    { area: 'platform_12_area', label: '12', osm_ref: '3;4', label_source: 'station_plan', osm_ref_agrees: false },
    { area: 'platform_11_area', label: '11', osm_ref: '3;4', label_source: 'station_plan', osm_ref_agrees: false },
    { area: 'platform_10_area', label: '10', osm_ref: '5;6', label_source: 'station_plan', osm_ref_agrees: false },
    { area: 'platform_9_area', label: '9', osm_ref: '5;6', label_source: 'station_plan', osm_ref_agrees: false },
    { area: 'platform_8_area', label: '8', osm_ref: '7;8', label_source: 'station_plan', osm_ref_agrees: true },
    { area: 'platform_7_area', label: '7', osm_ref: '7;8', label_source: 'station_plan', osm_ref_agrees: true },
  ],
  // The mirrored alternative is recorded but never applied (ruling R12).
  parity_check: { mirrored_transform: { scale: 0.8549, rotation_deg: -80.981, tx: -116.95, ty: 118.56 } },
  source: 'test', verification: 'pending',
}

export const feature = (id: string, kind: TourWorldFeature['kind'], points: [number, number][], over: Partial<TourWorldFeature> = {}): TourWorldFeature =>
  ({ id, kind, name: null, ref: null, levels: null, height_m: null, layer: null, points, ...over })
export const square = (cx: number, cy: number, r = 5): [number, number][] => [[cx - r, cy - r], [cx + r, cy - r], [cx + r, cy + r], [cx - r, cy + r]]

export const HERITAGE = feature('way/214739119', 'heritage', [[-108.32, -21.38], [-107.7, -25.9], [4.01, -7.32], [3.01, -1.0], [-28.92, -6.2],
  [-28.72, -7.39], [-30.23, -10.61], [-36.41, -8.71], [-36.63, -7.46], [-66.95, -12.4], [-68.18, -5.03], [-75.57, -6.22], [-74.07, -15.98]], { layer: 1 })
export const PLATFORM_5_6 = feature('way/397320033', 'platform', [[-39.75, 30.29], [-30.85, 32.24], [-138.34, 716.6], [-141.29, 715.92],
  [-137.89, 649.33], [-135.17, 623.29], [-118.64, 526.14], [-59.29, 148.3]], { ref: '5;6' })

export function chennaiWorld(features: TourWorldFeature[] = [
  HERITAGE, PLATFORM_5_6,
  feature('b/five', 'building', square(100, 50), { levels: 5, height_m: 40 }),
  feature('b/plain', 'building', square(-150, -80)),
  feature('b/far', 'building', square(900, 900)),
  feature('roof/1', 'roof', square(-60, -40)),
  feature('p/suburban', 'platform', [[60, -60], [80, -60], [80, 0], [60, 0]], { ref: '1A', name: 'Suburban platform' }),
  feature('p/unnamed', 'platform', [[120, -60], [130, -60], [130, 0], [120, 0]]),
  feature('subway/1', 'subway', [[-98, -101], [-95, -63]], { layer: -1 }),
  feature('station/bus', 'station', square(10, -40, 20)),
  feature('rail/long', 'rail', [[-75.5, -283.07], [0, -100], [0, 900]]),
]): TourWorld {
  return {
    attribution: '© OpenStreetMap contributors', licence: 'ODbL-1.0', osm_timestamp: '2026-10-18T14:58:20Z', features,
    alignment: CHENNAI_ALIGNMENT, model: { url: '/api/stations/chennai_central/model.glb', feature_id: 'way/214739119', height_m: 41 },
  }
}
