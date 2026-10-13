import { describe, expect, it } from "vitest";
import { fleetRates } from "./live";

describe("fleetRates", () => {
  it("sums each agent's latest report per slot without sawtooth", () => {
    const r = fleetRates({
      a: [{ t: 0, rx: 10, tx: 1 }, { t: 2000, rx: 20, tx: 2 }],
      b: [{ t: 1000, rx: 5, tx: 5 }, { t: 3000, rx: 7, tx: 7 }],
    });
    const last = r[r.length - 1];
    expect(last.rx).toBe(27);
    expect(r.every((p) => p.rx > 0)).toBe(true);
  });
  it("drops stale agents", () => {
    const r = fleetRates({ a: [{ t: 0, rx: 10, tx: 0 }], b: [{ t: 20000, rx: 1, tx: 0 }] });
    expect(r[r.length - 1].rx).toBe(1);
  });
});
