const fs = require("fs");
const path = require("path");
const { chromium } = require(
  "/Users/zhengdong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright"
);

const ROOT = process.cwd();
const OUT_DIR = path.join(ROOT, "docs/marketing/youtube/rendered/2026-05-19");
const AUDIO = path.join(OUT_DIR, "narration.m4a");
const WEBM = path.join(OUT_DIR, "mindmarket-2026-05-19-bond-risk.webm");
const HTML = path.join(OUT_DIR, "recorder.html");

fs.mkdirSync(OUT_DIR, { recursive: true });

const slides = [
  {
    title: "今天美股真正的风险",
    subtitle: "不是指数跌了多少，而是债券市场正在重新定价风险",
    tag: "Market Risk",
    bullets: ["美股继续从高位回落", "收益率上行压制估值", "科技 / AI 交易相对承压"],
    accent: "#f0c46a",
  },
  {
    title: "Market Snapshot",
    subtitle: "2026-05-19 收盘前后主要信号",
    tag: "Near Close",
    metrics: [
      ["S&P 500", "继续回落"],
      ["Dow", "-0.6%"],
      ["Nasdaq", "-0.8%"],
      ["10Y Yield", "~4.65%"],
    ],
    bullets: ["VIX 约 18，未恐慌但风险抬升", "30Y yield 维持在 5% 以上"],
    accent: "#5dc4b8",
  },
  {
    title: "为什么债券收益率重要",
    subtitle: "Inflation concern -> Higher yields -> Valuation pressure",
    tag: "Rates",
    flow: ["通胀担忧", "收益率上行", "估值倍数承压", "科技股波动加大"],
    bullets: ["成长股和 AI 股本质上对利率更敏感", "指数没大跌，不代表风险没变"],
    accent: "#e56b6f",
  },
  {
    title: "分散持仓不等于分散风险",
    subtitle: "Ticker diversification != Risk diversification",
    tag: "Portfolio",
    bullets: [
      "十几只股票可能仍然押注同一个宏观环境",
      "低利率、强流动性、AI 估值扩张是同一类风险驱动",
      "压力环境下，相关性会突然上升",
    ],
    accent: "#8ecae6",
  },
  {
    title: "AI / Chip Crowded Trade",
    subtitle: "强趋势也可能带来拥挤风险",
    tag: "Tech",
    bullets: [
      "AP 提到科技股在 AI 兴奋情绪后开始承压",
      "Nvidia 财报可能影响板块情绪",
      "风控重点不是预测涨跌，而是检查暴露是否过度集中",
    ],
    accent: "#cdb4db",
  },
  {
    title: "保证金账户要看账户级风险",
    subtitle: "Margin risk is account-level risk",
    tag: "Margin",
    bullets: [
      "多个仓位同时下跌时，净值会快速变化",
      "波动率抬升会改变维持保证金安全边界",
      "真正要问：Nasdaq 再跌 5%-10%，账户会怎样？",
    ],
    accent: "#ffb703",
  },
  {
    title: "Today's Risk Checklist",
    subtitle: "收盘后检查这 6 件事",
    tag: "Checklist",
    checklist: [
      "Yield sensitivity",
      "Tech / AI concentration",
      "Margin usage",
      "Nasdaq -5% / -10% stress test",
      "Cash buffer",
      "Correlation under stress",
    ],
    accent: "#90be6d",
  },
  {
    title: "MindMarket AI",
    subtitle: "Portfolio risk dashboard for individual investors",
    tag: "Demo",
    bullets: ["VaR / CVaR", "Stress Test", "Margin Monitor", "AI Risk Digest"],
    cta: "https://mindmarket.app",
    accent: "#5dc4b8",
  },
  {
    title: "总结",
    subtitle: "指数可能平静，但账户风险可能已经在重新定价",
    tag: "Close",
    bullets: ["收益率", "科技股", "AI 拥挤交易", "保证金风险"],
    cta: "美股账户风控笔记 · mindmarket.app",
    accent: "#f0c46a",
  },
];

function htmlFor(audioPath, outName) {
  const audioUrl = `file://${audioPath}`;
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    html, body { margin: 0; background: #070b10; overflow: hidden; }
    canvas { width: 1280px; height: 720px; display: block; }
  </style>
</head>
<body>
<canvas id="c" width="1280" height="720"></canvas>
<audio id="audio" src="${audioUrl}" crossorigin="anonymous"></audio>
<script>
const slides = ${JSON.stringify(slides)};
const canvas = document.getElementById("c");
const ctx = canvas.getContext("2d");
const audio = document.getElementById("audio");

function roundRect(x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function drawText(text, x, y, maxWidth, lineHeight, font, color) {
  ctx.font = font;
  ctx.fillStyle = color;
  const words = [...String(text)];
  let line = "";
  for (let i = 0; i < words.length; i++) {
    const test = line + words[i];
    if (ctx.measureText(test).width > maxWidth && line.length > 0) {
      ctx.fillText(line, x, y);
      line = words[i];
      y += lineHeight;
    } else {
      line = test;
    }
  }
  if (line) ctx.fillText(line, x, y);
  return y;
}

function gridBackground(t) {
  const grd = ctx.createLinearGradient(0, 0, 1280, 720);
  grd.addColorStop(0, "#080d13");
  grd.addColorStop(0.55, "#111820");
  grd.addColorStop(1, "#070b10");
  ctx.fillStyle = grd;
  ctx.fillRect(0, 0, 1280, 720);

  ctx.globalAlpha = 0.16;
  ctx.strokeStyle = "#36515f";
  ctx.lineWidth = 1;
  for (let x = -80 + (t * 20 % 80); x < 1360; x += 80) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x + 220, 720); ctx.stroke();
  }
  for (let y = 40; y < 720; y += 80) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(1280, y); ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function drawChart(t, accent) {
  ctx.save();
  ctx.translate(720, 145);
  ctx.globalAlpha = 0.9;
  roundRect(0, 0, 430, 240, 18);
  ctx.fillStyle = "rgba(13,22,30,0.72)";
  ctx.fill();
  ctx.strokeStyle = "rgba(255,255,255,0.08)";
  ctx.stroke();
  ctx.font = "18px Helvetica Neue, Arial";
  ctx.fillStyle = "#aeb9c2";
  ctx.fillText("Risk Dashboard", 28, 38);
  const pts = [];
  for (let i = 0; i < 28; i++) {
    const y = 150 + Math.sin(i * 0.7 + t * 2) * 22 + i * 1.5;
    pts.push([28 + i * 14, y]);
  }
  ctx.strokeStyle = accent;
  ctx.lineWidth = 3;
  ctx.beginPath();
  pts.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]));
  ctx.stroke();
  ctx.fillStyle = "rgba(229,107,111,0.8)";
  for (let i = 0; i < 12; i++) {
    const h = 18 + Math.abs(Math.sin(i * 1.1 + t)) * 60;
    ctx.fillRect(42 + i * 30, 205 - h, 14, h);
  }
  ctx.restore();
}

function drawSlide(slide, idx, p, globalT) {
  gridBackground(globalT);
  drawChart(globalT, slide.accent);

  ctx.fillStyle = "rgba(255,255,255,0.08)";
  ctx.fillRect(0, 0, 1280, 6);
  ctx.fillStyle = slide.accent;
  ctx.fillRect(0, 0, 1280 * ((idx + p) / slides.length), 6);

  ctx.fillStyle = slide.accent;
  roundRect(78, 74, 136, 36, 18);
  ctx.fill();
  ctx.fillStyle = "#071015";
  ctx.font = "bold 17px Helvetica Neue, Arial";
  ctx.fillText(slide.tag, 102, 98);

  const titleY = 175 + Math.sin(p * Math.PI) * -8;
  drawText(slide.title, 78, titleY, 600, 60, "bold 50px Helvetica Neue, PingFang SC, Arial", "#f4f7f8");
  drawText(slide.subtitle, 80, titleY + 72, 610, 34, "24px Helvetica Neue, PingFang SC, Arial", "#c5d0d8");

  if (slide.metrics) {
    slide.metrics.forEach((m, i) => {
      const x = 80 + (i % 2) * 255;
      const y = 340 + Math.floor(i / 2) * 118;
      roundRect(x, y, 220, 82, 14);
      ctx.fillStyle = "rgba(255,255,255,0.06)";
      ctx.fill();
      ctx.fillStyle = "#9fb0bc";
      ctx.font = "17px Helvetica Neue, Arial";
      ctx.fillText(m[0], x + 20, y + 30);
      ctx.fillStyle = slide.accent;
      ctx.font = "bold 26px Helvetica Neue, Arial";
      ctx.fillText(m[1], x + 20, y + 62);
    });
  }

  if (slide.flow) {
    slide.flow.forEach((f, i) => {
      const x = 70 + i * 285;
      const y = 410;
      roundRect(x, y, 210, 70, 16);
      ctx.fillStyle = i === 1 ? "rgba(229,107,111,0.28)" : "rgba(255,255,255,0.07)";
      ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,0.10)";
      ctx.stroke();
      drawText(f, x + 18, y + 43, 175, 28, "bold 23px PingFang SC, Helvetica Neue", "#eef4f5");
      if (i < slide.flow.length - 1) {
        ctx.strokeStyle = slide.accent;
        ctx.lineWidth = 3;
        ctx.beginPath(); ctx.moveTo(x + 218, y + 35); ctx.lineTo(x + 275, y + 35); ctx.stroke();
      }
    });
  }

  if (slide.checklist) {
    slide.checklist.forEach((item, i) => {
      const x = 86 + (i % 2) * 500;
      const y = 326 + Math.floor(i / 2) * 75;
      ctx.fillStyle = slide.accent;
      ctx.beginPath(); ctx.arc(x, y, 12, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#061014";
      ctx.font = "bold 16px Helvetica Neue, Arial";
      ctx.fillText(String(i + 1), x - 5, y + 6);
      ctx.fillStyle = "#eef4f5";
      ctx.font = "bold 25px Helvetica Neue, Arial";
      ctx.fillText(item, x + 28, y + 8);
    });
  } else if (slide.bullets) {
    slide.bullets.forEach((b, i) => {
      const y = 355 + i * 56;
      ctx.fillStyle = slide.accent;
      ctx.beginPath(); ctx.arc(96, y - 8, 6, 0, Math.PI * 2); ctx.fill();
      drawText(b, 118, y, 560, 31, "24px Helvetica Neue, PingFang SC, Arial", "#edf2f4");
    });
  }

  if (slide.cta) {
    roundRect(78, 610, 520, 52, 18);
    ctx.fillStyle = "rgba(93,196,184,0.15)";
    ctx.fill();
    ctx.strokeStyle = "rgba(93,196,184,0.45)";
    ctx.stroke();
    ctx.fillStyle = "#dff9f5";
    ctx.font = "bold 24px Helvetica Neue, Arial";
    ctx.fillText(slide.cta, 102, 645);
  }

  ctx.fillStyle = "rgba(255,255,255,0.58)";
  ctx.font = "16px Helvetica Neue, Arial";
  ctx.fillText("内容仅用于教育和研究，不构成投资建议", 78, 694);
  ctx.fillText("美股账户风控笔记", 1070, 694);
}

let started = false;
async function start() {
  if (started) return;
  started = true;
  await audio.play();
  const audioCtx = new AudioContext();
  const source = audioCtx.createMediaElementSource(audio);
  const dest = audioCtx.createMediaStreamDestination();
  source.connect(dest);
  source.connect(audioCtx.destination);
  const canvasStream = canvas.captureStream(30);
  const stream = new MediaStream([
    ...canvasStream.getVideoTracks(),
    ...dest.stream.getAudioTracks(),
  ]);
  const chunks = [];
  const rec = new MediaRecorder(stream, { mimeType: "video/webm;codecs=vp9,opus", videoBitsPerSecond: 5500000 });
  rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
  rec.onstop = async () => {
    const blob = new Blob(chunks, { type: "video/webm" });
    const arr = new Uint8Array(await blob.arrayBuffer());
    window.__recording = Array.from(arr);
    window.__done = true;
  };
  const startedAt = performance.now();
  function frame() {
    const t = audio.currentTime;
    const dur = Math.max(audio.duration || 480, 1);
    const slideLen = dur / slides.length;
    const idx = Math.min(slides.length - 1, Math.floor(t / slideLen));
    const p = Math.min(1, Math.max(0, (t - idx * slideLen) / slideLen));
    drawSlide(slides[idx], idx, p, t);
    if (!audio.ended && performance.now() - startedAt < (dur + 8) * 1000) {
      requestAnimationFrame(frame);
    } else {
      drawSlide(slides[slides.length - 1], slides.length - 1, 1, t);
      setTimeout(() => rec.stop(), 700);
    }
  }
  rec.start(1000);
  frame();
}
window.startRecording = start;
audio.addEventListener("canplaythrough", start, { once: true });
audio.load();
</script>
</body>
</html>`;
}

async function main() {
  if (!fs.existsSync(AUDIO)) {
    throw new Error(`Missing audio file: ${AUDIO}`);
  }
  fs.writeFileSync(HTML, htmlFor(AUDIO, WEBM));
  const chromePath = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  const launchOptions = fs.existsSync(chromePath)
    ? {
        headless: true,
        executablePath: chromePath,
        ignoreDefaultArgs: ["--mute-audio"],
        args: ["--autoplay-policy=no-user-gesture-required"],
      }
    : {
        headless: true,
        ignoreDefaultArgs: ["--mute-audio"],
        args: ["--autoplay-policy=no-user-gesture-required"],
      };
  const browser = await chromium.launch(launchOptions);
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  page.setDefaultTimeout(20 * 60 * 1000);
  await page.goto(`file://${HTML}`);
  await page.waitForFunction(() => document.getElementById("audio").readyState >= 1);
  await page.evaluate(() => window.startRecording());
  await page.waitForFunction(() => window.__done === true, null, { timeout: 20 * 60 * 1000 });
  const data = await page.evaluate(() => window.__recording);
  fs.writeFileSync(WEBM, Buffer.from(data));
  await browser.close();
  console.log(WEBM);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
