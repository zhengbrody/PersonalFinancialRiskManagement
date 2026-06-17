import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const apiFetchMock = vi.fn();
vi.mock("@/lib/api", () => ({ apiFetch: (...a: unknown[]) => apiFetchMock(...a) }));
const trackMock = vi.fn();
vi.mock("@/lib/analytics", () => ({ track: (...a: unknown[]) => trackMock(...a) }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ accessToken: "jwt" }) }));

import { ReportExportButton } from "./report-export-button";

beforeEach(() => {
  apiFetchMock.mockReset();
  trackMock.mockReset();
  // jsdom lacks these — stub for the open-in-new-tab flow.
  globalThis.URL.createObjectURL = vi.fn(() => "blob:report");
  globalThis.URL.revokeObjectURL = vi.fn();
  window.open = vi.fn();
});

describe("ReportExportButton", () => {
  it("posts the payload, opens the report, and tracks ONLY the kind", async () => {
    apiFetchMock.mockResolvedValue({
      html: "<!doctype html><html></html>",
      input_hash: "h",
      as_of: "2026-06-16",
      kind: "portfolio",
    });
    const user = userEvent.setup();
    render(<ReportExportButton kind="portfolio" payload={{ report: { x: 1 } }} />);

    await user.click(screen.getByRole("button", { name: /export report/i }));

    await waitFor(() => expect(window.open).toHaveBeenCalled());
    // Hit the right endpoint with the page's payload.
    expect(apiFetchMock).toHaveBeenCalledWith(
      "/api/v1/reports/portfolio/html",
      expect.objectContaining({ method: "POST" }),
    );
    // Analytics is redaction-safe: kind only, no tickers/$/holdings.
    const call = trackMock.mock.calls.find((c) => c[0] === "report_export_clicked");
    expect(call?.[1]).toEqual({ kind: "portfolio" });
  });

  it("renders nothing without an access token or payload", () => {
    const { container } = render(<ReportExportButton kind="ticker" payload={null} />);
    expect(container.firstChild).toBeNull();
  });
});
