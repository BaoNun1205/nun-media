/*
 * Adapted from FreeCut's MIT-licensed WebGPU effect pipeline and effect
 * catalogue (https://github.com/walterlow/freecut). See FREECUT_LICENSE.md.
 * This is intentionally a small, self-contained runtime for Nun Media rather
 * than a copy of FreeCut's editor/compositor.
 */
import { effectDefinitionForItem, type VideoEffectDefinition } from '../config/videoEffects';
import type { TimelineItem } from '../types/studio';

type Gpu = any;
type EffectPass = { kind: number; params: Record<string, unknown> };
type VisualSource = HTMLVideoElement | HTMLImageElement | HTMLCanvasElement;

const WGSL = /* wgsl */ `
struct V { @builtin(position) pos: vec4f, @location(0) uv: vec2f };
struct P { a: vec4f, b: vec4f };
@vertex fn vs(@builtin(vertex_index) i:u32) -> V { var p=array<vec2f,3>(vec2f(-1.,-1.),vec2f(3.,-1.),vec2f(-1.,3.)); var o:V; o.pos=vec4f(p[i],0.,1.); o.uv=(p[i]+vec2f(1.))*0.5; return o; }
@group(0) @binding(0) var s:sampler; @group(0) @binding(1) var tex:texture_2d<f32>; @group(0) @binding(2) var<uniform> p:P;
fn hash(v:vec2f)->f32{return fract(sin(dot(v,vec2f(12.9898,78.233)))*43758.5453);}
fn lum(c:vec3f)->f32{return dot(c,vec3f(.2126,.7152,.0722));}
fn sample(u:vec2f)->vec4f{return textureSample(tex,s,clamp(u,vec2f(0.),vec2f(1.)));}
fn blur(u:vec2f,r:f32)->vec4f{let q=vec2f(1./p.b.x,1./p.b.y)*r; var c=sample(u)*.2; c+=sample(u+vec2f(q.x,0.))*.1; c+=sample(u-vec2f(q.x,0.))*.1; c+=sample(u+vec2f(0.,q.y))*.1; c+=sample(u-vec2f(0.,q.y))*.1; c+=sample(u+q)*.1; c+=sample(u-q)*.1; c+=sample(u+vec2f(q.x,-q.y))*.1; c+=sample(u+vec2f(-q.x,q.y))*.1; return c;}
@fragment fn fs(v:V)->@location(0) vec4f { let u=v.uv; let k=i32(p.b.w); let t=p.b.z; var c=sample(u);
 if(k==1){let n=hash(floor(u*(120./max(.1,p.a.y)))+t*p.a.x)*2.-1.; c.rgb=clamp(c.rgb+vec3f(n*p.a.x),vec3f(0.),vec3f(1.));}
 else if(k==2){let d=length((u-.5)*2.);let m=1.-smoothstep(p.a.y,p.a.y+max(.01,p.a.z),d);c.rgb*=mix(1.,m,p.a.x);}
 else if(k==3){let n=hash(floor(u*vec2f(400.,240.))+floor(t*p.a.y))*2.-1.;let off=vec2f(n*p.a.x*.012,0.);c=vec4f(sample(u+off).r,sample(u).g,sample(u-off).b,c.a);c.rgb*=1.-mod(floor(u.y*p.b.y)+floor(t*30.),2.)*.12*p.a.x;}
 else if(k==4){let q=u-.5;let r=dot(q,q)*p.a.y;c=sample(.5+q*(1.+r));c.rgb*=1.-mod(floor(u.y*p.b.y),2.)*.16*p.a.x;}
 else if(k==5){c.rgb*=1.-step(.5,fract(u.y*p.a.y))*.55*p.a.x;}
 else if(k==6){let d=vec2f(cos(p.a.y),sin(p.a.y))*p.a.x;c=vec4f(sample(u+d).r,c.g,sample(u-d).b,c.a);}
 else if(k==7){let b=floor(u.y*18.+floor(t*p.a.y));let d=(hash(vec2f(b,t))-.5)*p.a.x*.06;c=vec4f(sample(u+vec2f(d,0.)).r,sample(u).g,sample(u-vec2f(d,0.)).b,c.a);}
 else if(k==8){let g=floor(u*max(2.,p.a.y));let active=step(.73,hash(g+floor(t)*.17));let d=(hash(g+7.)-.5)*p.a.x*.16*active;c=sample(u+vec2f(d,0.));}
 else if(k==9){let b=blur(u,max(1.,p.a.y));c.rgb=1.-(1.-c.rgb)*(1.-b.rgb*p.a.x);}
 else if(k==10){c=blur(u,p.a.x);}
 else if(k==11){let q=vec2f(p.a.x/p.b.x,p.a.x/p.b.y);c=sample((floor(u/q)+.5)*q);}
 else if(k==12){let b=blur(u,1.);c.rgb=clamp(c.rgb+(c.rgb-b.rgb)*p.a.x,vec3f(0.),vec3f(1.));}
 else if(k==13){let l=max(2.,p.a.x);c.rgb=floor(c.rgb*(l-1.)+.5)/(l-1.);}
 else if(k==14){let cell=max(2.,p.a.x);let q=fract(u*p.b.xy/cell)-.5;let d=length(q)*2.;let l=lum(sample((floor(u*p.b.xy/cell)+.5)*cell/p.b.xy).rgb);c.rgb=mix(c.rgb,vec3f(step(d,l)),p.a.y);}
 else if(k==15){c=sample(u+vec2f(sin(u.y*18.+t*p.a.y)*p.a.x,sin(u.x*15.+t*p.a.y)*p.a.x));}
 else if(k==16){let q=u-.5;let r=length(q);let a=atan2(q.y,q.x)+p.a.x*max(0.,1.-r/max(.01,p.a.y));c=sample(.5+vec2f(cos(a),sin(a))*r);}
 else if(k==17){let q=u-.5;let a=atan2(q.y,q.x)+p.a.y;let seg=max(2.,p.a.x);let fold=abs(fract(a/(6.283185/seg))-.5)*6.283185/seg;c=sample(.5+vec2f(cos(fold),sin(fold))*length(q));}
 else if(k==18){let m=select(vec2f(1.-u.x,u.y),vec2f(u.x,1.-u.y),p.a.x>.5);c=sample(m);}
 else if(k==19){let q=u-.5;let r=length(q);let d=sin(r*55.-t*p.a.y*6.)*p.a.x;c=sample(u+normalize(q+vec2f(.0001))*d);}
 else if(k==20){let q=vec2f(p.a.y/p.b.x,0.);var best=c;for(var i:i32=-4;i<=4;i++){let x=sample(u+q*f32(i));if(lum(x.rgb)>lum(best.rgb)){best=x;}}c=mix(c,best,p.a.x);}
 else if(k==21){let l=lum(c.rgb);let gray=vec3f(l);c.rgb=(c.rgb-.5)*p.a.y+.5+vec3f(p.a.x);c.rgb=mix(gray,c.rgb,p.a.z);}
 return vec4f(clamp(c.rgb,vec3f(0.),vec3f(1.)),c.a); }
`;

function values(def: VideoEffectDefinition, params: Record<string, unknown>) {
  const ordered = def.params.map((item) => Number(params[item.key] ?? item.default));
  return [ordered[0] ?? 0, ordered[1] ?? 0, ordered[2] ?? 0, ordered[3] ?? 0];
}

/**
 * Software safety net for embedded browsers without a WebGPU adapter. It is a
 * pixel renderer (not a CSS approximation) and deliberately shares the same
 * registry/parameter values as the GPU path. The result is resolution-capped
 * so a missing adapter never makes the Program Monitor unusable.
 */
class CanvasEffectFallback {
  render(source: VisualSource, canvas: HTMLCanvasElement, items: TimelineItem[], time: number) {
    const sourceWidth = source instanceof HTMLVideoElement ? source.videoWidth : source instanceof HTMLImageElement ? source.naturalWidth : source.width;
    const sourceHeight = source instanceof HTMLVideoElement ? source.videoHeight : source instanceof HTMLImageElement ? source.naturalHeight : source.height;
    if (sourceWidth < 2 || sourceHeight < 2) return false;
    const scale = Math.min(1, 1280 / sourceWidth, 720 / sourceHeight);
    const width = Math.max(2, Math.round(sourceWidth * scale)); const height = Math.max(2, Math.round(sourceHeight * scale));
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
    const context = canvas.getContext('2d', { willReadFrequently: true }); if (!context) return false;
    context.clearRect(0, 0, width, height); context.drawImage(source, 0, 0, width, height);
    for (const item of items) { const def = effectDefinitionForItem(item); if (def) this.apply(context, width, height, def, item.params || {}, time); }
    return true;
  }
  private apply(context: CanvasRenderingContext2D, width: number, height: number, def: VideoEffectDefinition, params: Record<string, unknown>, time: number) {
    const [a = 0, b = 0, c = 0] = values(def, params); const image = context.getImageData(0, 0, width, height); const data = image.data;
    const index = (x: number, y: number) => (Math.max(0, Math.min(height - 1, y | 0)) * width + Math.max(0, Math.min(width - 1, x | 0))) * 4;
    const copy = new Uint8ClampedArray(data); const read = (x: number, y: number, channel: number) => copy[index(x, y) + channel];
    const noise = (x: number, y: number) => { const n = Math.sin(x * 12.9898 + y * 78.233 + time * 37.719) * 43758.5453; return n - Math.floor(n); };
    const remap = (fn: (x: number, y: number) => [number, number]) => { for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) { const [sx, sy] = fn(x, y); const i = index(x, y); data[i] = read(sx, sy, 0); data[i + 1] = read(sx, sy, 1); data[i + 2] = read(sx, sy, 2); } };
    const rgbShift = (amount: number, angle = 0) => { const dx = Math.round(Math.cos(angle) * amount); const dy = Math.round(Math.sin(angle) * amount); for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) { const i = index(x, y); data[i] = read(x + dx, y + dy, 0); data[i + 2] = read(x - dx, y - dy, 2); } };
    switch (def.gpuKind) {
      case 1: for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) { const i = index(x, y); const n = (noise(x, y) - .5) * 255 * a; data[i] += n; data[i + 1] += n; data[i + 2] += n; } break;
      case 2: for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) { const i = index(x, y); const dx = x / width - .5; const dy = y / height - .5; const d = Math.sqrt(dx * dx + dy * dy) * 2; const v = 1 - Math.max(0, Math.min(1, (d - b) / Math.max(.01, c))) * a; data[i] *= v; data[i + 1] *= v; data[i + 2] *= v; } break;
      case 3: case 4: rgbShift(Math.max(1, Math.round(a * 10)), 0); for (let y = 0; y < height; y++) if ((y + Math.floor(time * 30)) % Math.max(2, Math.round(b)) < 1) for (let x = 0; x < width; x++) { const i = index(x, y); data[i] *= .82; data[i + 1] *= .82; data[i + 2] *= .82; } if (def.gpuKind === 4) { for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) { const i = index(x, y); const v = 1 - a * Math.max(0, Math.sqrt(((x / width) - .5) ** 2 + ((y / height) - .5) ** 2) * 1.9 - .2); data[i] *= v; data[i + 1] *= v; data[i + 2] *= v; } } break;
      case 5: for (let y = 0; y < height; y++) if (y % Math.max(2, Math.round(a)) < 1) for (let x = 0; x < width; x++) { const i = index(x, y); data[i] *= .45; data[i + 1] *= .45; data[i + 2] *= .45; } break;
      case 6: rgbShift(Math.max(1, Math.round(a * 12)), b); break;
      case 7: for (let y = 0; y < height; y++) { const dx = Math.round((noise(y, Math.floor(time * b)) - .5) * a * width * .06); for (let x = 0; x < width; x++) { const i = index(x, y); data[i] = read(x + dx + 2, y, 0); data[i + 2] = read(x + dx - 2, y, 2); } } break;
      case 8: { const size = Math.max(5, Math.round(b)); for (let y = 0; y < height; y += size) for (let x = 0; x < width; x += size) if (noise(x / size, y / size + Math.floor(time)) > .55) { const shift = Math.round((noise(x, y) - .5) * a * width * .18); for (let yy = y; yy < Math.min(height, y + size); yy++) for (let xx = x; xx < Math.min(width, x + size); xx++) { const i = index(xx, yy); data[i] = read(xx + shift, yy, 0); data[i + 1] = read(xx + shift, yy, 1); data[i + 2] = read(xx + shift, yy, 2); } } break; }
      case 9: for (let i = 0; i < data.length; i += 4) { const glow = Math.max(0, (data[i] + data[i + 1] + data[i + 2]) / 765 - .55) * a * 150; data[i] += glow; data[i + 1] += glow; data[i + 2] += glow; } break;
      case 10: { const radius = Math.max(1, Math.round(a)); for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) { let r = 0, g = 0, bl = 0, count = 0; for (let yy = -radius; yy <= radius; yy += radius) for (let xx = -radius; xx <= radius; xx += radius) { r += read(x + xx, y + yy, 0); g += read(x + xx, y + yy, 1); bl += read(x + xx, y + yy, 2); count++; } const i = index(x, y); data[i] = r / count; data[i + 1] = g / count; data[i + 2] = bl / count; } break; }
      case 11: { const size = Math.max(2, Math.round(a)); for (let y = 0; y < height; y += size) for (let x = 0; x < width; x += size) { const i = index(x, y); for (let yy = y; yy < Math.min(height, y + size); yy++) for (let xx = x; xx < Math.min(width, x + size); xx++) { const at = index(xx, yy); data[at] = copy[i]; data[at + 1] = copy[i + 1]; data[at + 2] = copy[i + 2]; } } break; }
      case 12: for (let y = 1; y < height - 1; y++) for (let x = 1; x < width - 1; x++) { const i = index(x, y); for (let ch = 0; ch < 3; ch++) data[i + ch] = Math.max(0, Math.min(255, copy[i + ch] * (1 + a * 4) - (read(x - 1, y, ch) + read(x + 1, y, ch) + read(x, y - 1, ch) + read(x, y + 1, ch)) * a)); } break;
      case 13: { const steps = Math.max(2, Math.round(a)); for (let i = 0; i < data.length; i += 4) for (let ch = 0; ch < 3; ch++) data[i + ch] = Math.round(data[i + ch] / 255 * (steps - 1)) * 255 / (steps - 1); break; }
      case 14: { const cell = Math.max(3, Math.round(a)); for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) { const i = index(x, y); const cx = Math.floor(x / cell) * cell + cell / 2; const cy = Math.floor(y / cell) * cell + cell / 2; const l = (read(cx, cy, 0) + read(cx, cy, 1) + read(cx, cy, 2)) / 765; const d = Math.hypot((x % cell) - cell / 2, (y % cell) - cell / 2) / cell; if (d < l * .7) data[i] = data[i + 1] = data[i + 2] = 24; } break; }
      case 15: remap((x, y) => [x + Math.sin(y / height * 18 + time * b) * a * width, y + Math.sin(x / width * 15 + time * b) * a * height]); break;
      case 16: remap((x, y) => { const dx = x - width / 2, dy = y - height / 2, r = Math.hypot(dx, dy), angle = Math.atan2(dy, dx) + a * Math.max(0, 1 - r / Math.max(1, b * Math.min(width, height))); return [width / 2 + Math.cos(angle) * r, height / 2 + Math.sin(angle) * r]; }); break;
      case 17: remap((x, y) => { const dx = x - width / 2, dy = y - height / 2, r = Math.hypot(dx, dy), seg = Math.max(2, Math.round(a)), sector = Math.PI * 2 / seg, angle = Math.abs((((Math.atan2(dy, dx) + b) % sector) + sector) % sector - sector / 2); return [width / 2 + Math.cos(angle) * r, height / 2 + Math.sin(angle) * r]; }); break;
      case 18: remap((x, y) => a > .5 ? [x, height - y] : [width - x, y]); break;
      case 19: remap((x, y) => { const dx = x - width / 2, dy = y - height / 2, r = Math.hypot(dx, dy), d = Math.sin(r / Math.max(1, width) * 55 - time * b * 6) * a * 18; return [x + dx / Math.max(1, r) * d, y + dy / Math.max(1, r) * d]; }); break;
      case 20: { const shift = Math.max(1, Math.round(b)); for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) { const i = index(x, y); const target = read(x + shift, y, 0) + read(x + shift, y, 1) + read(x + shift, y, 2) > read(x - shift, y, 0) + read(x - shift, y, 1) + read(x - shift, y, 2) ? x + shift : x - shift; data[i] = data[i] * (1 - a) + read(target, y, 0) * a; data[i + 1] = data[i + 1] * (1 - a) + read(target, y, 1) * a; data[i + 2] = data[i + 2] * (1 - a) + read(target, y, 2) * a; } break; }
      case 21: for (let i = 0; i < data.length; i += 4) { const l = .2126 * data[i] + .7152 * data[i + 1] + .0722 * data[i + 2]; data[i] = (data[i] - 128) * b + 128 + a * 255; data[i + 1] = (data[i + 1] - 128) * b + 128 + a * 255; data[i + 2] = (data[i + 2] - 128) * b + 128 + a * 255; data[i] = l * (1 - c) + data[i] * c; data[i + 1] = l * (1 - c) + data[i + 1] * c; data[i + 2] = l * (1 - c) + data[i + 2] * c; } break;
    }
    context.putImageData(image, 0, 0);
  }
}

export function effectPasses(items: TimelineItem[]): EffectPass[] {
  return items.flatMap((item) => {
    const definition = effectDefinitionForItem(item);
    return definition ? [{ kind: definition.gpuKind, params: item.params || {} }] : [];
  });
}

export class NunWebGpuEffects {
  private device: Gpu; private format: Gpu; private pipeline: Gpu; private presentPipeline: Gpu; private layout: Gpu; private sampler: Gpu; private fallback?: CanvasEffectFallback;
  private ping?: Gpu; private pong?: Gpu; private width = 0; private height = 0;
  private uniforms = new Map<string, Gpu>();
  get isFallback() { return Boolean(this.fallback); }
  private constructor(device: Gpu | null) { this.device = device; if (device) { this.format = navigator.gpu.getPreferredCanvasFormat(); this.sampler = device.createSampler({ magFilter: 'linear', minFilter: 'linear' }); } else this.fallback = new CanvasEffectFallback(); }
  static pending?: Promise<NunWebGpuEffects | null>;
  static lastError = '';
  static async create() {
    if (this.pending) return this.pending;
    this.pending = (async () => { try { const adapter = await (navigator as any).gpu?.requestAdapter(); if (!adapter) { this.lastError = 'No WebGPU adapter was returned.'; return new NunWebGpuEffects(null); } const runtime = new NunWebGpuEffects(await adapter.requestDevice()); await runtime.setup(); return runtime; } catch (error) { this.lastError = error instanceof Error ? error.message : String(error); return new NunWebGpuEffects(null); } })();
    return this.pending;
  }
  private async setup() {
    const module = this.device.createShaderModule({ code: WGSL });
    const compilation = await module.getCompilationInfo();
    const errors = compilation.messages.filter((message: { type: string }) => message.type === 'error');
    if (errors.length) throw new Error(errors.map((message: { message: string }) => message.message).join('; '));
    this.layout = this.device.createBindGroupLayout({ entries: [{ binding: 0, visibility: 2, sampler: {} }, { binding: 1, visibility: 2, texture: {} }, { binding: 2, visibility: 2, buffer: { type: 'uniform' } }] });
    const layout = this.device.createPipelineLayout({ bindGroupLayouts: [this.layout] });
    this.pipeline = await this.device.createRenderPipelineAsync({ layout, vertex: { module, entryPoint: 'vs' }, fragment: { module, entryPoint: 'fs', targets: [{ format: 'rgba8unorm' }] }, primitive: { topology: 'triangle-list' } });
    this.presentPipeline = await this.device.createRenderPipelineAsync({ layout, vertex: { module, entryPoint: 'vs' }, fragment: { module, entryPoint: 'fs', targets: [{ format: this.format }] }, primitive: { topology: 'triangle-list' } });
  }
  private ensure(width: number, height: number) { if (this.width === width && this.height === height && this.ping) return; this.ping?.destroy(); this.pong?.destroy(); const descriptor = { size: { width, height }, format: 'rgba8unorm', usage: 2 | 4 | 16 }; this.ping = this.device.createTexture(descriptor); this.pong = this.device.createTexture(descriptor); this.width = width; this.height = height; }
  render(source: VisualSource, canvas: HTMLCanvasElement, items: TimelineItem[], time: number) {
    if (this.fallback) return this.fallback.render(source, canvas, items, time);
    try {
      const rendered = this.renderGpu(source, canvas, items, time);
      if (rendered) return true;
    } catch (error) {
      NunWebGpuEffects.lastError = error instanceof Error ? error.message : String(error);
    }
    // Some embedded Chromium builds expose navigator.gpu but cannot create a
    // GPUCanvasContext. Falling through here prevents a transparent overlay
    // from silently hiding the selected timeline effect.
    this.fallback = new CanvasEffectFallback();
    return this.fallback.render(source, canvas, items, time);
  }
  private renderGpu(source: VisualSource, canvas: HTMLCanvasElement, items: TimelineItem[], time: number) {
    const sourceWidth = source instanceof HTMLVideoElement ? source.videoWidth : source instanceof HTMLImageElement ? source.naturalWidth : source.width;
    const sourceHeight = source instanceof HTMLVideoElement ? source.videoHeight : source instanceof HTMLImageElement ? source.naturalHeight : source.height;
    if (sourceWidth < 2 || sourceHeight < 2 || !items.length) return false;
    // copyExternalImageToTexture is a pixel copy, not an image-resize API.
    // Keep the texture at source dimensions so the Program Monitor never crops
    // the frame; CSS scales the resulting canvas into the preview viewport.
    const width = sourceWidth; const height = sourceHeight;
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
    const context = canvas.getContext('webgpu') as any; if (!context) return false; context.configure({ device: this.device, format: this.format, alphaMode: 'premultiplied' }); this.ensure(width, height); this.device.queue.copyExternalImageToTexture({ source }, { texture: this.ping }, { width, height });
    let input = this.ping; let output = this.pong; const encoder = this.device.createCommandEncoder();
    for (const item of items) { const def = effectDefinitionForItem(item); if (!def) continue; let uniform = this.uniforms.get(def.id); if (!uniform) { uniform = this.device.createBuffer({ size: 32, usage: 64 | 8 }); this.uniforms.set(def.id, uniform); } const nums = values(def, item.params || {}); this.device.queue.writeBuffer(uniform, 0, new Float32Array([...nums, width, height, time, def.gpuKind])); const bind = this.device.createBindGroup({ layout: this.layout, entries: [{ binding: 0, resource: this.sampler }, { binding: 1, resource: input.createView() }, { binding: 2, resource: { buffer: uniform } }] }); const pass = encoder.beginRenderPass({ colorAttachments: [{ view: output.createView(), loadOp: 'clear', storeOp: 'store', clearValue: [0,0,0,0] }] }); pass.setPipeline(this.pipeline); pass.setBindGroup(0, bind); pass.draw(3); pass.end(); [input, output] = [output, input]; }
    this.device.queue.submit([encoder.finish()]);
    return this.presentTexture(input, canvas, width, height);
  }
  private presentTexture(input: Gpu, canvas: HTMLCanvasElement, width: number, height: number) {
    const context = canvas.getContext('webgpu') as any; const uniform = this.device.createBuffer({ size: 32, usage: 64 | 8 }); this.device.queue.writeBuffer(uniform, 0, new Float32Array([0,0,0,0,width,height,0,0])); const bind=this.device.createBindGroup({layout:this.layout,entries:[{binding:0,resource:this.sampler},{binding:1,resource:input.createView()},{binding:2,resource:{buffer:uniform}}]}); const enc=this.device.createCommandEncoder();const pass=enc.beginRenderPass({colorAttachments:[{view:context.getCurrentTexture().createView(),loadOp:'clear',storeOp:'store',clearValue:[0,0,0,0]}]});pass.setPipeline(this.presentPipeline);pass.setBindGroup(0,bind);pass.draw(3);pass.end();this.device.queue.submit([enc.finish()]);return true;
  }
}

let sample: HTMLCanvasElement | undefined;
export function thumbnailSample() { if (sample) return sample; sample = document.createElement('canvas'); sample.width = 320; sample.height = 180; const c = sample.getContext('2d')!; const g=c.createLinearGradient(0,0,320,180);g.addColorStop(0,'#2354a5');g.addColorStop(.5,'#f08b68');g.addColorStop(1,'#1a1735');c.fillStyle=g;c.fillRect(0,0,320,180);c.fillStyle='#19172b';c.fillRect(0,115,320,65);c.fillStyle='#ffd791';c.beginPath();c.arc(240,55,27,0,7);c.fill();c.fillStyle='#243753';c.beginPath();c.moveTo(0,125);c.lineTo(95,55);c.lineTo(170,125);c.fill(); return sample; }
