import AVFoundation
import Foundation

func usage() -> Never {
    fputs("usage: enhance_voice.swift <input.m4a> <output.wav>\n", stderr)
    exit(2)
}

if CommandLine.arguments.count != 3 {
    usage()
}

let inputURL = URL(fileURLWithPath: CommandLine.arguments[1])
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2])

let asset = AVURLAsset(url: inputURL)
guard let track = asset.tracks(withMediaType: .audio).first else {
    fatalError("No audio track found")
}

var sampleRate = 48_000.0
var channels = 1
if let desc = track.formatDescriptions.first {
    let fmt = desc as! CMAudioFormatDescription
    if let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(fmt) {
        sampleRate = asbd.pointee.mSampleRate
        channels = Int(asbd.pointee.mChannelsPerFrame)
    }
}

let reader = try AVAssetReader(asset: asset)
let outputSettings: [String: Any] = [
    AVFormatIDKey: kAudioFormatLinearPCM,
    AVLinearPCMIsFloatKey: true,
    AVLinearPCMBitDepthKey: 32,
    AVLinearPCMIsNonInterleaved: false,
    AVSampleRateKey: sampleRate,
    AVNumberOfChannelsKey: channels
]
let output = AVAssetReaderTrackOutput(track: track, outputSettings: outputSettings)
output.alwaysCopiesSampleData = false
reader.add(output)
reader.startReading()

var mono: [Float] = []
while let sampleBuffer = output.copyNextSampleBuffer() {
    guard let blockBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else { continue }
    let length = CMBlockBufferGetDataLength(blockBuffer)
    var data = Data(count: length)
    data.withUnsafeMutableBytes { rawBuffer in
        if let base = rawBuffer.baseAddress {
            _ = CMBlockBufferCopyDataBytes(blockBuffer, atOffset: 0, dataLength: length, destination: base)
        }
    }
    data.withUnsafeBytes { rawBuffer in
        let floats = rawBuffer.bindMemory(to: Float.self)
        let frameTotal = floats.count / max(channels, 1)
        for frame in 0..<frameTotal {
            var s: Float = 0
            for c in 0..<channels {
                s += floats[frame * channels + c]
            }
            mono.append(s / Float(max(channels, 1)))
        }
    }
}

if reader.status == .failed {
    fatalError("Reader failed: \(reader.error?.localizedDescription ?? "unknown error")")
}

let frames = mono.count

// Gentle high-pass filter to reduce room rumble.
let cutoff = 85.0
let dt = 1.0 / sampleRate
let rc = 1.0 / (2.0 * Double.pi * cutoff)
let alpha = Float(rc / (rc + dt))
var hp = [Float](repeating: 0, count: mono.count)
var prevY: Float = 0
var prevX: Float = 0
for i in mono.indices {
    let y = alpha * (prevY + mono[i] - prevX)
    hp[i] = y
    prevY = y
    prevX = mono[i]
}

// Compress long dead air while preserving natural thinking pauses.
let chunkSize = max(1, Int(sampleRate * 0.02)) // 20 ms
let quietThreshold: Float = 0.010
let maxQuietChunksToKeep = Int(0.55 / 0.02)
var quietRun = 0
var paced: [Float] = []
paced.reserveCapacity(hp.count)

var idx = 0
while idx < hp.count {
    let end = min(idx + chunkSize, hp.count)
    var sum: Float = 0
    for i in idx..<end {
        sum += hp[i] * hp[i]
    }
    let rms = sqrt(sum / Float(max(1, end - idx)))
    let isQuiet = rms < quietThreshold
    if isQuiet {
        quietRun += 1
        if quietRun <= maxQuietChunksToKeep {
            paced.append(contentsOf: hp[idx..<end])
        }
    } else {
        quietRun = 0
        paced.append(contentsOf: hp[idx..<end])
    }
    idx = end
}

// Soft gate + light broadcast-style compression.
let gate: Float = 0.004
let threshold: Float = 0.16
let ratio: Float = 2.6
var processed = [Float](repeating: 0, count: paced.count)
for i in paced.indices {
    var x = paced[i]
    if abs(x) < gate {
        x *= 0.35
    }
    let sign: Float = x < 0 ? -1 : 1
    let mag = abs(x)
    if mag > threshold {
        x = sign * (threshold + (mag - threshold) / ratio)
    }
    processed[i] = x
}

var peak: Float = 0.0001
var rmsSum: Float = 0
for x in processed {
    peak = max(peak, abs(x))
    rmsSum += x * x
}
let rms = sqrt(rmsSum / Float(max(1, processed.count)))

// Aim for strong but non-clipped spoken-word level.
let targetPeak: Float = 0.88
let targetRMS: Float = 0.105
let gainByPeak = targetPeak / peak
let gainByRMS = targetRMS / max(rms, 0.0001)
let gain = min(gainByPeak, gainByRMS)
for i in processed.indices {
    processed[i] = max(-0.95, min(0.95, processed[i] * gain))
}

let outFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: sampleRate, channels: 1, interleaved: false)!
guard let outBuffer = AVAudioPCMBuffer(pcmFormat: outFormat, frameCapacity: AVAudioFrameCount(processed.count)) else {
    fatalError("Unable to allocate output buffer")
}
outBuffer.frameLength = AVAudioFrameCount(processed.count)
let outData = outBuffer.floatChannelData![0]
for i in processed.indices {
    outData[i] = processed[i]
}

try? FileManager.default.removeItem(at: outputURL)
let outputFile = try AVAudioFile(forWriting: outputURL, settings: outFormat.settings)
try outputFile.write(from: outBuffer)

let inputDuration = Double(frames) / sampleRate
let outputDuration = Double(processed.count) / sampleRate
print(String(format: "input: %.2fs output: %.2fs peak: %.3f rms: %.3f gain: %.2fx", inputDuration, outputDuration, peak, rms, gain))
