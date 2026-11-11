/**
 * Lambert conformal conic, the projection Indian atlases use. The same function
 * draws the map (scripts/build-india-map.mjs bakes the outlines with it) and
 * places the pins in the browser, so a pin always lands where the map says.
 * Spherical formulas, as in d3-geo's geoConicConformal.
 */

export interface ProjectionSpec {
  /** central meridian and the two standard parallels, in degrees */
  lon0: number;
  phi0: number;
  phi1: number;
  /** map units per radian, and where the origin lands */
  k: number;
  tx: number;
  ty: number;
}

const RAD = Math.PI / 180;
const tany = (phi: number) => Math.tan((Math.PI / 2 + phi) / 2);

/** Unscaled projection of (longitude, latitude) in degrees; y grows northwards. */
export function conicConformal(lon0: number, phi0: number, phi1: number): (lon: number, lat: number) => [number, number] {
  const y0 = phi0 * RAD;
  const y1 = phi1 * RAD;
  const cy0 = Math.cos(y0);
  const n = y0 === y1 ? Math.sin(y0) : Math.log(cy0 / Math.cos(y1)) / Math.log(tany(y1) / tany(y0));
  const f = (cy0 * Math.pow(tany(y0), n)) / n;
  return (lon, lat) => {
    const lambda = (lon - lon0) * RAD;
    let phi = lat * RAD;
    if (f > 0 ? phi < -Math.PI / 2 + 1e-6 : phi > Math.PI / 2 - 1e-6) phi = f > 0 ? -Math.PI / 2 + 1e-6 : Math.PI / 2 - 1e-6;
    const r = f / Math.pow(tany(phi), n);
    return [r * Math.sin(n * lambda), f - r * Math.cos(n * lambda)];
  };
}

/** (longitude, latitude) -> map units, y growing downwards like SVG. */
export function makeProjection(spec: ProjectionSpec): (lon: number, lat: number) => [number, number] {
  const raw = conicConformal(spec.lon0, spec.phi0, spec.phi1);
  return (lon, lat) => {
    const [x, y] = raw(lon, lat);
    return [spec.tx + spec.k * x, spec.ty - spec.k * y];
  };
}
