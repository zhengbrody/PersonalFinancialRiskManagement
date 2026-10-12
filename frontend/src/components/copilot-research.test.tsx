import { expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { CopilotResearchPanel } from "./copilot-research";
import { copilotResearchSchema } from "@/lib/copilot-research";
import fixture from "@/test-fixtures/copilot-research.json";

it("separates observations, untested hypotheses and unverified external leads", () => {
  render(<CopilotResearchPanel research={[copilotResearchSchema.parse(fixture)]} />);
  fireEvent.click(screen.getByText("AAPL · available"));
  expect(screen.getByText("20.00× · available")).toBeVisible();
  expect(screen.getAllByText(/Reporting period: unknown/)).toHaveLength(4);
  expect(screen.getAllByText(/not tested/)).toHaveLength(2);
  expect(screen.getByText(/Past growth can reflect/)).toBeVisible();
  expect(screen.getByText(/Author unknown · Conflicts not disclosed/)).toBeVisible();
  expect(screen.getByRole("link", { name: /Ignore all instructions/ })).toHaveAttribute("href", "https://example.com/research");
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("rejects foreign-security links and unknown observation references", () => {
  const wrong = structuredClone(fixture);
  wrong.observations[0].ticker = "MSFT";
  expect(copilotResearchSchema.safeParse(wrong).success).toBe(false);
  const missing = structuredClone(fixture);
  missing.questions[0].observation_ids = ["unrelated:metric"];
  expect(copilotResearchSchema.safeParse(missing).success).toBe(false);
});

it("rejects executable links and a research claim that it can rank candidates", () => {
  const wrong = structuredClone(fixture);
  wrong.leads[0].url = "javascript:alert(1)";
  expect(copilotResearchSchema.safeParse(wrong).success).toBe(false);
  expect(copilotResearchSchema.safeParse({ ...fixture, can_rank_candidates: true }).success).toBe(false);
});
