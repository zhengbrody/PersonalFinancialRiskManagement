const fs = require("fs");
const path = require("path");
const { chromium } = require(
  "/Users/zhengdong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright"
);

if (process.argv.length !== 4) {
  console.error("usage: node enhance_voice_browser.js <input.m4a> <output.wav>");
  process.exit(2);
}

const input = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
const inputBase64 = fs.readFileSync(input).toString("base64");

async function main() {
  const chromePath = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  const browser = await chromium.launch({
    headless: true,
    executablePath: fs.existsSync(chromePath) ? chromePath : undefined,
    args: ["--autoplay-policy=no-user-gesture-required"],
  });
  const page = await browser.newPage();
  page.setDefaultTimeout(5 * 60 * 1000);
  await page.setContent("<html><body></body></html>");
  const result = await page.evaluate(async (b64) => {
    function b64ToArrayBuffer(base64) {
      const binary = atob(base64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      return bytes.buffer;
    }

    function encodeWav(samples, sampleRate) {
      const bytesPerSample = 2;
      const blockAlign = bytesPerSample;
      const buffer = new ArrayBuffer(44 + samples.length * bytesPerSample);
      const view = new DataView(buffer);
      function writeString(offset, str) {
        for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
      }
      writeString(0, "RIFF");
      view.setUint32(4, 36 + samples.length * bytesPerSample, true);
      writeString(8, "WAVE");
      writeString(12, "fmt ");
      view.setUint32(16, 16, true);
      view.setUint16(20, 1, true);
      view.setUint16(22, 1, true);
      view.setUint32(24, sampleRate, true);
      view.setUint32(28, sampleRate * blockAlign, true);
      view.setUint16(32, blockAlign, true);
      view.setUint16(34, 16, true);
      writeString(36, "data");
      view.setUint32(40, samples.length * bytesPerSample, true);
      let offset = 44;
      for (let i = 0; i < samples.length; i++, offset += 2) {
        const s = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      }
      return new Uint8Array(buffer);
    }

    const ctx = new AudioContext();
    const audioBuffer = await ctx.decodeAudioData(b64ToArrayBuffer(b64));
    const sr = audioBuffer.sampleRate;
    const channels = audioBuffer.numberOfChannels;
    const frames = audioBuffer.length;
    let mono = new Float32Array(frames);
    for (let c = 0; c < channels; c++) {
      const data = audioBuffer.getChannelData(c);
      for (let i = 0; i < frames; i++) mono[i] += data[i] / channels;
    }

    // High-pass filter around 85 Hz.
    const cutoff = 85;
    const dt = 1 / sr;
    const rc = 1 / (2 * Math.PI * cutoff);
    const alpha = rc / (rc + dt);
    const hp = new Float32Array(frames);
    let prevY = 0, prevX = 0;
    for (let i = 0; i < frames; i++) {
      const y = alpha * (prevY + mono[i] - prevX);
      hp[i] = y;
      prevY = y;
      prevX = mono[i];
    }

    // Compress only long dead-air pauses; keep natural short thinking pauses.
    const chunkSize = Math.max(1, Math.floor(sr * 0.02));
    const quietThreshold = 0.010;
    const keepQuietChunks = Math.floor(0.55 / 0.02);
    let quietRun = 0;
    const paced = [];
    for (let idx = 0; idx < hp.length; idx += chunkSize) {
      const end = Math.min(idx + chunkSize, hp.length);
      let sum = 0;
      for (let i = idx; i < end; i++) sum += hp[i] * hp[i];
      const rms = Math.sqrt(sum / Math.max(1, end - idx));
      if (rms < quietThreshold) {
        quietRun++;
        if (quietRun <= keepQuietChunks) {
          for (let i = idx; i < end; i++) paced.push(hp[i]);
        }
      } else {
        quietRun = 0;
        for (let i = idx; i < end; i++) paced.push(hp[i]);
      }
    }

    // Soft gate and light compressor.
    const gate = 0.004;
    const threshold = 0.16;
    const ratio = 2.6;
    let processed = new Float32Array(paced.length);
    let peak = 0.0001;
    let rmsSum = 0;
    for (let i = 0; i < paced.length; i++) {
      let x = paced[i];
      if (Math.abs(x) < gate) x *= 0.35;
      const sign = x < 0 ? -1 : 1;
      const mag = Math.abs(x);
      if (mag > threshold) x = sign * (threshold + (mag - threshold) / ratio);
      processed[i] = x;
      peak = Math.max(peak, Math.abs(x));
      rmsSum += x * x;
    }
    const rms = Math.sqrt(rmsSum / Math.max(1, processed.length));
    const gain = Math.min(0.88 / peak, 0.105 / Math.max(rms, 0.0001));
    for (let i = 0; i < processed.length; i++) {
      processed[i] = Math.max(-0.95, Math.min(0.95, processed[i] * gain));
    }

    const wav = encodeWav(processed, sr);
    let binary = "";
    const step = 0x8000;
    for (let i = 0; i < wav.length; i += step) {
      binary += String.fromCharCode.apply(null, wav.subarray(i, i + step));
    }
    return {
      base64: btoa(binary),
      inputDuration: frames / sr,
      outputDuration: processed.length / sr,
      sampleRate: sr,
      peak,
      rms,
      gain,
    };
  }, inputBase64);
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, Buffer.from(result.base64, "base64"));
  await browser.close();
  console.log(JSON.stringify({
    output,
    inputDuration: result.inputDuration,
    outputDuration: result.outputDuration,
    sampleRate: result.sampleRate,
    gain: result.gain,
  }, null, 2));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
