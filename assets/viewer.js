(() => {
  const d = JSON.parse(document.querySelector('#cae-data').textContent);
  const canvas = document.querySelector('#cae-canvas'), ctx = canvas.getContext('2d');
  const select = document.querySelector('#cae-field'), slider = document.querySelector('#cae-scale');
  const legend = document.querySelector('#cae-legend'), pick = document.querySelector('#cae-pick');
  if(d.strength?.length){const o=document.createElement('option');o.value='strength';o.textContent='强度利用率（100% 为输入限制）';select.prepend(o);select.value='strength';}
  Object.keys(d.modes).forEach(key => { const o=document.createElement('option');o.value=key;o.textContent='屈曲形状 '+key.split('-').pop();select.append(o); });
  const lo=[0,1,2].map(i=>d.xyz.reduce((a,p)=>Math.min(a,p[i]),Infinity)), hi=[0,1,2].map(i=>d.xyz.reduce((a,p)=>Math.max(a,p[i]),-Infinity));
  const center=lo.map((v,i)=>(v+hi[i])/2), span=Math.max(...hi.map((v,i)=>v-lo[i]));
  const norm=v=>Math.hypot(...v); let yaw=-.65,pitch=.45,zoom=1,drag=null,animated=false,phase=0,projected=[];
  const color=t=>{t=Math.max(0,Math.min(1,t));const stops=[[35,85,170],[30,170,180],[245,198,60],[212,55,45]];const x=t*3,i=Math.min(2,Math.floor(x)),f=x-i;return stops[i].map((v,j)=>Math.round(v+(stops[i+1][j]-v)*f));};
  const rotate=p=>{const x=p[0]-center[0],y=p[1]-center[1],z=p[2]-center[2];const a=Math.cos(yaw)*x-Math.sin(yaw)*y,b=Math.sin(yaw)*x+Math.cos(yaw)*y;return [a,Math.cos(pitch)*z-Math.sin(pitch)*b,Math.sin(pitch)*z+Math.cos(pitch)*b];};
  function render(){
    const ratio=window.devicePixelRatio||1, width=canvas.clientWidth,height=canvas.clientHeight;
    if(canvas.width!==Math.round(width*ratio)||canvas.height!==Math.round(height*ratio)){canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);}
    ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,width,height);
    const field=select.value, mode=d.modes[field], vectors=mode||d.displacements;
    const maxVector=vectors.reduce((a,v)=>Math.max(a,norm(v)),0), amplitude=animated?Math.sin(phase):1;
    const factor=(field==='stress'||field==='strength')?0:Number(slider.value)*span*.12/Math.max(maxVector,1e-30)*amplitude;
    const points=d.xyz.map((p,i)=>rotate(p.map((x,k)=>x+factor*vectors[i][k])));
    const camera=span*3/zoom, focal=Math.min(width,height)*2.2;
    projected=points.map(p=>[width/2+focal*p[0]/(camera-p[2]),height/2-focal*p[1]/(camera-p[2]),p[2]]);
    const vals=field==='strength'?d.strength:field==='stress'?d.stress:d.triangles.map(t=>Math.max(...t.map(n=>norm(vectors[n]))));
    const max=vals.reduce((a,v)=>Math.max(a,v),-Infinity),min=vals.reduce((a,v)=>Math.min(a,v),Infinity);
    const order=d.triangles.map((t,i)=>({t,i,z:t.reduce((a,n)=>a+points[n][2],0)/3})).sort((a,b)=>a.z-b.z);
    order.forEach(({t,i})=>{const p=t.map(n=>projected[n]);ctx.beginPath();ctx.moveTo(p[0][0],p[0][1]);ctx.lineTo(p[1][0],p[1][1]);ctx.lineTo(p[2][0],p[2][1]);ctx.closePath();const rgb=color(vals[i]/Math.max(max,field==='strength'?1:1e-30));ctx.fillStyle=`rgb(${rgb})`;ctx.fill();ctx.strokeStyle=`rgba(${rgb},0.35)`;ctx.lineWidth=.4;ctx.stroke();});
    legend.textContent=mode?`屈曲模态：归一化形状幅值 ${min.toPrecision(3)}–${max.toPrecision(3)}。幅值任意，此动画不是动力响应。`:field==='strength'?`强度利用率 ${(min*100).toFixed(1)}%–${(max*100).toFixed(1)}%；超过 100% 表示超出声明的允许值。包含各材料自己的判据；实际结论还需通过网格、工况和条件验证。`:field==='stress'?`蓝色较低，红色较高；von Mises 应力 ${min.toPrecision(3)}–${max.toPrecision(3)} MPa，仅作应力描述，方向性材料不按它判断强度。`:`实际位移范围 ${min.toPrecision(3)}–${max.toPrecision(3)} mm；显示放大约 ${Math.abs(factor).toPrecision(3)} 倍。`;
    canvas.dataset.rendered='true';
    if(animated){phase+=.035;requestAnimationFrame(render);}
  }
  canvas.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,originX:e.clientX,originY:e.clientY};canvas.setPointerCapture(e.pointerId);});
  canvas.addEventListener('pointermove',e=>{if(!drag)return;yaw+=(e.clientX-drag.x)*.008;pitch=Math.max(-1.4,Math.min(1.4,pitch+(e.clientY-drag.y)*.008));drag.x=e.clientX;drag.y=e.clientY;if(!animated)render();});
  canvas.addEventListener('pointerup',e=>{if(drag&&Math.hypot(e.clientX-drag.originX,e.clientY-drag.originY)<4){const r=canvas.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;let best=-1,dist=Infinity;projected.forEach((p,i)=>{const s=(p[0]-x)**2+(p[1]-y)**2;if(s<dist){dist=s;best=i;}});if(best>=0&&dist<900){const p=d.xyz[best];pick.textContent=`当前位置 [${p.map(v=>v.toFixed(2)).join(', ')}] mm；实际位移 ${norm(d.displacements[best]).toPrecision(4)} mm。`;}}drag=null;});
  canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.4,Math.min(2.2,zoom*Math.exp(-e.deltaY*.001)));if(!animated)render();},{passive:false});
  select.addEventListener('change',()=>{if(!animated)render();});slider.addEventListener('input',()=>{if(!animated)render();});
  document.querySelector('#cae-reset').addEventListener('click',()=>{yaw=-.65;pitch=.45;zoom=1;if(!animated)render();});
  document.querySelector('#cae-animate').addEventListener('click',e=>{animated=!animated;e.target.textContent=animated?'暂停演示':'形状演示';if(animated)render();});
  new ResizeObserver(()=>{if(!animated)render();}).observe(canvas);render();
})();
