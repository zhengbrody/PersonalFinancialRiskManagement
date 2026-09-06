import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test-utils";
import { riskCheckSchema } from "@/lib/risk-check";

const identity = { userId: "u1", portfolioId: "p1" };
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: { id: identity.userId }, accessToken: "jwt" }),
}));
vi.mock("@/lib/portfolio-context", () => ({
  usePortfolioContext: () => ({
    activePortfolioId: identity.portfolioId,
    current: { name: identity.portfolioId },
  }),
}));
import { CopilotConversation } from "./copilot-conversation";

const check = riskCheckSchema.parse({
  portfolio_id: "p1",
  result_id: "r1",
  methodology_version: "risk-check-v1",
  computed_at: "2026-09-05T12:00:00Z",
  price_history_as_of: "2026-09-04",
  status: "limited",
  summary: "Inspect risk and coverage.",
  findings: [
    {
      key: "coverage",
      title: "Coverage first",
      severity: "info",
      explanation: "Not all inputs are available.",
    },
  ],
  metrics: [
    {
      key: "var",
      label: "A bad day",
      value: 120,
      unit: "usd",
      horizon: "1 trading day",
      basis: "Net equity",
      explanation: "Not a maximum loss.",
      source_field: "losses.var_1d_95.usd",
    },
  ],
  limitations: ["Options use a delta approximation."],
});
const answer = {
  intent: "explain_metric",
  tickers: [],
  evidence: [],
  data_only: true,
  answer_markdown: "Expected shortfall describes the tail.",
};
const envelope = (data: unknown) =>
  new Response(
    JSON.stringify({ data, error: null, meta: { request_id: "t" } }),
  );

const savedBook = "33333333-3333-4333-8333-333333333333";
const savedId = "44444444-4444-4444-8444-444444444444";
function savedResult(id = savedId, state = "completed") {
  return {
    id, portfolio_id: savedBook, state,
    created_at: "2026-09-06T12:00:00Z", updated_at: "2026-09-06T12:00:01Z",
    expires_at: "2026-09-06T12:10:00Z", error_code: null,
    result: state === "completed" ? { ...check, portfolio_id: savedBook } : null,
  };
}
function storeInterruptedRun() {
  sessionStorage.setItem(`mm:copilot:thread:v1:u1:${savedBook}`, JSON.stringify([
    { id: savedId, runId: savedId, question: "Check my portfolio", status: "running", kind: "check" },
  ]));
}
beforeEach(() => {
  sessionStorage.clear();
  identity.userId = "u1";
  identity.portfolioId = "p1";
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("single-window Copilot", () => {
  it("saves the run ID before POST and accepts only its own completed result", async () => {
    vi.stubEnv("NEXT_PUBLIC_COPILOT_RUNS_ENABLED", "true");
    identity.portfolioId = savedBook;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
      expect(String(url)).toContain("/api/v1/copilot/runs");
      const body = JSON.parse(String(init?.body));
      expect(body.expected_portfolio_id).toBe(savedBook);
      expect(sessionStorage.getItem(`mm:copilot:thread:v1:u1:${savedBook}`)).toContain(body.id);
      return envelope(savedResult(body.id));
    });
    renderWithQuery(<CopilotConversation />);
    fireEvent.click(screen.getByRole("button", { name: "Check my portfolio" }));
    await screen.findByText("Coverage first");
  });
  it("refresh restores an interrupted run and retrieves it with GET only", async () => {
    identity.portfolioId = savedBook;
    storeInterruptedRun();
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope(savedResult()));
    renderWithQuery(<CopilotConversation />);
    const retrieve = await screen.findByRole("button", { name: "Retrieve saved result" });
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(retrieve);
    await screen.findByText("Coverage first");
    expect(fetch.mock.calls[0][1]?.method).toBe("GET");
    expect(String(fetch.mock.calls[0][0])).toContain(savedId);
  });
  it("does not offer recovery for a check the server refused to start", async () => {
    vi.stubEnv("NEXT_PUBLIC_COPILOT_RUNS_ENABLED", "true");
    identity.portfolioId = savedBook;
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      data: null, error: { code: "analysis_busy", message: "A check is already running." },
      meta: { request_id: "test" },
    }), { status: 429 }));
    renderWithQuery(<CopilotConversation />);
    fireEvent.click(screen.getByRole("button", { name: "Check my portfolio" }));
    await screen.findByText("A check is already running.");
    expect(screen.queryByRole("button", { name: "Retrieve saved result" })).not.toBeInTheDocument();
  });
  it("does not confuse stopping the browser wait with server cancellation", async () => {
    vi.stubEnv("NEXT_PUBLIC_COPILOT_RUNS_ENABLED", "true");
    identity.portfolioId = savedBook;
    vi.spyOn(globalThis, "fetch").mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));
    renderWithQuery(<CopilotConversation />);
    fireEvent.click(screen.getByRole("button", { name: "Check my portfolio" }));
    fireEvent.click(await screen.findByRole("button", { name: "Stop waiting" }));
    await screen.findByRole("button", { name: "Retrieve saved result" });
    expect(screen.getByText(/cancel the server run below/)).toBeInTheDocument();
  });
  it("explicit cancellation is confirmed by the server, not by aborting fetch", async () => {
    identity.portfolioId = savedBook;
    storeInterruptedRun();
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope(savedResult(savedId, "cancelled")));
    renderWithQuery(<CopilotConversation />);
    fireEvent.click(await screen.findByRole("button", { name: "Cancel server check" }));
    await screen.findByText(/Check cancelled. Any computation already running/);
    expect(fetch.mock.calls[0][1]?.method).toBe("POST");
    expect(String(fetch.mock.calls[0][0])).toContain(`${savedId}/cancel`);
  });
  it("rejects a valid-looking result returned for a different run ID", async () => {
    identity.portfolioId = savedBook;
    storeInterruptedRun();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope(savedResult("55555555-5555-4555-8555-555555555555")));
    renderWithQuery(<CopilotConversation />);
    fireEvent.click(await screen.findByRole("button", { name: "Retrieve saved result" }));
    await screen.findByText(/does not match this portfolio and request/);
    expect(screen.queryByText("Coverage first")).not.toBeInTheDocument();
  });
  it("checks the selected portfolio and expands the engine numbers in place", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(envelope({ copilot_check: check }));
    const user = userEvent.setup();
    renderWithQuery(<CopilotConversation />);
    await user.click(
      screen.getByRole("button", { name: "Check my portfolio" }),
    );
    await screen.findByText("Coverage first");
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({
      expected_portfolio_id: "p1",
      include_copilot_check: true,
    });
    await user.click(
      screen.getByRole("button", { name: "Understand the numbers" }),
    );
    expect(screen.getByText("$120")).toBeInTheDocument();
    expect(screen.getByText("1 trading day")).toBeInTheDocument();
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(
      screen.queryByRole("link", { name: "Open Analyze" }),
    ).not.toBeInTheDocument();
  });
  it("uses grounded answers and never auto-runs prefill", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(envelope(answer));
    renderWithQuery(
      <CopilotConversation initialQuestion="Explain expected shortfall" />,
    );
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText("Expected shortfall describes the tail.");
    expect(String(fetch.mock.calls[0][0])).toContain("/copilot/ask");
  });
  it("restores completed history across page and floating views", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope(answer));
    const view = renderWithQuery(
      <CopilotConversation initialQuestion="Explain risk" />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText("Expected shortfall describes the tail.");
    view.unmount();
    renderWithQuery(<CopilotConversation variant="floating" />);
    expect(
      await screen.findByText("Expected shortfall describes the tail."),
    ).toBeInTheDocument();
  });
  it("rejects a different portfolio in a successful response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      envelope({ copilot_check: { ...check, portfolio_id: "p2" } }),
    );
    renderWithQuery(<CopilotConversation />);
    fireEvent.click(screen.getByRole("button", { name: "Check my portfolio" }));
    await screen.findByText(/belongs to another portfolio/);
    expect(screen.queryByText("Coverage first")).not.toBeInTheDocument();
  });
  it("does not paint late results into another portfolio", async () => {
    let resolve!: (r: Response) => void;
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
    const view = renderWithQuery(<CopilotConversation />);
    fireEvent.click(screen.getByRole("button", { name: "Check my portfolio" }));
    identity.portfolioId = "p2";
    view.rerender(<CopilotConversation />);
    resolve(envelope({ copilot_check: check }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Check my portfolio" }),
      ).toBeEnabled(),
    );
    expect(screen.queryByText("Coverage first")).not.toBeInTheDocument();
    expect(sessionStorage.getItem("mm:copilot:thread:v1:u1:p2")).toBeNull();
  });
  it("isolates history on an account change", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope(answer));
    const view = renderWithQuery(
      <CopilotConversation initialQuestion="Private question" />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText("Expected shortfall describes the tail.");
    identity.userId = "u2";
    view.rerender(<CopilotConversation />);
    expect(
      screen.queryByText("Expected shortfall describes the tail."),
    ).not.toBeInTheDocument();
  });
  it("marks reloaded requests interrupted without automatically rerunning", () => {
    sessionStorage.setItem(
      "mm:copilot:thread:v1:u1:p1",
      JSON.stringify([
        {
          id: "r",
          question: "Check my portfolio",
          kind: "check",
          status: "running",
        },
      ]),
    );
    const fetch = vi.spyOn(globalThis, "fetch");
    renderWithQuery(<CopilotConversation />);
    expect(screen.getByText(/not automatically restarted/)).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });
  it("starts only one calculation on double click and supports stopping", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(
        (_url, opts) =>
          new Promise((_r, reject) =>
            opts?.signal?.addEventListener("abort", () =>
              reject(new Error("aborted")),
            ),
          ),
      );
    renderWithQuery(<CopilotConversation />);
    const button = screen.getByRole("button", { name: "Check my portfolio" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(fetch).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Stop waiting" }));
    await screen.findByText(/Stopped waiting/);
    expect(screen.queryByText("Coverage first")).not.toBeInTheDocument();
  });
  it("does not submit on IME Enter", () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    renderWithQuery(<CopilotConversation initialQuestion="检查我的组合风险" />);
    fireEvent.keyDown(screen.getByRole("textbox"), {
      key: "Enter",
      isComposing: true,
    });
    expect(fetch).not.toHaveBeenCalled();
  });
});
