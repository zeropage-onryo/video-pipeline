/* The Studio field shader — ported unchanged from prototype/studio.html.
   Self-contained: falls back to the CSS .fb gradient when WebGL2 is
   unavailable, respects prefers-reduced-motion. */
export function initField() {
  const cv = document.getElementById('gl');
  const gl = cv.getContext('webgl2', { antialias: false, alpha: false, powerPreference: 'low-power' });
  if (!gl) { document.documentElement.classList.add('no-gl'); return; }
  const VS = `#version 300 es
  in vec2 p; void main(){ gl_Position=vec4(p,0.,1.); }`;
  const FS = `#version 300 es
  precision highp float; out vec4 O;
  uniform vec2 uRes; uniform float uT; uniform vec2 uM;
  float hash(vec2 p){ return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453123); }
  float noise(vec2 p){ vec2 i=floor(p),f=fract(p); vec2 u=f*f*(3.-2.*f);
    return mix(mix(hash(i),hash(i+vec2(1,0)),u.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),u.x),u.y); }
  float fbm(vec2 p){ float v=0.,a=.5; for(int i=0;i<4;i++){ v+=a*noise(p); p*=2.03; a*=.5; } return v; }
  vec3 wash(vec2 uv){
    float t=uT*.035;
    vec2 q=vec2(fbm(uv*1.7+vec2(t,0.)),fbm(uv*1.7+vec2(4.7,-t*.75)));
    float f=fbm(uv*2.1+q*1.5+t*.25);
    vec3 vd=vec3(.014,.014,.017), cold=vec3(.040,.052,.072),
         warm=vec3(.115,.050,.032), emb=vec3(.62,.020,.095);
    vec3 c=mix(vd,cold,smoothstep(.22,.78,f));
    c=mix(c,warm,smoothstep(.48,.94,fbm(uv*1.15-t*.45)));
    float d=distance(uv*vec2(uRes.x/uRes.y,1.),uM*vec2(uRes.x/uRes.y,1.));
    c+=emb*(.34/(1.+d*d*13.))*(.62+.38*sin(uT*.55));
    c+=emb*.26*smoothstep(.95,.05,distance(uv,vec2(.86,.14)));
    c+=cold*1.1*smoothstep(.9,.0,distance(uv,vec2(.12,.72)));
    return c;
  }
  vec2 rot(vec2 v,float a){ float s=sin(a),c=cos(a); return mat2(c,-s,s,c)*v; }
  void main(){
    vec2 uv=gl_FragCoord.xy/uRes;
    vec2 auv=vec2(uv.x*(uRes.x/uRes.y),uv.y);
    float ang=radians(31.);
    vec2 r=rot(auv,ang);
    float wob=sin(r.y*2.1+uT*.11)*.016;
    float bar=fract((r.x+wob)*9.0);
    float q=bar-.5, lens=q*2.;
    float refr=.030*lens*sqrt(max(0.,1.-lens*lens*.55));
    vec2 off=rot(vec2(refr,0.),-ang);
    vec3 c;
    c.r=wash(uv+off*1.13).r; c.g=wash(uv+off*1.00).g; c.b=wash(uv+off*0.87).b;
    float spec=pow(max(0.,1.-abs(lens)),14.);
    c+=vec3(.86,.89,1.)*spec*.050;
    c*=1.-smoothstep(.40,.5,abs(q))*.40;
    c*=1.-smoothstep(.42,1.18,length((uv-.5)*vec2(1.25,1.)))*.68;
    c+=(hash(gl_FragCoord.xy+fract(uT)*97.31)-.5)*.030;
    O=vec4(max(c,0.),1.);
  }`;
  function sh(t, s) {
    const o = gl.createShader(t); gl.shaderSource(o, s); gl.compileShader(o);
    if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) { console.warn(gl.getShaderInfoLog(o)); return null; }
    return o;
  }
  const vs = sh(gl.VERTEX_SHADER, VS), fs = sh(gl.FRAGMENT_SHADER, FS);
  if (!vs || !fs) { document.documentElement.classList.add('no-gl'); return; }
  const pr = gl.createProgram(); gl.attachShader(pr, vs); gl.attachShader(pr, fs); gl.linkProgram(pr);
  if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) { document.documentElement.classList.add('no-gl'); return; }
  gl.useProgram(pr);
  const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(pr, 'p'); gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const uRes = gl.getUniformLocation(pr, 'uRes'), uT = gl.getUniformLocation(pr, 'uT'), uM = gl.getUniformLocation(pr, 'uM');
  const S = .62; let mx = .78, my = .30, tx = .78, ty = .30;
  function size() {
    const w = Math.floor(innerWidth * S), h = Math.floor(innerHeight * S);
    cv.width = w; cv.height = h; gl.viewport(0, 0, w, h); gl.uniform2f(uRes, w, h);
  }
  addEventListener('resize', size); size();
  addEventListener('pointermove', e => { tx = e.clientX / innerWidth; ty = 1 - e.clientY / innerHeight; });
  const still = matchMedia('(prefers-reduced-motion:reduce)').matches;
  const t0 = performance.now();
  (function loop(now) {
    mx += (tx - mx) * .045; my += (ty - my) * .045;
    gl.uniform1f(uT, still ? 6.0 : (now - t0) / 1000);
    gl.uniform2f(uM, mx, my);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    if (!still) requestAnimationFrame(loop);
  })(t0);
}
