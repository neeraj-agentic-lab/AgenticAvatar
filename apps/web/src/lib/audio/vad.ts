/**
 * Simple energy-based Voice Activity Detector.
 *
 * Runs entirely in the browser on each 20ms PCM frame.
 * Emits onSpeechStart / onSpeechEnd callbacks used to drive
 * speech.started / speech.ended WebSocket events.
 *
 * For production: swap for @ricky0123/vad-web (ONNX neural VAD)
 * which has far better accuracy on noisy environments.
 */

interface VADOptions {
  /** RMS energy threshold 0–1. Frames above = speech. Default 0.01 */
  threshold?: number;
  /** Consecutive speech frames before firing onSpeechStart. Default 3 (~60ms) */
  speechFrames?: number;
  /** Consecutive silence frames before firing onSpeechEnd. Default 25 (~500ms) */
  silenceFrames?: number;
}

export class VoiceActivityDetector {
  private threshold: number;
  private speechFrames: number;
  private silenceFrames: number;

  private speechCount = 0;
  private silenceCount = 0;
  private isSpeaking = false;

  onSpeechStart: (() => void) | null = null;
  onSpeechEnd: (() => void) | null = null;
  onAudioLevel: ((level: number) => void) | null = null;

  constructor(options: VADOptions = {}) {
    this.threshold = options.threshold ?? 0.01;
    this.speechFrames = options.speechFrames ?? 3;
    this.silenceFrames = options.silenceFrames ?? 25;
  }

  processFrame(pcm: ArrayBuffer): void {
    const samples = new Int16Array(pcm);
    const level = this._rms(samples);

    this.onAudioLevel?.(level);

    if (level > this.threshold) {
      this.speechCount++;
      this.silenceCount = 0;
      if (!this.isSpeaking && this.speechCount >= this.speechFrames) {
        this.isSpeaking = true;
        this.onSpeechStart?.();
      }
    } else {
      this.silenceCount++;
      this.speechCount = 0;
      if (this.isSpeaking && this.silenceCount >= this.silenceFrames) {
        this.isSpeaking = false;
        this.onSpeechEnd?.();
      }
    }
  }

  reset(): void {
    this.speechCount = 0;
    this.silenceCount = 0;
    if (this.isSpeaking) {
      this.isSpeaking = false;
      this.onSpeechEnd?.();
    }
  }

  private _rms(samples: Int16Array): number {
    let sum = 0;
    for (let i = 0; i < samples.length; i++) {
      const s = samples[i] / 32768;
      sum += s * s;
    }
    return Math.sqrt(sum / samples.length);
  }
}
