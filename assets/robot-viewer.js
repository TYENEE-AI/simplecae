(() => {
 const d=JSON.parse(document.querySelector('#robot-data').textContent),sel=document.querySelector('#robot-pose'),canvas=document.querySelector('#robot-canvas'),ctx=canvas.getContext('2d'),legend=document.querySelector('#robot-legend'),pick=document.querySelector('#robot-pick');
 const controls=['wrenches','transfers','self-weight','pads','paths'].map(n=>document.querySelector('#robot-'+n));
 const checked=n=>document.querySelector('#robot-'+n)?.checked;
 d.poses.forEach((p,i)=>{const o=document.createElement('option');o.value=i;o.textContent=p.name;sel.append(o);});
 let yaw=-.65,pitch=.45,zoom=1,drag=null,markers=[];
 const overlays=p=>p.wrench_overlays||{wrenches:[],pads:[],probes:[]};
 const all=d.poses.flatMap(p=>p.xyz.concat(p.markers.map(m=>m.xyz),p.contacts,p.com?[p.com]:[],overlays(p).wrenches.map(w=>w.point_world_m),overlays(p).pads.map(a=>a.center_world_m)));
 if(!all.length)all.push([0,0,0]);
 const lo=[0,1,2].map(i=>all.reduce((a,p)=>Math.min(a,p[i]),Infinity)),hi=[0,1,2].map(i=>all.reduce((a,p)=>Math.max(a,p[i]),-Infinity)),center=lo.map((v,i)=>(v+hi[i])/2),span=Math.max(...hi.map((v,i)=>v-lo[i]),.01);
 const norm=v=>Math.hypot(...v),add=(a,b)=>a.map((x,i)=>x+b[i]),mul=(v,s)=>v.map(x=>x*s),sub=(a,b)=>a.map((x,i)=>x-b[i]);
 const maxF=Math.max(...d.poses.flatMap(p=>overlays(p).wrenches.map(w=>norm(w.force_world_n))),1e-12),maxM=Math.max(...d.poses.flatMap(p=>overlays(p).wrenches.map(w=>norm(w.moment_world_n_m))),1e-12);
 function render(){const p=d.poses[Number(sel.value)],w=canvas.clientWidth,h=canvas.clientHeight,r=window.devicePixelRatio||1;canvas.width=w*r;canvas.height=h*r;ctx.setTransform(r,0,0,r,0,0);ctx.clearRect(0,0,w,h);
  const project=v=>{const [x,y,z]=sub(v,center),a=Math.cos(yaw)*x-Math.sin(yaw)*y,b=Math.sin(yaw)*x+Math.cos(yaw)*y,c=Math.cos(pitch)*z-Math.sin(pitch)*b,e=Math.sin(pitch)*z+Math.cos(pitch)*b,f=Math.min(w,h)*.75*zoom/span;return [w/2+a*f,h/2-c*f,e];};
  const line=(a,b,color,dash=[])=>{const v=project(a),u=project(b);ctx.beginPath();ctx.moveTo(v[0],v[1]);ctx.lineTo(u[0],u[1]);ctx.strokeStyle=color;ctx.lineWidth=2;ctx.setLineDash(dash);ctx.stroke();ctx.setLineDash([]);return [v,u];};
  const vertices=p.xyz.map(project);p.triangles.map((t,i)=>({t,i,z:t.reduce((v,n)=>v+vertices[n][2],0)/3})).sort((a,b)=>a.z-b.z).forEach(({t})=>{const v=t.map(n=>vertices[n]);ctx.beginPath();ctx.moveTo(v[0][0],v[0][1]);ctx.lineTo(v[1][0],v[1][1]);ctx.lineTo(v[2][0],v[2][1]);ctx.closePath();ctx.fillStyle='#b4c6d9';ctx.fill();ctx.strokeStyle='#92a8bf';ctx.lineWidth=.3;ctx.stroke();});
  p.edges.forEach(e=>line(...e,'#6c839a'));
  markers=[];const dot=(xyz,label,color,entry,small=false)=>{const v=project(xyz);ctx.beginPath();ctx.arc(v[0],v[1],small?3:5,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();if(label){ctx.fillStyle='#172c42';ctx.font='12px system-ui';ctx.fillText(label,v[0]+7,v[1]-7);}markers.push({v,entry:{...entry,xyz}});};
  p.markers.forEach(m=>dot(m.xyz,m.payload?m.name:'',m.payload?'#dc9230':m.utilization>1?'#cf453c':'#2471ad',m,!m.payload));
  p.contacts.forEach((v,i)=>dot(v,'支点 '+(i+1),p.contact_feasible===false?'#cf453c':'#687b8b',{name:'地面支点'}));
  if(p.com)dot(p.com,'总质心','#8755a8',{name:'总质心'});
  let count=0,pathCount=0,padCount=0;const o=overlays(p);
  if(checked('paths'))(p.reaction_pairs||[]).forEach(pair=>{const [a,b]=pair.ports;line(a.position_m,b.position_m,'#087d78',[7,5]);dot(a.position_m,'作用端','#087d78',{name:pair.name+'/driven',force:a.force_n,moment:a.moment_n_m});dot(b.position_m,'反力端','#087d78',{name:pair.name+'/reaction',force:b.force_n,moment:b.moment_n_m});pathCount++;});
  if(checked('pads'))o.pads.forEach(a=>{const u=mul(a.tangent_u_world,a.half_extents_m[0]),v=mul(a.tangent_v_world,a.half_extents_m[1]),corners=[[1,1],[-1,1],[-1,-1],[1,-1]].map(([x,y])=>add(a.center_world_m,add(mul(u,x),mul(v,y))));corners.forEach((c,i)=>line(c,corners[(i+1)%4],'#c46705'));dot(a.center_world_m,'软垫','#c46705',{name:a.name,force:mul(a.normal_on_finger_world,a.normal_force_n),moment:[0,0,0]});padCount++;});
  function arrow(point,vector,max,color,couple){if(norm(vector)<1e-12)return;const end=add(point,mul(vector,span*.25/max)),[a,b]=line(point,end,color,couple?[3,3]:[]),angle=Math.atan2(b[1]-a[1],b[0]-a[0]);ctx.beginPath();ctx.moveTo(b[0],b[1]);ctx.lineTo(b[0]-8*Math.cos(angle-.4),b[1]-8*Math.sin(angle-.4));ctx.lineTo(b[0]-8*Math.cos(angle+.4),b[1]-8*Math.sin(angle+.4));ctx.closePath();ctx.fillStyle=color;ctx.fill();if(couple){ctx.beginPath();ctx.arc(a[0],a[1],8,0,Math.PI*1.7);ctx.strokeStyle=color;ctx.stroke();}}
  if(checked('wrenches'))o.wrenches.forEach(a=>{if(a.category==='self_weight'&&!checked('self-weight')||a.category==='component_transfer'&&!checked('transfers'))return;const color=a.category==='actuation'?'#087d78':a.category==='component_transfer'?'#ad5008':a.category==='self_weight'?'#738290':'#d67808';arrow(a.point_world_m,a.force_world_n,maxF,color,false);arrow(a.point_world_m,a.moment_world_n_m,maxM,'#8b36ad',true);dot(a.point_world_m,'',color,{name:a.name,force:a.force_world_n,moment:a.moment_world_n_m,category:a.category},true);count++;});
  o.probes.forEach(a=>dot(a.point_world_m,'测点','#b12b60',{name:a.name+'（材料点待网格确认）'}));
  [[1,0,0,'#c1443a','X'],[0,1,0,'#358347','Y'],[0,0,1,'#356ab4','Z']].forEach(a=>{const tip=add(center,mul(a.slice(0,3),span*.15));line(center,tip,a[3]);const v=project(tip);ctx.fillStyle=a[3];ctx.fillText(a[4]+' 世界',v[0],v[1]);});
  if(p.status==='preview_only')legend.textContent=`姿态 ${p.name}；仅预览，未作强度/位移/接触判定。载荷 ${count}，反力路径 ${pathCount}，软垫 ${padCount}。橙色力 N，紫色力矩轴 N·m；两类箭头分别缩放。位置单位 m。`;
  else{const ratios=Object.values(p.efforts).map(e=>e.utilization).filter(x=>x!=null),max=ratios.length?Math.max(...ratios):null;legend.textContent=`姿态 ${p.name}；关节最高利用率 ${max===null?'缺少额定值':(max*100).toFixed(1)+'%'}；${p.contact_feasible==null?'固定底座安装强度未评估':p.contact_feasible?'声明支点可满足平衡':'声明支点无法平衡'}。载荷 ${count}，反力路径 ${pathCount}。位置单位 m；箭头仅表示方向和相对幅值。`;}
  if(d.display_omissions.length)legend.textContent+=' 部分外形未显示，详见完整数据。';
  canvas.dataset.rendered='true';canvas.dataset.pose=p.name;canvas.dataset.wrenchCount=count;canvas.dataset.pathCount=pathCount;canvas.dataset.padCount=padCount;
 }
 canvas.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,sx:e.clientX,sy:e.clientY};canvas.setPointerCapture(e.pointerId);});
 canvas.addEventListener('pointermove',e=>{if(!drag)return;yaw+=(e.clientX-drag.x)*.008;pitch=Math.max(-1.4,Math.min(1.4,pitch+(e.clientY-drag.y)*.008));drag.x=e.clientX;drag.y=e.clientY;render();});
 canvas.addEventListener('pointerup',e=>{if(drag&&Math.hypot(e.clientX-drag.sx,e.clientY-drag.sy)<5){const r=canvas.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top,matches=markers.filter(m=>Math.hypot(m.v[0]-x,m.v[1]-y)<15);if(matches.length)pick.textContent=matches.map(({entry:m})=>`${m.name}：[${m.xyz.map(v=>v.toFixed(5)).join(', ')}] m${m.effort==null?'':`；保持力/矩 ${m.effort.toPrecision(5)} ${m.units}`}${m.force?`；世界力 [${m.force.map(v=>Number(v).toPrecision(5)).join(', ')}] N；表示点力矩 [${m.moment.map(v=>Number(v).toPrecision(5)).join(', ')}] N·m`:''}`).join(' | ');}drag=null;});
 canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.4,Math.min(2.5,zoom*Math.exp(-e.deltaY*.001)));render();},{passive:false});
 sel.addEventListener('change',()=>{pick.textContent='拖动旋转、滚轮缩放；点击载荷点读取世界坐标力与力矩。';render();});
 document.querySelector('#robot-reset').addEventListener('click',()=>{yaw=-.65;pitch=.45;zoom=1;render();});controls.forEach(c=>c?.addEventListener('change',render));new ResizeObserver(render).observe(canvas);render();
})();
