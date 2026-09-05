/**
 * Manages microphone capture via AudioWorklet.
 * Emits 16kHz PCM Int16 frames on the onFrame callback.
 */
export class MicrophoneCapture {
  private context: AudioContext | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private stream: MediaStream | null = null;

  onFrame: ((pcm: ArrayBuffer) => void) | null = null;

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        sampleRate: 48000,
        channelCount: 1,
      },
    });

    this.context = new AudioContext({ sampleRate: 48000 });
    await this.context.audioWorklet.addModule("/audio-processor.js");

    this.workletNode = new AudioWorkletNode(
      this.context,
      "audio-capture-processor",
      { processorOptions: { targetSampleRate: 16000 } }
    );

    this.workletNode.port.onmessage = (e) => {
      if (e.data.type === "frame" && this.onFrame) {
        this.onFrame(e.data.pcm);
      }
    };

    this.sourceNode = this.context.createMediaStreamSource(this.stream);
    this.sourceNode.connect(this.workletNode);
    // Do not connect workletNode to destination — we don't want local playback
  }

  getAudioLevel(): number {
    // Used for mic level indicator — reads from an AnalyserNode
    return 0; // TODO: add AnalyserNode for level metering
  }

  stop(): void {
    this.sourceNode?.disconnect();
    this.workletNode?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.context?.close();
    this.context = null;
    this.workletNode = null;
    this.sourceNode = null;
    this.stream = null;
  }
}
