import { describe, expect, it } from "vitest";
import { fmtBps, fmtBpsShort, fmtBytes, fmtDuration, fmtMs } from "./format";

describe("format", () => {
  it("formats bit rates", () => {
    expect(fmtBps(930_150_000)).toBe("930.15 Mbit/s");
    expect(fmtBps(15.3e9)).toBe("15.30 Gbit/s");
    expect(fmtBps(512)).toBe("512 bit/s");
    expect(fmtBps(null)).toBe("—");
    expect(fmtBpsShort(2_500_000)).toBe("2.5M");
  });
  it("formats bytes, durations, latency", () => {
    expect(fmtBytes(1536)).toBe("1.5 KiB");
    expect(fmtDuration(90061)).toBe("1d 1h");
    expect(fmtMs(0.189)).toBe("189 µs");
    expect(fmtMs(11.525)).toBe("11.5 ms");
    expect(fmtMs(2.238)).toBe("2.24 ms");
  });
});
