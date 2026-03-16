/**
 * PCM Recorder AudioWorklet Processor
 *
 * Captures microphone audio on the audio thread and posts
 * Float32Array samples to the main thread via port.postMessage().
 *
 * The main thread converts to PCM16 and sends over WebSocket.
 *
 * Audio format: Float32, 16kHz, mono
 */
class PCMRecorderProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
  }

  process(inputs, outputs, parameters) {
    if (inputs.length > 0 && inputs[0].length > 0) {
      const inputChannel = inputs[0][0];
      // Copy buffer to avoid recycled memory issues
      const copy = new Float32Array(inputChannel);
      this.port.postMessage(copy);
    }
    return true;
  }
}

registerProcessor('pcm-recorder-processor', PCMRecorderProcessor);
