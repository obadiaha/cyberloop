/**
 * PCM Player AudioWorklet Processor
 *
 * Ring-buffer based audio playback on the audio thread.
 * Receives PCM16 audio chunks via port.postMessage() from the main thread,
 * converts to float32, and fills the output buffer from a ring buffer.
 *
 * This eliminates stuttering caused by main-thread scheduling jitter
 * (the old AudioBufferSourceNode approach).
 *
 * Audio format: PCM16 little-endian, 24kHz, mono
 */
class PCMPlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();

    // Ring buffer: 24kHz * 180 seconds = enough for a full interview
    this.bufferSize = 24000 * 180;
    this.buffer = new Float32Array(this.bufferSize);
    this.writeIndex = 0;
    this.readIndex = 0;

    this.port.onmessage = (event) => {
      // Handle control commands
      if (event.data && event.data.command === 'endOfAudio') {
        // Clear the buffer (skip to write position)
        this.readIndex = this.writeIndex;
        return;
      }

      // Decode incoming PCM16 data (ArrayBuffer) to float32 ring buffer
      const int16Samples = new Int16Array(event.data);
      this._enqueue(int16Samples);
    };
  }

  _enqueue(int16Samples) {
    for (let i = 0; i < int16Samples.length; i++) {
      // Convert 16-bit signed integer to float [-1, 1]
      this.buffer[this.writeIndex] = int16Samples[i] / 32768;
      this.writeIndex = (this.writeIndex + 1) % this.bufferSize;

      // Overflow: overwrite oldest samples
      if (this.writeIndex === this.readIndex) {
        this.readIndex = (this.readIndex + 1) % this.bufferSize;
      }
    }
  }

  process(inputs, outputs, parameters) {
    const output = outputs[0];
    const framesPerBlock = output[0].length;

    for (let frame = 0; frame < framesPerBlock; frame++) {
      // Read from ring buffer (outputs silence if underflowing)
      output[0][frame] = this.buffer[this.readIndex];
      if (output.length > 1) {
        output[1][frame] = this.buffer[this.readIndex];
      }

      // Advance read index unless we've caught up to write (underflow)
      if (this.readIndex !== this.writeIndex) {
        this.readIndex = (this.readIndex + 1) % this.bufferSize;
      }
    }

    // Keep processor alive
    return true;
  }
}

registerProcessor('pcm-player-processor', PCMPlayerProcessor);
