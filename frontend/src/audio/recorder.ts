/** Local microphone capture; uploads are owned by the visible speech control. */
export class PcmRecorder {
  private context?: AudioContext
  private stream?: MediaStream
  private node?: AudioWorkletNode
  private chunks: Float32Array[] = []
  private cancelled = false
  private peak = 0
  private flushed?: () => void

  constructor(private readonly onLimit?: () => void, private readonly onLevel?: (level:number) => void) {}

  async start() {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      throw new Error('麦克风需要 HTTPS 或本机 localhost/127.0.0.1 页面。')
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } })
    if (this.cancelled) { stream.getTracks().forEach(track => track.stop()); return }
    this.stream = stream
    const context = new AudioContext()
    this.context = context
    try {
      await context.resume()
      await context.audioWorklet.addModule(`${import.meta.env.BASE_URL}audio/pcm-capture.js`)
      if (this.cancelled) return
      const node = new AudioWorkletNode(context, 'pcm-capture')
      this.node = node
      node.port.onmessage = event => {
        if (event.data.samples) {
          const samples:Float32Array=event.data.samples
          this.chunks.push(samples)
          let energy=0
          for(const sample of samples){energy+=sample*sample;this.peak=Math.max(this.peak,Math.abs(sample))}
          const db=20*Math.log10(Math.max(1e-8,Math.sqrt(energy/Math.max(1,samples.length))))
          this.onLevel?.(Math.round(Math.max(0,Math.min(100,(db+60)/60*100))))
        }
        if (event.data.done) this.flushed?.()
        if (event.data.limit) this.onLimit?.()
      }
      const mute = context.createGain()
      mute.gain.value = 0
      context.createMediaStreamSource(stream).connect(node).connect(mute).connect(context.destination)
    } catch (error) {
      this.cancel()
      throw error
    }
  }

  async finish(): Promise<Blob> {
    const sampleRate = this.context?.sampleRate ?? 48000
    if (this.node) {
      await new Promise<void>(resolve => {
        const timeout = setTimeout(resolve, 250)
        this.flushed = () => { clearTimeout(timeout); resolve() }
        this.node!.port.postMessage('stop')
      })
    }
    const chunks = this.chunks
    this.chunks = []
    this.release()
    const length = chunks.reduce((sum, chunk) => sum + chunk.length, 0)
    if (length / sampleRate < .25) throw new Error('录音太短，请至少说一句话后再结束。')
    if(this.peak<1e-6)throw new Error('未检测到音频输入，请检查麦克风后重新录音；本次没有上传。')
    const source = new AudioBuffer({ length, sampleRate, numberOfChannels: 1 })
    let offset = 0
    for (const chunk of chunks) { source.copyToChannel(chunk, 0, offset); offset += chunk.length }
    const resampler = new OfflineAudioContext(1, Math.min(480000, Math.ceil(length * 16000 / sampleRate)), 16000)
    const player = resampler.createBufferSource()
    player.buffer = source
    player.connect(resampler.destination)
    player.start()
    const audio = await resampler.startRendering()
    const samples = audio.getChannelData(0)
    const pcm = new ArrayBuffer(samples.length * 2), view = new DataView(pcm)
    samples.forEach((sample, index) => {
      const value = Math.max(-1, Math.min(1, sample))
      view.setInt16(index * 2, Math.round(value * (value < 0 ? 32768 : 32767)), true)
    })
    return new Blob([pcm], { type: 'audio/pcm' })
  }

  cancel() {
    this.cancelled = true
    this.flushed?.()
    this.chunks = []
    this.release()
  }

  private release() {
    this.stream?.getTracks().forEach(track => track.stop())
    this.node?.disconnect()
    if (this.context && this.context.state !== 'closed') void this.context.close().catch(() => {})
    this.node = undefined
    this.context = undefined
    this.stream = undefined
  }
}
