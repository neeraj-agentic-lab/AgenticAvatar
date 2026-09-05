"use client";

/**
 * Plays raw PCM s16le chunks streamed from the gateway over WebSocket.
 * Each chunk is decoded and scheduled on a shared AudioContext.
 */
export class PCMPlayer {
  private ctx: AudioContext | null = null;
  private nextAt = 0;
  private readonly sampleRate: number;
  private readonly channels: number;

  constructor(sampleRate = 16000, channels = 1) {
    this.sampleRate = sampleRate;
    this.channels = channels;
  }

  private _ensureContext() {
    if (!this.ctx || this.ctx.state === "closed") {
      this.ctx = new AudioContext({ sampleRate: this.sampleRate });
      this.nextAt = 0;
    }
    return this.ctx;
  }

  feed(pcm: ArrayBuffer) {
    const ctx = this._ensureContext();
    const samples = new Int16Array(pcm);
    const frameCount = samples.length / this.channels;
    const buffer = ctx.createBuffer(this.channels, frameCount, this.sampleRate);

    for (let ch = 0; ch < this.channels; ch++) {
      const channelData = buffer.getChannelData(ch);
      for (let i = 0; i < frameCount; i++) {
        channelData[i] = samples[i * this.channels + ch] / 32768;
      }
    }

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);

    const now = ctx.currentTime;
    const startAt = Math.max(now, this.nextAt);
    source.start(startAt);
    this.nextAt = startAt + buffer.duration;
  }

  stop() {
    this.ctx?.close();
    this.ctx = null;
    this.nextAt = 0;
  }
}
