/**
 * DataSourceBadges / DataSourcesPanel: render provider chips + the Yahoo-fallback
 * warning + an expandable per-field panel. Pure components (no hooks).
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataSourceBadges, DataSourcesPanel } from "./data-source-badges";
import type { SourceProvenance } from "@/lib/schemas";

const PRIMARY: SourceProvenance[] = [
  { field: "news", provider: "fmp", label: "FMP", role: "primary" },
  { field: "filings", provider: "sec", label: "SEC EDGAR", role: "primary" },
];

const WITH_FALLBACK: SourceProvenance[] = [
  { field: "prices", provider: "yfinance", label: "Yahoo Finance", role: "fallback", fallback_used: true },
];

describe("DataSourceBadges", () => {
  it("renders one chip per provider", () => {
    render(<DataSourceBadges sources={PRIMARY} />);
    expect(screen.getByText("FMP")).toBeInTheDocument();
    expect(screen.getByText("SEC EDGAR")).toBeInTheDocument();
  });

  it("shows the Yahoo-fallback warning only when a fallback was used", () => {
    const { rerender } = render(<DataSourceBadges sources={PRIMARY} />);
    expect(screen.queryByText(/Yahoo fallback/i)).not.toBeInTheDocument();
    rerender(<DataSourceBadges sources={WITH_FALLBACK} />);
    expect(screen.getByText(/Using Yahoo fallback because Massive\/FMP was unavailable/i)).toBeInTheDocument();
  });

  it("renders nothing when there are no sources", () => {
    const { container } = render(<DataSourceBadges sources={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("de-dupes repeated providers into one chip", () => {
    render(
      <DataSourceBadges
        sources={[
          { field: "news", provider: "fmp", label: "FMP", role: "primary" },
          { field: "press", provider: "fmp", label: "FMP", role: "primary" },
        ]}
      />,
    );
    expect(screen.getAllByText("FMP")).toHaveLength(1);
  });
});

describe("DataSourcesPanel", () => {
  it("lists each field's provider + freshness", () => {
    render(
      <DataSourcesPanel
        sources={[{ field: "yield_curve", provider: "treasury", label: "U.S. Treasury", role: "primary", as_of: "2026-06-13" }]}
        warnings={["fmp_key_missing"]}
      />,
    );
    expect(screen.getByText(/Data sources used/i)).toBeInTheDocument();
    expect(screen.getByText("yield_curve")).toBeInTheDocument();
    expect(screen.getByText("U.S. Treasury")).toBeInTheDocument();
    expect(screen.getByText(/fmp_key_missing/)).toBeInTheDocument();
  });
});
