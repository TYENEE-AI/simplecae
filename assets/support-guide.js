(() => {
 const d=JSON.parse(document.querySelector('#intake').textContent);if(d.kind!=='solid')return;
 const primary=document.querySelector('#support'),parent=primary.closest('fieldset'),esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const row=document.createElement('div');row.className='support-row';row.dataset.name='mount1';primary.parentElement.before(row);row.append(primary.parentElement);primary.classList.add('support-face');primary.dataset.active='true';
 primary.parentElement.firstChild.textContent='支撑1完整材料面 ';
 const presetChoices='<option value="">选择真实支撑的近似方式</option>'+Object.entries(d.support_presets).map(([key,p])=>`<option value="${key}">${esc(p.label)}</option>`).join('');
 const controls=(id,removable)=>`<label>约束方式 <select class="support-preset" id="support-preset-${id}">${presetChoices}</select></label><label>分析/世界轴 <select class="support-axis" id="support-axis-${id}"><option value="">方向约束须明确选择轴</option><option value="x">X</option><option value="y">Y</option><option value="z">Z</option></select></label><p class="support-description"></p>${removable?'<button type="button" class="support-remove">移除此约束</button>':''}`;
 row.insertAdjacentHTML('beforeend',controls(1,false));
 const rows=document.createElement('div');rows.id='support-rows';row.before(rows);rows.append(row);
 const add=document.createElement('button');add.type='button';add.id='support-add';add.textContent='增加真实限位、座面或销位约束';rows.after(add);
 const status=document.createElement('p');status.id='support-status';status.setAttribute('role','status');add.after(status);
 const explanation=document.createElement('p');explanation.textContent='预设只生成明确的X/Y/Z位移分量约束；不推断单向接触、间隙、摩擦或安装真实性。导轨/销位近似的转动约束取决于区域分布；非轴向安装请调整分析坐标或使用详细连接模型。';status.after(explanation);
 // Replace the old full-fix-only explanation while retaining load/gravity inputs.
 for(const p of parent.querySelectorAll('p'))if(p.textContent.startsWith('固定面所有位移被限制'))p.textContent='载荷按完整所选面分布。实际螺钉、局部贴片、自由铰接或接触区域需要上游分区/连接建模。';
 let count=1;
 const cross=(r,e)=>[r[1]*e[2]-r[2]*e[1],r[2]*e[0]-r[0]*e[2],r[0]*e[1]-r[1]*e[0]];
 function diagnose(supports){
  const selected=new Map(),surface=d.surface;
  supports.forEach(s=>{const face=s.selector.ids[0];surface.triangles.forEach((t,i)=>{if(surface.triangle_faces[i]!==face)return;t.forEach(n=>{if(!selected.has(n))selected.set(n,new Set());s.dofs.forEach(v=>selected.get(n).add(v));});});});
  if(!selected.size)throw Error('所选材料面没有可用于预览的节点；请先核对完整面。');
  const points=[...selected.keys()].map(n=>surface.xyz[n]),center=[0,1,2].map(i=>points.reduce((sum,p)=>sum+p[i],0)/points.length),lo=[0,1,2].map(i=>Math.min(...points.map(p=>p[i]))),hi=[0,1,2].map(i=>Math.max(...points.map(p=>p[i]))),span=Math.max(Math.hypot(...hi.map((x,i)=>x-lo[i])),1e-12),a=[];
  selected.forEach((dofs,n)=>{const r=surface.xyz[n].map((x,i)=>(x-center[i])/span);dofs.forEach(dof=>{const e=[0,0,0];e[dof-1]=1;a.push(e.concat(cross(r,e)));});});
  let rank=0;const pivots=[];
  for(let col=0;col<6;col++){let best=rank;for(let i=rank;i<a.length;i++)if(Math.abs(a[i][col])>Math.abs(a[best]?.[col]||0))best=i;if(!a[best]||Math.abs(a[best][col])<1e-9)continue;[a[rank],a[best]]=[a[best],a[rank]];const pivot=a[rank][col];a[rank]=a[rank].map(x=>x/pivot);for(let i=0;i<a.length;i++){if(i===rank)continue;const factor=a[i][col];if(Math.abs(factor)<1e-12)continue;for(let j=0;j<6;j++)a[i][j]-=factor*a[rank][j];}pivots.push(col);rank++;if(rank===6)break;}
  const missing=new Set(),labels=['Tx','Ty','Tz','Rx','Ry','Rz'];for(let free=0;free<6;free++){if(pivots.includes(free))continue;const mode=[0,0,0,0,0,0];mode[free]=1;pivots.forEach((col,i)=>mode[col]=-a[i][free]);const max=Math.max(...mode.map(Math.abs));mode.forEach((v,i)=>{if(Math.abs(v)>max*.1)missing.add(labels[i]);});}
  return {rank,missing_modes:6-rank,missing_components:[...missing].sort(),scope:'Preview surface-node diagnosis of common rigid modes only; authoritative volume-mesh check still required.'};
 }
 function update(){let state;try{const supports=[],presets=[];for(const [i,r] of [...rows.children].entries()){const face=r.querySelector('.support-face').value,preset=r.querySelector('.support-preset').value,axis=r.querySelector('.support-axis').value,p=d.support_presets[preset];if(!face||!p)throw Error('请为每项支撑选择完整面和约束方式。');const selector={type:'face_ids',ids:[Number(face)],geometry_sha256:d.geometry.geometry_sha256};let dofs;
   if(!p.axis_role){dofs=[1,2,3];r.querySelector('.support-axis').disabled=true;}else{r.querySelector('.support-axis').disabled=false;if(!axis)throw Error('方向约束需明确选择分析/世界轴。');const n='xyz'.indexOf(axis)+1;dofs=['normal','stop'].includes(p.axis_role)?[n]:[1,2,3].filter(x=>x!==n);}
   r.querySelector('.support-description').textContent=p.meaning+' 当前限制位移：'+dofs.map(n=>'XYZ'[n-1]).join(', ')+'。';supports.push({name:r.dataset.name,selector,dofs});presets.push({name:r.dataset.name,preset,axis:p.axis_role?axis:null});}
   const diagnostics=diagnose(supports);state={supports,presets,diagnostics};status.textContent=diagnostics.missing_modes?`仍有 ${diagnostics.missing_modes} 个共同刚体模式未约束，涉及 ${diagnostics.missing_components.join(', ')}（T为平移，R为转动）。请补充真实限位或支撑。`:'预览支撑消除了6个共同刚体模式；体网格还会再次检查。此项不证明安装真实性、零件强度或连接刚度。';
  }catch(e){state={error:e.message};status.textContent=e.message;}document.dispatchEvent(new CustomEvent('simplecae-supports-ready',{detail:state}));}
 rows.addEventListener('change',update);rows.addEventListener('focusin',e=>{if(e.target.classList.contains('support-face')){rows.querySelectorAll('.support-face').forEach(s=>s.dataset.active='false');e.target.dataset.active='true';}});
 rows.addEventListener('click',e=>{if(e.target.classList.contains('support-remove')){e.target.closest('.support-row').remove();update();}});
 add.addEventListener('click',()=>{count++;const extra=document.createElement('div');extra.className='support-row';extra.dataset.name='mount'+count;extra.innerHTML=`<label>支撑${count}完整材料面 <select class="support-face" id="support-face-${count}">${primary.innerHTML}</select></label>`+controls(count,true);rows.append(extra);update();});
 update();
})();
