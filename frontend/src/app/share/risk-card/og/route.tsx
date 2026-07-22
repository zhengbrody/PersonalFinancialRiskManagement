/**
 * Dynamic OpenGraph image for the shareable risk-score card (1200×630 PNG).
 *
 * A Route Handler (NOT the `opengraph-image` file convention) because the card
 * state lives in a `?book=` QUERY param — the file convention only receives
 * `params`, never `searchParams`, so it cannot vary by query string. The handler
 * gets the full Request and reads `?book=`.
 *
 * Runs on the NODE runtime (this app is `output: standalone` / `node server.js`
 * — there is no edge runtime when self-hosting, so we do NOT export
 * `runtime = "edge"`; `next/og`'s ImageResponse runs fine on Node). No new
 * dependency, no `sharp`. Hardcoded brand HEX (satori cannot resolve the
 * `--mm-*` CSS vars) from the dark brand palette in globals.css. Only ~2 `book`
 * variants exist, so a long Cache-Control lets Cloudflare cache each at the edge
 * — effectively 2 renders ever, trivial on the t3.micro.
 */

import { ImageResponse } from "next/og";
import { parseShareBook, riskFitLabel, stressBandLabel, titleCase, type ShareBand } from "@/lib/share-card";
import { resolveShareToken } from "@/lib/share-card-server";

// Dynamic by `?book=` (reads the request URL), but only ~2 variants exist and
// the long Cache-Control below lets Cloudflare cache each at the edge.

// Dark brand palette (globals.css `.dark` --mm-*), inlined for satori.
const INK = "#0b0e11";
const PANEL = "#10171d";
const TEXT = "#f8fafc";
const DIM = "#aab4c2";
const TEAL = "#39a3b5";
const GOLD = "#d4a017";
const GREEN = "#38d39f";
const RED = "#ff6b6b";
const HAIR = "rgba(255,255,255,0.12)";

function bandColor(band: ShareBand): string {
  if (band === "Poor") return RED;
  if (band === "Watch") return GOLD;
  return GREEN; // Healthy / Strong
}

export async function GET(req: Request): Promise<Response> {
  const { searchParams } = new URL(req.url);
  const token = searchParams.get("token");
  if (token) {
    try {
      const card = await resolveShareToken(token);
      const maxAge = Math.max(0, Math.min(3600, card.exp - Math.floor(Date.now() / 1000)));
      return new ImageResponse(
        <div style={{ width: "1200px", height: "630px", display: "flex", flexDirection: "column", justifyContent: "space-between", background: INK, backgroundImage: `linear-gradient(135deg, ${PANEL} 0%, ${INK} 55%)`, padding: "64px 72px", fontFamily: "sans-serif" }}>
          <div style={{ display: "flex", justifyContent: "space-between", color: TEXT, fontSize: "30px", fontWeight: 700 }}><span>MindMarket</span><span style={{ color: TEAL, fontSize: "20px", letterSpacing: "0.16em" }}>PORTFOLIO RISK PROFILE</span></div>
          <div style={{ display: "flex", flexDirection: "column", gap: "22px" }}>
            <span style={{ color: DIM, fontSize: "24px" }}>Privacy-preserving share card</span>
            <span style={{ color: TEXT, fontSize: "82px", fontWeight: 800 }}>{titleCase(card.score_band)}</span>
            <div style={{ display: "flex", gap: "12px", flexWrap: "wrap" }}>
              {[`Risk fit · ${riskFitLabel(card.risk_fit)}`, `Primary risk · ${titleCase(card.top_risk_category)}`, `Stress · ${stressBandLabel(card.stress_band)}`, `Confidence · ${titleCase(card.confidence_label)}`].map((value) => <span key={value} style={{ display: "flex", padding: "10px 18px", borderRadius: "10px", background: PANEL, border: `1px solid ${HAIR}`, color: TEXT, fontSize: "22px" }}>{value}</span>)}
            </div>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", borderTop: `1px solid ${HAIR}`, paddingTop: "26px", color: DIM, fontSize: "22px" }}><span>No positions · no identity · no exact values</span><span>mindmarket.app</span></div>
        </div>,
        { width: 1200, height: 630, headers: { "Cache-Control": `public, max-age=${maxAge}, s-maxage=${maxAge}, must-revalidate`, "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow" } },
      );
    } catch {
      return new Response("Not found", { status: 404, headers: { "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer" } });
    }
  }
  const book = parseShareBook(searchParams.get("book") ?? undefined);
  const accent = bandColor(book.band);
  const markerPct = Math.max(0, Math.min(100, (book.score / 1000) * 100));

  return new ImageResponse(
    (
      <div
        style={{
          width: "1200px",
          height: "630px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: INK,
          backgroundImage: `linear-gradient(135deg, ${PANEL} 0%, ${INK} 55%)`,
          padding: "64px 72px",
          fontFamily: "sans-serif",
        }}
      >
        {/* header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
            <div
              style={{
                display: "flex",
                width: "44px",
                height: "44px",
                borderRadius: "12px",
                background: TEAL,
                alignItems: "center",
                justifyContent: "center",
                color: INK,
                fontSize: "28px",
                fontWeight: 800,
              }}
            >
              M
            </div>
            <span style={{ color: TEXT, fontSize: "30px", fontWeight: 700, letterSpacing: "-0.02em" }}>
              MindMarket
            </span>
          </div>
          <span
            style={{
              color: TEAL,
              fontSize: "20px",
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.18em",
            }}
          >
            Portfolio Risk X-ray
          </span>
        </div>

        {/* score block */}
        <div style={{ display: "flex", flexDirection: "column", gap: "22px" }}>
          <span style={{ color: DIM, fontSize: "26px", fontWeight: 500 }}>{book.label}</span>
          <div style={{ display: "flex", alignItems: "flex-end", gap: "20px" }}>
            <span style={{ color: TEXT, fontSize: "150px", fontWeight: 800, lineHeight: 1 }}>
              {book.score}
            </span>
            <span style={{ color: DIM, fontSize: "40px", fontWeight: 600, paddingBottom: "22px" }}>
              / 1000
            </span>
            <span
              style={{
                display: "flex",
                marginLeft: "12px",
                marginBottom: "30px",
                padding: "8px 20px",
                borderRadius: "999px",
                background: `${accent}22`,
                color: accent,
                fontSize: "30px",
                fontWeight: 700,
              }}
            >
              {book.band}
            </span>
          </div>

          {/* band bar */}
          <div style={{ display: "flex", position: "relative", width: "100%", height: "16px" }}>
            <div
              style={{
                display: "flex",
                width: "100%",
                height: "16px",
                borderRadius: "999px",
                background: "linear-gradient(90deg, #ff6b6b 0%, #d4a017 45%, #38d39f 75%)",
                opacity: 0.55,
              }}
            />
            <div
              style={{
                display: "flex",
                position: "absolute",
                top: "-6px",
                left: `${markerPct}%`,
                width: "6px",
                height: "28px",
                marginLeft: "-3px",
                borderRadius: "999px",
                background: TEXT,
              }}
            />
          </div>
        </div>

        {/* takeaway */}
        <p style={{ color: TEXT, fontSize: "30px", lineHeight: 1.4, margin: 0, maxWidth: "1000px" }}>
          {book.takeaway}
        </p>

        {/* footer */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderTop: `1px solid ${HAIR}`,
            paddingTop: "26px",
          }}
        >
          <span style={{ color: DIM, fontSize: "24px" }}>
            Free risk X-ray — no signup · mindmarket.app
          </span>
          <span style={{ display: "flex", gap: "10px" }}>
            {book.dimensions.map((d) => (
              <span
                key={d.label}
                style={{
                  display: "flex",
                  padding: "6px 16px",
                  borderRadius: "10px",
                  background: PANEL,
                  border: `1px solid ${HAIR}`,
                  color: TEXT,
                  fontSize: "22px",
                  fontWeight: 600,
                }}
              >
                {d.value.toFixed(1)}
              </span>
            ))}
          </span>
        </div>
      </div>
    ),
    {
      width: 1200,
      height: 630,
      headers: {
        "Cache-Control": "public, max-age=86400, s-maxage=604800, immutable",
      },
    },
  );
}
