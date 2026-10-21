(() => {
 const source=document.querySelector('#preflight-data');if(!source)return;
 const d=JSON.parse(source.textContent),canvas=document.querySelector('#preflight-canvas'),ctx=canvas.getContext('2d');
 const pick=document.querySelector('#preflight-pick'),mode=document.querySelector('#preflight-mode');
 const lo=[0,1,2].map(i=>d.xyz.reduce((a,p)=>Math.min(a,p[i]),Infinity)),hi=[0,1,2].map(i=>d.xyz.reduce((a,p)=>Math.max(a,p[i]),-Infinity));
 const center=lo.map((v,i)=>(v+hi[i])/2),span=Math.max(...hi.map((v,i)=>v-lo[i]));
 let yaw=-.65,pitch=.45,zoom=1,drag=null,projected=[],ordered=[];
 const fixed=new Set(d.supports||[]),loaded=new Set((d.loads||[]).flatMap(l=>l.faces.map(f=>l.body?l.body+':'+f:f)));
 const rotate=p=>{const x=p[0]-center[0],y=p[1]-center[1],z=p[2]-center[2],a=Math.cos(yaw)*x-Math.sin(yaw)*y,b=Math.sin(yaw)*x+Math.cos(yaw)*y;return [a,Math.cos(pitch)*z-Math.sin(pitch)*b,Math.sin(pitch)*z+Math.cos(pitch)*b];};
 function project(p,w,h){const q=rotate(p),camera=span*3/zoom,focal=Math.min(w,h)*2.2;return [w/2+focal*q[0]/(camera-q[2]),h/2-focal*q[1]/(camera-q[2]),q[2]];}
 function render(){
  const ratio=devicePixelRatio||1,w=canvas.clientWidth,h=canvas.clientHeight;canvas.width=w*ratio;canvas.height=h*ratio;ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,w,h);
  const support=document.querySelector('#support'),load=document.querySelector('#load'),supportFaces=new Set([...document.querySelectorAll('.support-face')].map(s=>s.value));
  projected=d.xyz.map(p=>project(p,w,h));ordered=d.triangles.map((t,i)=>({t,i,z:t.reduce((sum,n)=>sum+projected[n][2],0)/3})).sort((a,b)=>a.z-b.z);
  for(const {t,i} of ordered){const points=t.map(n=>projected[n]),face=d.triangle_faces[i];ctx.beginPath();ctx.moveTo(...points[0].slice(0,2));ctx.lineTo(...points[1].slice(0,2));ctx.lineTo(...points[2].slice(0,2));ctx.closePath();ctx.fillStyle=fixed.has(face)||supportFaces.has(String(face))||support&&String(face)===support.value?'#5A94C2':loaded.has(face)||load&&String(face)===load.value?'#E6A265':'#C8D4DF';ctx.fill();ctx.strokeStyle='#7691A433';ctx.lineWidth=.5;ctx.stroke();}
  let arrows=d.loads||[];
  if(!arrows.length&&load&&load.value){const input=document.querySelector('#force'),values=input?.value.split(',').map(Number),face=d.geometry?.faces.find(f=>String(f.id)===load.value);if(face&&values?.length===3&&values.every(Number.isFinite))arrows=[{name:'输入总力',force_n:values,point_mm:face.centroid_mm}];}
  function arrow(point,vector,label,color){const n=Math.hypot(...vector);if(!n)return;const end=point.map((v,i)=>v+vector[i]/n*span*.15),a=project(point,w,h),b=project(end,w,h);ctx.strokeStyle=color;ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();const angle=Math.atan2(b[1]-a[1],b[0]-a[0]);ctx.beginPath();ctx.moveTo(b[0],b[1]);ctx.lineTo(b[0]-10*Math.cos(angle-.5),b[1]-10*Math.sin(angle-.5));ctx.lineTo(b[0]-10*Math.cos(angle+.5),b[1]-10*Math.sin(angle+.5));ctx.closePath();ctx.fillStyle=color;ctx.fill();ctx.font='13px system-ui';ctx.fillText(label,b[0]+5,b[1]);}
  for(const item of arrows){arrow(item.point_mm,item.force_n,item.name+' '+Math.hypot(...item.force_n).toPrecision(3)+' N','#B43B28');if(item.moment_about_surface_center_n_mm)arrow(item.centroid_mm,item.moment_about_surface_center_n_mm,'等效力矩轴 '+Math.hypot(...item.moment_about_surface_center_n_mm).toPrecision(3)+' N·mm','#8551A2');}
  canvas.dataset.rendered='true';
 }
 function inside(x,y,p){const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]),q=[x,y],a=cross(p[0],p[1],q),b=cross(p[1],p[2],q),c=cross(p[2],p[0],q);return (a>=0&&b>=0&&c>=0)||(a<=0&&b<=0&&c<=0);}
 canvas.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY};canvas.setPointerCapture(e.pointerId);});
 canvas.addEventListener('pointermove',e=>{if(!drag)return;yaw+=(e.clientX-drag.x)*.008;pitch=Math.max(-1.4,Math.min(1.4,pitch+(e.clientY-drag.y)*.008));drag.x=e.clientX;drag.y=e.clientY;render();});
 canvas.addEventListener('pointerup',e=>{if(drag&&Math.hypot(e.clientX-drag.startX,e.clientY-drag.startY)<4){const bounds=canvas.getBoundingClientRect(),x=e.clientX-bounds.left,y=e.clientY-bounds.top;for(const {t,i} of [...ordered].reverse()){if(inside(x,y,t.map(n=>projected[n]))){const face=d.triangle_faces[i];pick.textContent='完整面 '+face+'；坐标轴与当前分析一致。';const target=mode&&mode.value==='support'?(document.querySelector('.support-face[data-active="true"]')||document.querySelector('#support')):mode&&mode.value==='load'?document.querySelector('#load'):null;if(target){target.value=String(face);target.dispatchEvent(new Event('change',{bubbles:true}));render();}break;}}}drag=null;});
 canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.4,Math.min(2.5,zoom*Math.exp(-e.deltaY*.001)));render();},{passive:false});
 document.querySelector('#preflight-reset').addEventListener('click',()=>{yaw=-.65;pitch=.45;zoom=1;render();});
 for(const id of ['support','load'])document.querySelector('#'+id)?.addEventListener('change',render);
 document.querySelector('#force')?.addEventListener('input',render);
 document.addEventListener('simplecae-supports-ready',render);
 new ResizeObserver(render).observe(canvas);render();
})();
