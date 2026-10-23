import * as THREE from 'three'

/** Camera-facing instanced particles: two draw calls, simulation-clock driven, deterministic on replay. */
export class FireEffects {
  readonly group=new THREE.Group()
  private flame: THREE.InstancedMesh
  private smoke: THREE.InstancedMesh
  private transform=new THREE.Object3D()
  private color=new THREE.Color()
  constructor() {
    const geometry=new THREE.PlaneGeometry(1,1)
    const makeMaterial=(fire:boolean)=>new THREE.ShaderMaterial({
      transparent:true,depthWrite:false,side:THREE.DoubleSide,blending:THREE.NormalBlending,
      uniforms:{uFire:{value:fire?1:0}},
      vertexShader:`varying vec2 vUv; varying vec3 vColor;
        void main(){ vUv=uv; vColor=instanceColor; gl_Position=projectionMatrix*modelViewMatrix*instanceMatrix*vec4(position,1.0); }`,
      fragmentShader:`uniform float uFire; varying vec2 vUv; varying vec3 vColor;
        float noise(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
        float smoothNoise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.0-2.0*f);return mix(mix(noise(i),noise(i+vec2(1,0)),f.x),mix(noise(i+vec2(0,1)),noise(i+vec2(1,1)),f.x),f.y);}
        void main(){vec2 p=(vUv-.5)*2.0;float n=smoothNoise(vUv*7.0)*.55+smoothNoise(vUv*17.0)*.25;
          if(uFire>.5)p.x/=max(.12,1.0-vUv.y*.84);
          float edge=1.0-smoothstep(.25,1.0,length(p)+n*.28);float alpha=edge*(uFire>.5?.72:.16);
          if(alpha<.005)discard; gl_FragColor=vec4(vColor,alpha);
          #include <tonemapping_fragment>
          #include <colorspace_fragment>
        }`
    })
    this.flame=new THREE.InstancedMesh(geometry,makeMaterial(true),64)
    this.smoke=new THREE.InstancedMesh(geometry,makeMaterial(false),88)
    for(const mesh of [this.flame,this.smoke]) { mesh.frustumCulled=false;mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage); for(let i=0;i<mesh.count;i++)mesh.setColorAt(i,new THREE.Color(1,1,1)); this.group.add(mesh) }
  }
  update(seconds:number,intensity:number,radius:number,wind:string,camera:THREE.Camera,quality:number,indoor=false) {
    const strength=THREE.MathUtils.clamp(intensity/100,0,1)
    this.group.visible=strength>0
    const direction=new THREE.Vector3(wind.includes('东')?-1:wind.includes('西')?1:.2,0,wind.includes('北')?1:wind.includes('南')?-1:.1).normalize()
    for(const [mesh,isFlame,max] of [[this.flame,true,64],[this.smoke,false,88]] as const) {
      mesh.visible=isFlame||!indoor
      mesh.count=Math.round(max*quality)
      for(let i=0;i<mesh.count;i++) {
        const phase=(seconds*(isFlame?.4:.095)+i*.61803398875)%1
        const angle=i*2.39996, spread=isFlame?1.25:1.5+phase*Math.min(7,radius*.12)
        const drift=isFlame?phase*.3:phase*phase*(3+radius*.18)
        this.transform.position.set(Math.sin(angle)*spread+direction.x*drift,(isFlame?.45:3)+phase*(isFlame?2+strength*4:12+strength*9),Math.cos(angle)*spread+direction.z*drift)
        this.transform.quaternion.copy(camera.quaternion)
        const size=isFlame?(1-phase)*(.8+strength*2):1.4+phase*(3+radius*.08)
        this.transform.scale.set(size,isFlame?size*1.8:size,1);this.transform.updateMatrix();mesh.setMatrixAt(i,this.transform.matrix)
        if(isFlame)this.color.setRGB(2.4, .12+(1-phase)*.65, .012+(1-phase)*.035)
        else this.color.setRGB(.035+phase*.065,.041+phase*.065,.043+phase*.065)
        mesh.setColorAt(i,this.color)
      }
      mesh.instanceMatrix.needsUpdate=true;mesh.instanceColor!.needsUpdate=true
    }
  }
}
