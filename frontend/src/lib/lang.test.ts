import { describe, expect, it } from "vitest";
import { hasCjk } from "./lang";

describe("hasCjk", () => {
  it("detects a Chinese question", () => {
    expect(hasCjk("我的组合风险高吗？")).toBe(true);
  });

  it("detects a short mixed message with enough CJK", () => {
    expect(hasCjk("NVDA 怎么样")).toBe(true);
  });

  it("stays false for English", () => {
    expect(hasCjk("How risky is my portfolio?")).toBe(false);
  });

  it("ignores a single stray CJK char (needs ≥2)", () => {
    expect(hasCjk("buy NVDA 吗")).toBe(false);
  });

  it("needs CJK to be ≥20% of the non-space characters", () => {
    expect(
      hasCjk("please analyze the portfolio risk profile carefully 风险"),
    ).toBe(false);
  });

  it("returns false for empty input", () => {
    expect(hasCjk("")).toBe(false);
  });
});
