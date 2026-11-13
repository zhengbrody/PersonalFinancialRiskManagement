# Factor stress model — point-in-time validation

Generated 2026-11-12T05:29:09Z · model `factor-stress-v1` · prices through 2026-11-11.

- Report hash (sha256): `1d44c9f68f75f470d72129775043d10cff43a585cf6001714255ec619cfa8039`
- Data hash (sha256): `c7c91b46d404b47379839bb532223ae3a78ae9b0a7245f30594e1e4ee83443b1`
- Code hash (sha256): `45c642203ae8cf14286d215c082ff10ebc0f50876f740732abea465a5bf4ed69`

## Conditional accuracy (loadings fitted before each episode)

| Model | n | Bias | MAE | RMSE | Calibration slope |
|---|---|---|---|---|---|
| Seven-factor | 56 | -0.2% | 4.0% | 6.1% | 0.93 |
| Market beta only | 56 | +0.7% | 4.9% | 6.4% | 0.93 |
| Assume beta = 1 | 56 | -3.2% | 7.6% | 10.8% | 0.84 |

90% interval: 44 of 56 realised outcomes fell inside (78.6%).

| Episode | Portfolio | Fit cutoff | Realised | Predicted | Interval | Error |
|---|---|---|---|---|---|---|
| Global Financial Crisis | US 60/40 | 2007-10-01 | -30.3% | -31.1% | -33.9% to -28.3% | -0.8% |
| Global Financial Crisis | Nasdaq 100 | 2007-10-01 | -51.6% | -53.2% | -70.2% to -36.2% | -1.6% |
| Global Financial Crisis | Nine US sectors, equal weight | 2007-10-01 | -51.7% | -55.7% | -60.9% to -50.5% | -4.0% |
| Global Financial Crisis | Global equity | 2007-10-01 | -57.6% | -56.0% | -62.3% to -49.6% | +1.7% |
| Global Financial Crisis | Defensive | 2007-10-01 | -27.5% | -36.0% | -44.1% to -27.9% | -8.5% |
| Global Financial Crisis | Gold miners, energy, long bonds | 2007-10-01 | -17.0% | -22.2% | -40.3% to -4.1% | -5.2% |
| Global Financial Crisis | Financials | 2007-10-01 | -76.9% | -67.7% | -78.0% to -57.4% | +9.2% |
| Global Financial Crisis | US small caps | 2007-10-01 | -58.4% | -70.4% | -81.2% to -59.5% | -12.0% |
| Global Financial Crisis | Five largest tech stocks today (hindsight-selected) | 2007-10-01 | -53.1% | -50.7% | -85.4% to -16.1% | +2.3% |
| 2011 US downgrade | US 60/40 | 2011-07-14 | -10.4% | -10.0% | -13.8% to -6.3% | +0.3% |
| 2011 US downgrade | Nasdaq 100 | 2011-07-14 | -14.0% | -19.1% | -30.1% to -8.0% | -5.0% |
| 2011 US downgrade | Nine US sectors, equal weight | 2011-07-14 | -17.6% | -18.1% | -23.4% to -12.9% | -0.5% |
| 2011 US downgrade | Global equity | 2011-07-14 | -22.1% | -21.3% | -25.9% to -16.7% | +0.8% |
| 2011 US downgrade | Defensive | 2011-07-14 | -4.7% | -7.3% | -14.5% to -0.0% | -2.5% |
| 2011 US downgrade | Gold miners, energy, long bonds | 2011-07-14 | -2.7% | -5.6% | -16.8% to +5.6% | -2.9% |
| 2011 US downgrade | Financials | 2011-07-14 | -26.4% | -25.5% | -46.7% to -4.3% | +0.9% |
| 2011 US downgrade | US small caps | 2011-07-14 | -27.2% | -22.6% | -35.1% to -10.1% | +4.6% |
| 2011 US downgrade | Five largest tech stocks today (hindsight-selected) | 2011-07-14 | -11.7% | -22.1% | -38.3% to -5.9% | -10.4% |
| 2015 China devaluation | US 60/40 | 2015-07-31 | -6.4% | -6.6% | -7.1% to -6.1% | -0.2% |
| 2015 China devaluation | Nasdaq 100 | 2015-07-31 | -12.1% | -12.4% | -16.1% to -8.6% | -0.3% |
| 2015 China devaluation | Nine US sectors, equal weight | 2015-07-31 | -10.6% | -10.7% | -12.2% to -9.2% | -0.1% |
| 2015 China devaluation | Global equity | 2015-07-31 | -11.5% | -10.6% | -12.7% to -8.5% | +0.9% |
| 2015 China devaluation | Defensive | 2015-07-31 | -6.3% | -6.1% | -8.6% to -3.5% | +0.2% |
| 2015 China devaluation | Gold miners, energy, long bonds | 2015-07-31 | -5.9% | -3.1% | -8.1% to +1.8% | +2.8% |
| 2015 China devaluation | Financials | 2015-07-31 | -12.4% | -11.3% | -14.6% to -8.1% | +1.0% |
| 2015 China devaluation | US small caps | 2015-07-31 | -9.5% | -11.7% | -16.1% to -7.2% | -2.1% |
| 2015 China devaluation | Five largest tech stocks today (hindsight-selected) | 2015-07-31 | -12.1% | -13.6% | -20.1% to -7.1% | -1.6% |
| 2018 Q4 selloff | US 60/40 | 2018-09-12 | -11.4% | -11.3% | -12.3% to -10.3% | +0.1% |
| 2018 Q4 selloff | Nasdaq 100 | 2018-09-12 | -22.0% | -20.4% | -28.7% to -12.1% | +1.6% |
| 2018 Q4 selloff | Nine US sectors, equal weight | 2018-09-12 | -18.3% | -18.1% | -21.9% to -14.2% | +0.2% |
| 2018 Q4 selloff | Global equity | 2018-09-12 | -16.9% | -20.1% | -24.0% to -16.2% | -3.2% |
| 2018 Q4 selloff | Defensive | 2018-09-12 | -6.1% | -7.4% | -14.3% to -0.5% | -1.3% |
| 2018 Q4 selloff | Gold miners, energy, long bonds | 2018-09-12 | -4.3% | -5.5% | -17.4% to +6.4% | -1.2% |
| 2018 Q4 selloff | Financials | 2018-09-12 | -24.2% | -23.8% | -32.4% to -15.3% | +0.4% |
| 2018 Q4 selloff | US small caps | 2018-09-12 | -26.0% | -21.8% | -31.9% to -11.6% | +4.3% |
| 2018 Q4 selloff | Five largest tech stocks today (hindsight-selected) | 2018-09-12 | -30.1% | -22.0% | -34.4% to -9.6% | +8.0% |
| COVID-19 crash | US 60/40 | 2020-02-10 | -21.5% | -20.4% | -21.1% to -19.7% | +1.2% |
| COVID-19 crash | Nasdaq 100 | 2020-02-10 | -27.9% | -37.2% | -42.3% to -32.2% | -9.3% |
| COVID-19 crash | Nine US sectors, equal weight | 2020-02-10 | -36.5% | -32.1% | -34.7% to -29.5% | +4.5% |
| COVID-19 crash | Global equity | 2020-02-10 | -33.4% | -29.1% | -31.8% to -26.3% | +4.4% |
| COVID-19 crash | Defensive | 2020-02-10 | -23.7% | -17.6% | -22.2% to -12.9% | +6.1% |
| COVID-19 crash | Gold miners, energy, long bonds | 2020-02-10 | -22.5% | -10.9% | -17.6% to -4.2% | +11.6% |
| COVID-19 crash | Financials | 2020-02-10 | -44.7% | -35.8% | -42.5% to -29.0% | +8.9% |
| COVID-19 crash | US small caps | 2020-02-10 | -40.7% | -41.6% | -47.2% to -35.9% | -0.9% |
| COVID-19 crash | Five largest tech stocks today (hindsight-selected) | 2020-02-10 | -26.7% | -42.0% | -49.1% to -34.9% | -15.2% |
| 2022 rate-hike bear market | US 60/40 | 2021-12-23 | -21.0% | -20.8% | -23.9% to -17.7% | +0.2% |
| 2022 rate-hike bear market | Nasdaq 100 | 2021-12-23 | -34.3% | -27.6% | -43.5% to -11.7% | +6.7% |
| 2022 rate-hike bear market | Nine US sectors, equal weight | 2021-12-23 | -13.1% | -24.0% | -33.7% to -14.3% | -10.9% |
| 2022 rate-hike bear market | Global equity | 2021-12-23 | -26.9% | -23.8% | -31.0% to -16.5% | +3.1% |
| 2022 rate-hike bear market | Defensive | 2021-12-23 | -11.8% | -23.5% | -34.3% to -12.8% | -11.8% |
| 2022 rate-hike bear market | Gold miners, energy, long bonds | 2021-12-23 | -1.6% | -29.0% | -53.0% to -4.9% | -27.3% |
| 2022 rate-hike bear market | Financials | 2021-12-23 | -20.3% | -11.0% | -38.9% to +16.8% | +9.2% |
| 2022 rate-hike bear market | US small caps | 2021-12-23 | -25.0% | -27.6% | -54.1% to -1.1% | -2.5% |
| 2022 rate-hike bear market | Five largest tech stocks today (hindsight-selected) | 2021-12-23 | -36.8% | -27.3% | -47.3% to -7.4% | +9.5% |
| 2023 regional-bank stress | US 60/40 | 2023-02-28 | +0.6% | +1.1% | -0.0% to +2.1% | +0.4% |
| 2023 regional-bank stress | Nasdaq 100 | 2023-02-28 | +4.6% | +1.7% | -5.1% to +8.4% | -2.9% |
| 2023 regional-bank stress | Nine US sectors, equal weight | 2023-02-28 | -2.5% | -1.1% | -4.7% to +2.5% | +1.4% |
| 2023 regional-bank stress | Global equity | 2023-02-28 | -1.3% | -0.4% | -3.2% to +2.4% | +0.9% |
| 2023 regional-bank stress | Defensive | 2023-02-28 | +1.5% | +2.2% | -2.6% to +7.0% | +0.6% |
| 2023 regional-bank stress | Gold miners, energy, long bonds | 2023-02-28 | +4.5% | +7.8% | -1.8% to +17.4% | +3.3% |
| 2023 regional-bank stress | Financials | 2023-02-28 | -14.8% | -7.1% | -15.0% to +0.8% | +7.7% |
| 2023 regional-bank stress | US small caps | 2023-02-28 | -7.6% | -1.9% | -11.5% to +7.7% | +5.7% |
| 2023 regional-bank stress | Five largest tech stocks today (hindsight-selected) | 2023-02-28 | +8.5% | +2.5% | -6.1% to +11.2% | -6.0% |

## Unconditional calibration (rolling 10-day VaR, out of sample)

| Level | Windows | Breaches | Breach rate | Expected |
|---|---|---|---|---|
| 95% | 3392 | 109 | 3.2% | 5.0% |
| 99% | 3392 | 40 | 1.2% | 1.0% |

## Caveats

- Conditional test: the model is given the factor moves that actually happened. It measures how well point-in-time loadings translate those moves into a portfolio loss — not whether a crisis could have been foreseen.
- Seven episodes is a small sample. Treat these as diagnostics, not a pass mark.
- Loadings rise in a crisis, so a model fitted in calmer times tends to understate losses; the bias column shows by how much.
- No reference portfolio holds any of the funds the factors are built from, so none of them predicts itself.
- The reference portfolios are funds that still exist. A fund that closed is not in the sample, which flatters broad-market results slightly.
- A portfolio you hold today has no observed history as a portfolio. Replaying it through the past is a reconstruction and is reported separately, in the Crisis replay.
