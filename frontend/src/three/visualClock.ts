/** Cosmetic interpolation only; replay and paused frames use the exact drill time. */
export class VisualClock {
  private elapsed=Number.NaN
  private received=0
  private running=false
  at(elapsed:number,running:boolean,now:number){
    if(elapsed!==this.elapsed||running!==this.running){this.elapsed=elapsed;this.received=now;this.running=running}
    return elapsed+(running?Math.max(0,Math.min(.5,(now-this.received)/1000)):0)
  }
}
