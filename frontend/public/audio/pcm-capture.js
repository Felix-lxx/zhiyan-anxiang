/* Accumulate microphone samples without routing audible sound to speakers. */
class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super()
    this.buffer = new Float32Array(2048)
    this.used = 0
    this.stopped = false
    this.captured = 0
    this.port.onmessage = event => {
      if (event.data !== 'stop') return
      this.flush()
      this.stopped = true
      this.port.postMessage({ done: true })
    }
  }
  flush() {
    if (!this.used) return
    const samples = this.buffer.slice(0, this.used)
    this.port.postMessage({ samples }, [samples.buffer])
    this.used = 0
  }
  process(inputs) {
    if (this.stopped) return false
    const channels = inputs[0]
    if (!channels?.length) return true
    for (let i = 0; i < channels[0].length; i++) {
      let value = 0
      for (const channel of channels) value += channel[i]
      this.buffer[this.used++] = value / channels.length
      this.captured++
      if (this.used === this.buffer.length) this.flush()
      if (this.captured >= sampleRate * 30) {
        this.flush()
        this.stopped = true
        this.port.postMessage({ limit: true })
        return false
      }
    }
    return true
  }
}
registerProcessor('pcm-capture', PcmCapture)
