const fs = require("fs");
const path = require("path");

if (process.argv.length < 5) {
  console.error("usage: node concat_wav.js <out.wav> <in1.wav> <in2.wav> [...]");
  process.exit(2);
}

const out = process.argv[2];
const inputs = process.argv.slice(3);

function parseWav(file) {
  const buf = fs.readFileSync(file);
  if (buf.toString("ascii", 0, 4) !== "RIFF" || buf.toString("ascii", 8, 12) !== "WAVE") {
    throw new Error(`${file} is not a RIFF/WAVE file`);
  }
  let offset = 12;
  let fmt = null;
  let data = null;
  while (offset + 8 <= buf.length) {
    const id = buf.toString("ascii", offset, offset + 4);
    const size = buf.readUInt32LE(offset + 4);
    const start = offset + 8;
    if (id === "fmt ") fmt = buf.subarray(start, start + size);
    if (id === "data") data = buf.subarray(start, start + size);
    offset = start + size + (size % 2);
  }
  if (!fmt || !data) throw new Error(`${file} missing fmt or data chunk`);
  return { fmt, data };
}

const parsed = inputs.map(parseWav);
const fmt0 = parsed[0].fmt;
for (const p of parsed) {
  if (!p.fmt.equals(fmt0)) throw new Error("input WAV formats differ");
}

const silence = Buffer.alloc(48000 * 2); // 1 sec, mono 16-bit at 48k
const dataParts = [];
parsed.forEach((p, i) => {
  if (i) dataParts.push(silence);
  dataParts.push(p.data);
});
const data = Buffer.concat(dataParts);

const header = Buffer.alloc(12);
header.write("RIFF", 0);
header.writeUInt32LE(4 + (8 + fmt0.length) + (8 + data.length), 4);
header.write("WAVE", 8);
const fmtHeader = Buffer.alloc(8);
fmtHeader.write("fmt ", 0);
fmtHeader.writeUInt32LE(fmt0.length, 4);
const dataHeader = Buffer.alloc(8);
dataHeader.write("data", 0);
dataHeader.writeUInt32LE(data.length, 4);

fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, Buffer.concat([header, fmtHeader, fmt0, dataHeader, data]));
console.log(out);
