/* 机制动画共享库:确定性 Canvas 绘制(固定种子噪声 / 墨笔 / 印章 / 舆图晕渲)。
   约定:画面只由 renderFrame(t) 决定——无真实时钟、无 Math.random、无 CSS 动画,
   tools/render_html_video.py 逐帧调用截图。页面需先有 #cv 画布与 #subtxt 字幕节点,再引入本文件。 */
const cv=document.getElementById('cv'), ctx=cv.getContext('2d');
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const seg=(t,a,b)=>clamp((t-a)/(b-a),0,1);
const ease=p=>p<.5?2*p*p:1-Math.pow(-2*p+2,2)/2;
const lerp=(a,b,p)=>a+(b-a)*p;
const sm=v=>v<=0?0:v>=1?1:v*v*(3-2*v);
const fade=(t,a,b,d=.4)=>Math.min(seg(t,a,a+d),1-seg(t,b-d,b));
const INK='#2a241c', PAPER='#efe7d2', CINNABAR='#a8281f', QIN_RED='#b3322a', ZHAO_GREEN='#2f5d4f';
const KAI='"KaiTi","STKaiti","Noto Serif SC",serif';

/* ============ 确定性噪声 ============ */
function hash2(x,y,s){let h=(Math.imul(x|0,374761393)+Math.imul(y|0,668265263)+Math.imul(s|0,1442695041))|0;
  h=Math.imul(h^(h>>>13),1274126177);h^=h>>>16;return (h>>>0)/4294967296;}
const H1=(i,s)=>hash2(i,7,s);
function noise1(x,s=0){const i=Math.floor(x),f=x-i,u=f*f*(3-2*f);return lerp(H1(i,s),H1(i+1,s),u);}
function rng(seed){return ()=>{seed=seed+0x6D2B79F5|0;let t=Math.imul(seed^seed>>>15,1|seed);
  t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};}
const PERM=new Uint8Array(512),GX=new Float32Array(256),GY=new Float32Array(256);
(function(){const r=rng(97),p=[...Array(256).keys()];
  for(let i=255;i>0;i--){const j=Math.floor(r()*(i+1));[p[i],p[j]]=[p[j],p[i]];}
  for(let i=0;i<512;i++)PERM[i]=p[i&255];
  for(let i=0;i<256;i++){const a=r()*Math.PI*2;GX[i]=Math.cos(a);GY[i]=Math.sin(a);}})();
function noise2(x,y){
  const X=Math.floor(x),Y=Math.floor(y),xf=x-X,yf=y-Y,xi=X&255,yi=Y&255;
  const a=PERM[PERM[xi]+yi],b=PERM[PERM[xi+1]+yi],c=PERM[PERM[xi]+yi+1],d=PERM[PERM[xi+1]+yi+1];
  const u=xf*xf*xf*(xf*(xf*6-15)+10),v=yf*yf*yf*(yf*(yf*6-15)+10);
  const n0=lerp(GX[a]*xf+GY[a]*yf,GX[b]*(xf-1)+GY[b]*yf,u);
  const n1=lerp(GX[c]*xf+GY[c]*(yf-1),GX[d]*(xf-1)+GY[d]*(yf-1),u);
  return lerp(n0,n1,v);
}
function fbm(x,y,o){let s=0,a=1,f=1,n=0;for(let i=0;i<o;i++){s+=a*noise2(x*f+i*31.7,y*f-i*17.3);n+=a;a*=.5;f*=2.03;}return s/n*1.45;}
function ridged(x,y,o,g=.5){let s=0,a=1,f=1,n=0,w=1;
  for(let i=0;i<o;i++){let r=1-Math.abs(noise2(x*f+i*13.1,y*f-i*7.7)*1.5);r=r*r;s+=a*r*w;w=clamp(r*1.3,0,1);n+=a;a*=g;f*=2.07;}
  return s/n;}

/* ============ 路径采样(借隐藏 SVG 求弧长) ============ */
const SVG_NS='http://www.w3.org/2000/svg';
const SV=document.createElementNS(SVG_NS,'svg');
SV.setAttribute('style','position:absolute;width:0;height:0');document.body.appendChild(SV);
function samplePath(d,step=3){
  const p=document.createElementNS(SVG_NS,'path');p.setAttribute('d',d);SV.appendChild(p);
  const L=p.getTotalLength(),n=Math.max(2,Math.ceil(L/step)),pts=[];
  for(let i=0;i<=n;i++){const q=p.getPointAtLength(Math.min(i*L/n,L));pts.push([q.x,q.y]);}
  return {pts,L,step:L/n,d};
}
function at(P,s){s=clamp(s,0,P.L);const f=s/P.step,i=Math.min(Math.floor(f),P.pts.length-2),u=f-i;
  const a=P.pts[i],b=P.pts[i+1];return [a[0]+(b[0]-a[0])*u,a[1]+(b[1]-a[1])*u];}
function tan(P,s){const a=at(P,s-4),b=at(P,s+4),dx=b[0]-a[0],dy=b[1]-a[1],l=Math.hypot(dx,dy)||1;return [dx/l,dy/l];}
// 单调路径的查表函数:axis='y' 给出 x(y)(南北向河流),axis='x' 给出 y(x)(东西向道路)
function lookup(P,axis,lo,hi,dflt){
  const n=hi-lo,T=new Float32Array(n+1).fill(NaN),ia=axis==='y'?1:0,ib=1-ia;
  for(const p of P.pts){const k=Math.round(p[ia]-lo);if(k>=0&&k<=n)T[k]=p[ib];}
  let last=NaN;for(let k=0;k<=n;k++){if(!isNaN(T[k]))last=T[k];else T[k]=last;}
  last=NaN;for(let k=n;k>=0;k--){if(!isNaN(T[k]))last=T[k];else T[k]=isNaN(last)?dflt:last;}
  return v=>T[clamp(Math.round(v-lo),0,n)];
}
// 闭合软圈:绕一组点画一圈(半径随方向贴合 + 噪声),返回可 samplePath 的 d
function blobPath(pts,pad,seed){
  const cx=pts.reduce((s,p)=>s+p[0],0)/pts.length,cy=pts.reduce((s,p)=>s+p[1],0)/pts.length,K=14,ring=[];
  for(let k=0;k<K;k++){const a=k/K*Math.PI*2,ux=Math.cos(a),uy=Math.sin(a);
    let r=0;for(const p of pts){const dx=p[0]-cx,dy=p[1]-cy,proj=dx*ux+dy*uy,perp=Math.abs(-dx*uy+dy*ux);
      if(perp<pad*1.1)r=Math.max(r,proj);}
    r=Math.max(r,pad*.6)+pad*(.85+.3*hash2(k,seed,5));ring.push([cx+ux*r,cy+uy*r]);}
  let d=`M ${ring[0][0].toFixed(1)},${ring[0][1].toFixed(1)}`;
  for(let k=0;k<K;k++){const p0=ring[(k-1+K)%K],p1=ring[k],p2=ring[(k+1)%K],p3=ring[(k+2)%K];
    d+=` C ${(p1[0]+(p2[0]-p0[0])/6).toFixed(1)},${(p1[1]+(p2[1]-p0[1])/6).toFixed(1)} ${(p2[0]-(p3[0]-p1[0])/6).toFixed(1)},${(p2[1]-(p3[1]-p1[1])/6).toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;}
  return {d,cx,cy};
}

/* ============ 舆图底图:高度场 → 晕渲 + 等高线 + 纸纹(只在加载时算一次) ============ */
const RAMP=[[0,[234,224,197]],[.1,[229,217,184]],[.2,[214,198,158]],[.34,[192,183,145]],
  [.5,[166,172,140]],[.68,[140,148,124]],[.85,[122,126,108]],[1,[106,106,94]]];
function ramp(e){for(let i=1;i<RAMP.length;i++)if(e<=RAMP[i][0]){const [a,ca]=RAMP[i-1],[b,cb]=RAMP[i],u=(e-a)/(b-a);
  return [lerp(ca[0],cb[0],u),lerp(ca[1],cb[1],u),lerp(ca[2],cb[2],u)];}return RAMP[RAMP.length-1][1];}
// W = {X0,Y0,W,H,S}:世界范围与底图分辨率倍率;height(x,y)→0..1;decorate(g) 在世界坐标下叠画河流道路等
function buildRelief(W,height,decorate){
  const TW=Math.round(W.W*W.S),TH=Math.round(W.H*W.S),Hm=new Float32Array(TW*TH);
  for(let j=0;j<TH;j++){const y=W.Y0+j/W.S;for(let i=0;i<TW;i++)Hm[j*TW+i]=height(W.X0+i/W.S,y);}
  const can=document.createElement('canvas');can.width=TW;can.height=TH;
  const g=can.getContext('2d'),img=g.createImageData(TW,TH),D=img.data;
  const Z=125*W.S/2, L=[-.55,-.6,.58], CI=.07;
  for(let j=0;j<TH;j++)for(let i=0;i<TW;i++){
    const k=j*TW+i,h=Hm[k];
    const hl=Hm[k-(i>0?1:0)],hr=Hm[k+(i<TW-1?1:0)],hu=Hm[k-(j>0?TW:0)],hd=Hm[k+(j<TH-1?TW:0)];
    const nx=-(hr-hl)*Z,ny=-(hd-hu)*Z,nl=Math.hypot(nx,ny,1);
    const sh=(nx*L[0]+ny*L[1]+L[2])/nl;
    const f=clamp(1+.72*(sh-.58),.56,1.16);
    const e=clamp(h,0,1);let [r,gg,b]=ramp(e);
    r*=f;gg*=f;b*=f*.98+.02;                                              // 阴坡微偏冷
    if(e>.19){const c0=Math.floor(e/CI);
      if(c0!==Math.floor(hr/CI)||c0!==Math.floor(hd/CI)){r=r*.8+20;gg=gg*.8+14;b=b*.8+6;}}
    const x=W.X0+i/W.S,y=W.Y0+j/W.S;
    const st=.965+.05*noise2(x*.0016+50,y*.0016-20), gr=.975+.05*hash2(i,j,3);
    D[k*4]=clamp(r*st*gr,0,255);D[k*4+1]=clamp(gg*st*gr,0,255);D[k*4+2]=clamp(b*st*gr,0,255);D[k*4+3]=255;
  }
  g.putImageData(img,0,0);
  g.setTransform(W.S,0,0,W.S,-W.X0*W.S,-W.Y0*W.S);g.lineCap='round';g.lineJoin='round';
  if(decorate)decorate(g);
  return can;
}
function strokeRiver(g,d,w=24){
  const rp=new Path2D(d);
  g.strokeStyle='rgba(96,118,108,.32)';g.lineWidth=w*1.5;g.stroke(rp);
  g.strokeStyle='rgba(150,180,170,.95)';g.lineWidth=w;g.stroke(rp);
  g.strokeStyle='rgba(214,229,221,.65)';g.lineWidth=w*.3;g.stroke(rp);
}
// 草木:淡点皴(ok(x,y) 决定能否落点)
function stipple(g,n,box,ok,seed){
  const R=rng(seed);
  for(let m=0;m<n;m++){
    const x=box[0]+R()*box[2],y=box[1]+R()*box[3];
    if(!ok(x,y))continue;
    for(let q=0;q<6;q++){g.beginPath();g.arc(x+(R()-.5)*16,y+(R()-.5)*9,1.1+R()*1.3,0,7);
      g.fillStyle=`rgba(84,98,72,${.28+R()*.2})`;g.fill();}
  }
}

/* ============ 绘制原语 ============ */
// 墨笔:变宽多边形(起笔收笔渐细 + 噪声起伏) + 飞白丝
function brush(P,s0,s1,W,color,seed,dry=true){
  if(s1-s0<2)return;
  const n=Math.max(2,Math.ceil((s1-s0)/3)),Lp=[],Rp=[];
  for(let i=0;i<=n;i++){
    const s=s0+(s1-s0)*i/n,[x,y]=at(P,s),[tx,ty]=tan(P,s),u=i/n;
    const taper=Math.min(1,u/.05+.3)*Math.min(1,(1-u)/.08+.4);
    const w=W*taper*(.82+.36*noise1(s*.018,seed))/2,j=(noise1(s*.35,seed+9)-.5)*1.8;
    Lp.push([x-ty*(w+j),y+tx*(w+j)]);Rp.push([x+ty*(w-j),y-tx*(w-j)]);
  }
  ctx.beginPath();ctx.moveTo(Lp[0][0],Lp[0][1]);for(const p of Lp)ctx.lineTo(p[0],p[1]);
  for(let i=Rp.length-1;i>=0;i--)ctx.lineTo(Rp[i][0],Rp[i][1]);ctx.closePath();
  ctx.fillStyle=color;ctx.fill();
  if(!dry)return;
  ctx.save();ctx.strokeStyle='rgba(239,231,210,.38)';ctx.lineWidth=1.1;ctx.lineCap='round';
  for(let k=0;k<3;k++){
    const off=(k-1)*W*.24;ctx.beginPath();let pen=false;
    for(let i=0;i<=n;i++){const s=s0+(s1-s0)*i/n;
      if(noise1(s*.045,seed*3+k*11)>.56){const [x,y]=at(P,s),[tx,ty]=tan(P,s),px=x-ty*off,py=y+tx*off;
        pen?ctx.lineTo(px,py):ctx.moveTo(px,py);pen=true;}else pen=false;}
    ctx.stroke();}
  ctx.restore();
}
function arrowHead(P,s,size,color){
  const [x,y]=at(P,s),[tx,ty]=tan(P,s),nx=-ty,ny=tx;
  ctx.beginPath();ctx.moveTo(x+tx*size*.7,y+ty*size*.7);
  ctx.quadraticCurveTo(x+nx*size*.25,y+ny*size*.25,x-tx*size*.55+nx*size*.62,y-ty*size*.55+ny*size*.62);
  ctx.lineTo(x-tx*size*.2,y-ty*size*.2);
  ctx.lineTo(x-tx*size*.55-nx*size*.62,y-ty*size*.55-ny*size*.62);
  ctx.quadraticCurveTo(x-nx*size*.25,y-ny*size*.25,x+tx*size*.7,y+ty*size*.7);
  ctx.fillStyle=color;ctx.fill();
}
// 小旗:droop 0→1 旗面由迎风到低垂
function banner(x,y,col,droop,alpha,ph,t,sc=1){
  if(alpha<=0)return;
  ctx.save();ctx.globalAlpha*=alpha;ctx.translate(x,y);ctx.scale(sc,sc);
  ctx.strokeStyle=INK;ctx.lineWidth=1.7;ctx.lineCap='round';
  ctx.beginPath();ctx.moveTo(0,0);ctx.lineTo(0,-25);ctx.stroke();
  ctx.translate(0,-24);ctx.rotate(droop*1.2);
  const w=1.5*Math.sin(t*5.2+ph)*(1-droop);
  ctx.beginPath();ctx.moveTo(0,0);ctx.quadraticCurveTo(8,-1+w*.5,16,1+w);ctx.lineTo(11,5+w*.6);
  ctx.lineTo(16,9+w);ctx.quadraticCurveTo(8,10+w*.5,0,10);ctx.closePath();
  ctx.fillStyle=col;ctx.fill();ctx.lineWidth=1;ctx.stroke();ctx.restore();
}
function cart(x,y,ang,a){
  if(a<=0)return;
  ctx.save();ctx.globalAlpha*=a;ctx.translate(x,y);ctx.rotate(ang);
  ctx.strokeStyle=INK;ctx.lineWidth=1.5;
  ctx.beginPath();ctx.moveTo(-15,-6);ctx.lineTo(-27,-3);ctx.stroke();
  ctx.beginPath();ctx.roundRect(-15,-13,30,10,3);ctx.fillStyle='#c39a4c';ctx.fill();ctx.stroke();
  ctx.beginPath();ctx.ellipse(1,-14,10,5,0,Math.PI,0);ctx.fillStyle='#e4cf98';ctx.fill();ctx.stroke();
  for(const wx of[-8,8]){ctx.beginPath();ctx.arc(wx,0,4,0,7);ctx.fillStyle=PAPER;ctx.fill();ctx.stroke();}
  ctx.restore();
}
function halo(text,x,y,font,fill,align='left',hw=6,alpha=1){
  ctx.save();ctx.globalAlpha*=alpha;ctx.font=font;ctx.textAlign=align;ctx.textBaseline='alphabetic';
  ctx.lineJoin='round';ctx.strokeStyle='rgba(239,231,210,.9)';ctx.lineWidth=hw;ctx.strokeText(text,x,y);
  ctx.fillStyle=fill;ctx.fillText(text,x,y);ctx.restore();
}
function seal(x,y,size,ch,col,alpha=1,sc=1){
  if(alpha<=0)return;
  ctx.save();ctx.globalAlpha*=alpha;ctx.translate(x,y);ctx.scale(sc,sc);
  ctx.beginPath();ctx.roundRect(-size/2,-size/2,size,size,size*.14);ctx.fillStyle=col;ctx.fill();
  ctx.font=`bold ${size*.72}px ${KAI}`;ctx.textAlign='center';ctx.textBaseline='middle';
  ctx.fillStyle='#f6eedb';ctx.fillText(ch,0,size*.04);
  const R=rng(ch.charCodeAt(0));ctx.fillStyle='rgba(246,238,219,.5)';            // 印泥斑驳
  for(let i=0;i<14;i++){ctx.beginPath();ctx.arc((R()-.5)*size*.9,(R()-.5)*size*.9,R()*1.3+.3,0,7);ctx.fill();}
  ctx.restore();
}
// 地图标注:印章 + 楷书(带纸色描边)
function label(x,y,sealCh,sealCol,text,size,align,alpha){
  if(alpha<=0)return;
  ctx.font=`bold ${size}px ${KAI}`;const tw=ctx.measureText(text).width,ss=size*1.05,gap=9;
  const total=(sealCh?ss+gap:0)+tw,x0=align==='center'?x-total/2:align==='right'?x-total:x;
  if(sealCh)seal(x0+ss/2,y-size*.32,ss,sealCh,sealCol,alpha);
  halo(text,x0+(sealCh?ss+gap:0),y,`bold ${size}px ${KAI}`,INK,'left',7,alpha);
}
// 纸色卡片(计日/户籍等屏幕面板)
function card(x,y,w,h,edge='#7e201a'){
  ctx.beginPath();ctx.roundRect(x,y,w,h,8);ctx.fillStyle='rgba(239,231,210,.94)';ctx.fill();
  ctx.lineWidth=3;ctx.strokeStyle=edge;ctx.stroke();
  ctx.beginPath();ctx.roundRect(x+8,y+8,w-16,h-16,5);ctx.lineWidth=1;ctx.stroke();
}
const CN='零一二三四五六七八九';
function cnum(n){                                     // 0~999 → 中文数字(四十六 / 一百零五 / 一百一十)
  if(n<10)return CN[n];
  if(n<20)return '十'+(n%10?CN[n%10]:'');
  if(n<100)return CN[(n/10)|0]+'十'+(n%10?CN[n%10]:'');
  const r=n%100;return CN[(n/100)|0]+'百'+(r===0?'':r<10?'零'+CN[r]:r<20?'一'+cnum(r):cnum(r));
}

/* ============ 屏幕层:题头 / 暗角 / 纸纹 ============ */
let VIG,GRAIN;
function buildOverlays(){
  VIG=document.createElement('canvas');VIG.width=1920;VIG.height=1080;
  const v=VIG.getContext('2d'),g=v.createRadialGradient(960,540,420,960,540,1180);
  g.addColorStop(0,'rgba(42,30,18,0)');g.addColorStop(1,'rgba(42,30,18,.75)');v.fillStyle=g;v.fillRect(0,0,1920,1080);
  GRAIN=document.createElement('canvas');GRAIN.width=1920;GRAIN.height=1080;
  const q=GRAIN.getContext('2d'),im=q.createImageData(1920,1080),D=im.data;
  for(let i=0;i<1920*1080;i++){const n=232+23*hash2(i%1920,(i/1920)|0,11);D[i*4]=n;D[i*4+1]=n-4;D[i*4+2]=n-12;D[i*4+3]=255;}
  q.putImageData(im,0,0);
}
// H = {series,title,year,yearVal,source};纪年条按战国区间(前475~前221)定位
function drawHeader(H){
  const gl=ctx.createRadialGradient(400,88,30,400,88,420);
  gl.addColorStop(0,'rgba(239,231,210,.75)');gl.addColorStop(1,'rgba(239,231,210,0)');
  ctx.fillStyle=gl;ctx.fillRect(0,0,1920,1080);
  const gr=ctx.createRadialGradient(1640,100,30,1640,100,360);
  gr.addColorStop(0,'rgba(239,231,210,.75)');gr.addColorStop(1,'rgba(239,231,210,0)');
  ctx.fillStyle=gr;ctx.fillRect(0,0,1920,1080);
  ctx.beginPath();ctx.roundRect(140,50,64,64,10);ctx.fillStyle=ZHAO_GREEN;ctx.fill();
  ctx.font=`bold 36px ${KAI}`;ctx.textAlign='center';ctx.fillStyle='#f4edda';ctx.fillText('势',172,95);
  halo(H.series,226,76,'22px "Noto Serif SC",serif','#6f675c','left',5);
  halo(H.title,226,121,'bold 42px "Noto Serif SC",serif',INK,'left',7);
  halo(H.year,1830,90,'bold 48px "Noto Serif SC",serif',CINNABAR,'right',7);
  ctx.fillStyle='rgba(206,195,166,.9)';ctx.beginPath();ctx.roundRect(1380,106,450,8,4);ctx.fill();
  ctx.fillStyle=CINNABAR;ctx.beginPath();ctx.roundRect(1380,106,450*(475-H.yearVal)/(475-221),8,4);ctx.fill();
  halo('战国',1364,118,'bold 24px "Noto Serif SC",serif','#7e201a','right',5);
  halo(H.source,1830,150,'20px "Noto Serif SC",serif','#6f675c','right',5);
}
// 图例:items 依阅读顺序 [['txt',文字,色]|['dot',色]|['flag',色]|['house']|['gap']]
function drawLegend(items,t,alpha){
  if(alpha<=0)return;
  ctx.save();ctx.globalAlpha=alpha;ctx.font=`bold 21px ${KAI}`;
  const wOf=it=>it[0]==='txt'?ctx.measureText(it[1]).width:it[0]==='dot'?10:it[0]==='flag'?16:it[0]==='house'?30:18;
  let x=1830-items.reduce((s,it)=>s+wOf(it)+6,0);
  for(const it of items){
    if(it[0]==='txt')halo(it[1],x,1046,`bold 21px ${KAI}`,it[2],'left',5);
    else if(it[0]==='dot'){ctx.fillStyle=it[1];ctx.beginPath();ctx.arc(x+5,1039,3.2,0,7);ctx.fill();}
    else if(it[0]==='flag')banner(x+3,1050,it[1],0,1,0,t,.72);
    else if(it[0]==='house')house(x+15,1039,0,1,null);
    x+=wOf(it)+6;}
  ctx.restore();
}
// 一户(俯视院落):院墙 + 北面正房(悬山顶+屋脊)+ 东厢 + 南开院门;mark 为朱砂描边色(连坐高亮)
function house(x,y,ang,alpha,mark,roof='#b9a88a'){
  if(alpha<=0)return;
  ctx.save();ctx.globalAlpha*=alpha;ctx.translate(x,y);ctx.rotate(ang);
  ctx.fillStyle='rgba(60,46,30,.16)';ctx.fillRect(-12,-9,28,22);                              // 落影
  ctx.fillStyle='rgba(236,226,198,.94)';ctx.fillRect(-14,-11,28,22);
  ctx.lineWidth=1.2;ctx.strokeStyle='rgba(58,47,34,.75)';ctx.strokeRect(-14,-11,28,22);
  const roofAt=(rx,ry,rw,rh)=>{ctx.fillStyle=roof;ctx.fillRect(rx,ry,rw,rh);
    ctx.fillStyle='rgba(60,46,30,.3)';ctx.fillRect(rx,ry+rh/2,rw,rh/2);                       // 背阴坡
    ctx.lineWidth=1.1;ctx.strokeStyle=INK;ctx.strokeRect(rx,ry,rw,rh);
    ctx.beginPath();ctx.moveTo(rx,ry+rh/2);ctx.lineTo(rx+rw,ry+rh/2);ctx.stroke();};
  roofAt(-11,-10,22,9);roofAt(5,0,7,9);
  ctx.fillStyle=INK;ctx.fillRect(-3,9.8,6,2.4);                                                 // 院门
  if(mark){ctx.lineWidth=3;ctx.strokeStyle=mark;ctx.strokeRect(-17.5,-14.5,35,29);}
  ctx.restore();
}

/* ============ 镜头 ============ */
// keys: [[t, 中心x, 中心y, 缩放], ...]
function camAt(keys,t){let i=0;while(i<keys.length-2&&t>keys[i+1][0])i++;
  const [t0,x0,y0,z0]=keys[i],[t1,x1,y1,z1]=keys[i+1],p=ease(seg(t,t0,t1));
  return [lerp(x0,x1,p),lerp(y0,y1,p),lerp(z0,z1,p)];}

/* ============ 主循环 / 渲染引导 ============ */
// A = {dur, cam, world:{X0,Y0,W,H,S}, height, decorate, drawWorld(t), drawScreen(t), vignette(t), subs}
function mechMain(A){
  const subtxt=document.getElementById('subtxt');
  let TER=null;
  window.renderFrame=function(T){
    const t=clamp(T,0,A.dur);
    ctx.setTransform(1,0,0,1,0,0);ctx.globalAlpha=1;ctx.globalCompositeOperation='source-over';
    ctx.fillStyle='#e9dfc6';ctx.fillRect(0,0,1920,1080);
    const [cx,cy,z]=camAt(A.cam,t);
    ctx.setTransform(z,0,0,z,960-cx*z,540-cy*z);
    ctx.imageSmoothingQuality='high';ctx.drawImage(TER,A.world.X0,A.world.Y0,A.world.W,A.world.H);
    A.drawWorld(t);
    ctx.setTransform(1,0,0,1,0,0);ctx.globalAlpha=1;
    ctx.globalCompositeOperation='multiply';ctx.drawImage(GRAIN,0,0);
    ctx.globalAlpha=A.vignette?A.vignette(t):.32;ctx.drawImage(VIG,0,0);
    ctx.globalAlpha=1;ctx.globalCompositeOperation='source-over';
    A.drawScreen(t);
    const fo=ease(seg(t,A.dur-.6,A.dur));if(fo>0){ctx.fillStyle=`rgba(20,16,12,${fo*.92})`;ctx.fillRect(0,0,1920,1080);}
    let line='',op=0;for(const [a,b,s] of A.subs)if(t>=a&&t<b){line=s;op=fade(t,a,b,.2);}
    if(subtxt.textContent!==line)subtxt.textContent=line;
    subtxt.style.opacity=op;
  };
  window.__DURATION__=A.dur;
  const q=new URLSearchParams(location.search),frame=document.getElementById('frame');
  const fit=()=>{const s=Math.min(innerWidth/1920,innerHeight/1080);
    frame.style.transform=`translate(${(innerWidth-1920*s)/2}px,${(innerHeight-1080*s)/2}px) scale(${s})`;};
  if(!q.has('render')){fit();addEventListener('resize',fit);}
  document.fonts.ready.then(()=>{
    const t0=performance.now();TER=buildRelief(A.world,A.height,A.decorate);buildOverlays();
    window.__BUILD_MS__=Math.round(performance.now()-t0);
    if(q.has('render')||q.has('t'))window.renderFrame(parseFloat(q.get('t')||'0'));
    else{let s=null;const loop=now=>{if(s===null)s=now;window.renderFrame(((now-s)/1000)%A.dur);requestAnimationFrame(loop);};requestAnimationFrame(loop);}
    window.__READY__=true;
  });
}
