import { describe, expect, it } from "vitest";

import { formatPercent } from "@/ui/formatters";

describe("formatPercent", () => {
  it("treats backend confidence values as percentages from 0 to 100", () => {
    expect(formatPercent(80)).toBe("80.0%");
    expect(formatPercent(0)).toBe("0.0%");
    expect(formatPercent(100)).toBe("100.0%");
  });
});
