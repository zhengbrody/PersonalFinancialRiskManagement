"use client";

import { useId, useRef, useState } from "react";
import { sampleComparison, type ProceedsUse } from "@/lib/marketing-sample";
import { track } from "@/lib/analytics";
import styles from "./public-experience.module.css";

const usd = (value: number) => new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", maximumFractionDigits: 0,
}).format(value);

/** Shared by the homepage and demo; no fetch, LLM, account access, or persistence. */
export function SampleComparison() {
  const id = useId();
  const [reduction, setReduction] = useState(25);
  const [shock, setShock] = useState(-20);
  const [use, setUse] = useState<ProceedsUse>("cash");
  const interacted = useRef(false);
  function markInteraction() {
    if (interacted.current) return;
    interacted.current = true;
    track("demo_interacted", { kind: "sample_comparison" });
  }
  const { before, after, proceeds } = sampleComparison(reduction, shock, use);
  function reset() { setReduction(25); setShock(-20); setUse("cash"); }
  return (
    <section className={styles.demo} aria-label="Interactive sample portfolio">
      <div className={styles.demoTop}>
        <span className={styles.badge}>ILLUSTRATIVE SAMPLE</span>
        <button className={styles.textButton} onClick={reset}>Reset demo ↺</button>
      </div>
      <h2>A change worth understanding.</h2>
      <p className={styles.hint}>Simplified educational model—not the signed-in risk engine. No live prices or account data.</p>
      <p className={styles.muted}>$100,000 in stocks · $20,000 margin loan · $80,000 net equity</p>
      <div className={styles.allocation} aria-label="Sample allocation: Growth stock 40%, other stocks 60%">
        <span style={{ width: "40%" }} /><span style={{ width: "60%" }} />
      </div>
      <div className={styles.legend}><span>Growth stock · 40%</span><span>Other stocks · 60%</span></div>
      <div aria-live="polite" aria-atomic="true" className={styles.result}>
        <p className={styles.resultLabel}>Illustrative loss under a {Math.abs(shock)}% market fall</p>
        <div className={styles.lossPair}>
          <div><span>Current</span><strong>{usd(before.loss)}</strong></div>
          <span aria-hidden="true">→</span>
          <div><span>After change</span><strong>{usd(after.loss)}</strong></div>
        </div>
        <p>{usd(before.loss - after.loss)} less scenario loss. This is a hypothetical comparison, not a forecast.</p>
      </div>
      <div className={styles.controls}>
        <label htmlFor={`${id}-reduction`}>1. Reduce the growth position <strong>{reduction}%</strong></label>
        <input id={`${id}-reduction`} type="range" min="0" max="50" step="5" value={reduction}
          onChange={(event) => { markInteraction(); setReduction(Number(event.target.value)); }} />
        <p className={styles.hint}>{usd(proceeds)} of hypothetical proceeds. No actual holdings change.</p>
        <fieldset>
          <legend>2. Choose where the proceeds go</legend>
          <div className={styles.choices}>
            {(["cash", "repay"] as const).map((value) => (
              <label key={value} className={use === value ? styles.selected : ""}>
                <input type="radio" name={`${id}-proceeds`} checked={use === value}
                  onChange={() => { markInteraction(); setUse(value); }} />
                {value === "cash" ? "Keep as cash" : "Repay margin"}
              </label>
            ))}
          </div>
        </fieldset>
        <label htmlFor={`${id}-shock`}>3. Test a hypothetical market fall
          <select id={`${id}-shock`} value={shock} onChange={(event) => { markInteraction(); setShock(Number(event.target.value)); }}>
            <option value={-10}>−10%</option><option value={-20}>−20%</option><option value={-30}>−30%</option>
          </select>
        </label>
      </div>
      <div aria-live="polite" aria-atomic="true" className={styles.result}>
        <table className={styles.comparison}>
          <caption className={styles.srOnly}>Current portfolio versus hypothetical change</caption>
          <thead><tr><th scope="col">What changes</th><th scope="col">Current</th><th scope="col">After</th></tr></thead>
          <tbody>
            <tr><th scope="row">Growth / stock value</th><td>{(before.concentration * 100).toFixed(1)}%</td><td>{(after.concentration * 100).toFixed(1)}%</td></tr>
            <tr><th scope="row">Margin loan</th><td>{usd(before.margin)}</td><td>{usd(after.margin)}</td></tr>
            <tr><th scope="row">Cash</th><td>{usd(before.cash)}</td><td>{usd(after.cash)}</td></tr>
          </tbody>
        </table>
        <p className={styles.hint}>{use === "cash"
          ? "Cash stays available; the margin loan remains."
          : "The margin loan falls; less cash remains available."} Both choices have the same immediate shock loss here. Interest is not modeled.</p>
      </div>
      <details className={styles.assumptions}>
        <summary>How this sample is calculated</summary>
        <p>Fixed fictional holdings, not live prices: one $40,000 growth stock and $60,000 in other stocks, financed partly by a $20,000 loan. The growth stock moves 1.5× the market shock; other stocks move 1×; cash does not move.</p>
        <p>Loss = (remaining growth value × 1.5 + other stock value) × market fall. Net equity remains {usd(after.equity)} before the shock. Concentration uses stock value, not net equity.</p>
        <p>This simplified educational model excludes options, taxes, interest, transaction costs, changing correlations and broker liquidation rules. It is not VaR, maximum possible loss, or the full MindMarket risk engine. Reducing exposure can also reduce participation in a recovery.</p>
      </details>
    </section>
  );
}
