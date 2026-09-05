/**
 * DataTable behaviour: ticker filter narrows rows, clicking a sortable header
 * reorders, and the top-N collapse hides the tail until "show all".
 */

import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DataTable, type Column } from "./data-table";

type Row = { ticker: string; pct: number };

const ROWS: Row[] = [
  { ticker: "NVDA", pct: 0.4 },
  { ticker: "MSFT", pct: 0.35 },
  { ticker: "AAPL", pct: 0.25 },
];

const COLUMNS: Column<Row>[] = [
  { key: "ticker", header: "Ticker", render: (r) => r.ticker, sortValue: (r) => r.ticker },
  { key: "pct", header: "Share", align: "right", render: (r) => `${(r.pct * 100).toFixed(0)}%`, sortValue: (r) => r.pct },
];

function bodyTickers(): string[] {
  const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1); // drop header
  return rows.map((r) => r.querySelector("td")?.textContent ?? "");
}

describe("DataTable", () => {
  it("sorts through a keyboard-operable header button", async () => {
    render(<DataTable rows={ROWS} columns={COLUMNS} rowKey={(row) => row.ticker} />);
    screen.getByRole("button", { name: "Share" }).focus();
    await userEvent.keyboard("{Enter}{Enter}");
    expect(bodyTickers()).toEqual(["AAPL", "MSFT", "NVDA"]);
    expect(screen.getByRole("columnheader", { name: /Share/ })).toHaveAttribute("aria-sort", "ascending");
  });
  it("filters by the ticker field", async () => {
    const user = userEvent.setup();
    render(
      <DataTable rows={ROWS} columns={COLUMNS} rowKey={(r) => r.ticker} filterKey="ticker" topN={2} />,
    );
    await user.type(screen.getByLabelText(/filter ticker/i), "ms");
    expect(bodyTickers()).toEqual(["MSFT"]);
  });

  it("sorts when a sortable header is clicked", async () => {
    const user = userEvent.setup();
    render(<DataTable rows={ROWS} columns={COLUMNS} rowKey={(r) => r.ticker} />);
    // No initial sort → input order.
    expect(bodyTickers()).toEqual(["NVDA", "MSFT", "AAPL"]);
    // Click Share → desc (highest pct first = NVDA already first), click again → asc.
    await user.click(screen.getByText("Share"));
    expect(bodyTickers()).toEqual(["NVDA", "MSFT", "AAPL"]);
    await user.click(screen.getByText("Share"));
    expect(bodyTickers()).toEqual(["AAPL", "MSFT", "NVDA"]);
  });

  it("collapses to top-N then expands", async () => {
    const user = userEvent.setup();
    render(
      <DataTable
        rows={ROWS}
        columns={COLUMNS}
        rowKey={(r) => r.ticker}
        initialSort={{ key: "pct", dir: "desc" }}
        topN={2}
      />,
    );
    expect(bodyTickers()).toEqual(["NVDA", "MSFT"]); // AAPL hidden
    await user.click(screen.getByRole("button", { name: /show all 3/i }));
    expect(bodyTickers()).toEqual(["NVDA", "MSFT", "AAPL"]);
  });
});
