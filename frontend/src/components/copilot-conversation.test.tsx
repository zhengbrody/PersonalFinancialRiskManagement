/**
 * FollowUpChips language behavior (rendered through the real
 * <CopilotConversation/>): the deterministic follow-up suggestions follow
 * the conversation language — Chinese last user message → Chinese chips,
 * English → English chips — and already-asked questions stay filtered out
 * (max 3 shown).
 *
 * The conversation is seeded via the mocked `readSession` (the component
 * hydrates persisted turns on mount), so no network/stream is involved.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ accessToken: "test-jwt" }),
}));
vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));

const readSessionMock = vi.fn();
vi.mock("@/lib/use-session-state", () => ({
  readSession: (key: string) => readSessionMock(key),
  writeSession: vi.fn(),
}));

import { CopilotConversation } from "./copilot-conversation";

type Msg = { role: "user" | "assistant"; text: string };

function seedConversation(messages: Msg[]) {
  readSessionMock.mockReturnValue(messages);
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("FollowUpChips", () => {
  it("shows English follow-up chips after an English conversation", () => {
    seedConversation([
      { role: "user", text: "Is my portfolio too risky?" },
      { role: "assistant", text: "Here is your risk picture." },
    ]);
    renderWithQuery(<CopilotConversation />);

    expect(
      screen.getByRole("button", {
        name: "What's my single biggest risk right now?",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "我现在最大的单一风险是什么？" }),
    ).not.toBeInTheDocument();
  });

  it("shows Chinese follow-up chips when the last user message is Chinese", () => {
    seedConversation([
      { role: "user", text: "我的组合风险高吗？" },
      { role: "assistant", text: "**评估:** 组合评分为 **700/1000**。" },
    ]);
    renderWithQuery(<CopilotConversation />);

    expect(
      screen.getByRole("button", { name: "我现在最大的单一风险是什么？" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "市场下跌 20% 会对我有多大影响？" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "What's my single biggest risk right now?",
      }),
    ).not.toBeInTheDocument();
  });

  it("filters out already-asked questions (case-insensitive) and caps at 3", () => {
    seedConversation([
      { role: "user", text: "what's my single biggest risk right now?" },
      { role: "assistant", text: "Concentration in tech." },
    ]);
    renderWithQuery(<CopilotConversation />);

    // The asked question is gone; the next three in order take its place.
    expect(
      screen.queryByRole("button", {
        name: "What's my single biggest risk right now?",
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "How would a -20% market drop hit me?" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "What would diversify my portfolio the most?",
      }),
    ).toBeInTheDocument();
    // Max 3 suggestions → the 5th question stays hidden.
    expect(
      screen.queryByRole("button", {
        name: "Any hidden fees or tax-loss opportunities?",
      }),
    ).not.toBeInTheDocument();
  });
});
