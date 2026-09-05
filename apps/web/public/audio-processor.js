/**
 * AudioWorklet processor — runs on the audio render thread.
 * Captures 20ms PCM frames, resamples to 16kHz, sends to the main thread.
 */
class AudioCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this._targetSampleRate = options.processorOptions?.targetSampleRate ?? 16000;
    this._sourceSampleRate = sampleRate; // global from AudioWorkletGlobalScope
    this._ratio = this._sourceSampleRate / this._targetSampleRate;
    this._buffer = [];
    // 20ms of samples at target rate
    this._frameSize = Math.floor(this._targetSampleRate * 0.02);
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;

    const samples = input[0]; // mono Float32

    // Downsample: simple decimation — good enough for speech
    for (let i = 0; i < samples.length; i += this._ratio) {
      this._buffer.push(samples[Math.floor(i)]);
    }

    // Emit complete 20ms frames
    while (this._buffer.length >= this._frameSize) {
      const frame = this._buffer.splice(0, this._frameSize);
      // Convert Float32 → PCM Int16
      const pcm = new Int16Array(frame.length);
      for (let i = 0; i < frame.length; i++) {
        pcm[i] = Math.max(-32768, Math.min(32767, frame[i] * 32768));
      }
      this.port.postMessage({ type: "frame", pcm: pcm.buffer }, [pcm.buffer]);
    }

    return true;
  }
}

registerProcessor("audio-capture-processor", AudioCaptureProcessor);
