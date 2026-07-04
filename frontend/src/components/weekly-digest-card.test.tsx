import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";
import { WeeklyDigestCard } from "./weekly-digest-card";

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: { id: "u1" }, accessToken: "tok", configured: true, loading: false }),
}));

function mockJson(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const envelope = (enabled: boolean) => ({
  data: { enabled },
  error: null,
  meta: { request_id: "r" },
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("WeeklyDigestCard", () => {
  it("shows the enabled state and toggles it off via POST", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(mockJson(envelope(true))) // GET pref
      .mockResolvedValueOnce(mockJson(envelope(false))) // POST toggle
      .mockResolvedValue(mockJson(envelope(false))); // refetch
    renderWithQuery(<WeeklyDigestCard />);

    expect(await screen.findByText("已开启")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /关闭简报/ }));
    await waitFor(() => expect(screen.getByText("已关闭")).toBeInTheDocument());

    const post = fetchSpy.mock.calls.find(([, init]) => init?.method === "POST");
    expect(post?.[0]).toContain("/api/v1/digest/pref");
    expect(post?.[1]?.body).toContain('"enabled":false');
  });

  it("renders nothing while the backing table is unavailable (pref GET fails)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockJson({ data: null, error: { code: "x", message: "y" }, meta: { request_id: "r" } }, 503),
    );
    const { container } = renderWithQuery(<WeeklyDigestCard />);
    await waitFor(() => expect(container.firstChild).toBeNull());
  });
});
