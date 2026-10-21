/* Numerical values come exclusively from registered evidence. No solver in the UI. */
'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let state = JSON.parse($('initial-state').textContent), currentId = null, datasetId = null;
  let selected = null, token = '', lastSignature = '', busy = false, renderedKey = '';
  const drafts = new Map();
  const fieldRequests = new Map();
  async function loadRun(id){
    const r=state.runs.find(r=>r.id===id);
    if(!live||!r||r.state!=='completed'||r.fields_loaded!==false||r.field_load_error||fieldRequests.has(id))return;
    const signature=r.evidence_signature;
    const controller=new AbortController();fieldRequests.set(id,controller);
    try{
      const response=await fetch('/run?id='+encodeURIComponent(id),{signal:controller.signal});
      const loaded=await response.json();
      if(!response.ok)throw Error(loaded.error||response.status);
      const fresh=state.runs.find(r=>r.id===id);
      if(fresh&&fresh.evidence_signature===signature&&[currentId,$('baseline').value].includes(id))Object.assign(fresh,loaded);
    }catch(e){const fresh=state.runs.find(r=>r.id===id);if(e.name!=='AbortError'&&fresh&&fresh.evidence_signature===signature)fresh.field_load_error=String(e.message);}
    finally{fieldRequests.delete(id);renderState();}
  }
  let modalPlaying=false, modalPhase=1, modalFrame=null;
  let motionStateId=null;
  let durabilityPointId=null;
  const modalOption=document.createElement('option');modalOption.value='mode_shape';modalOption.textContent='归一化振型';$('field').prepend(modalOption);
  const live = location.protocol === 'http:';
  const statusNames = {pass_under_stated_model:'模型内通过',fail_under_stated_model:'模型内失败',indeterminate:'证据不足',invalid:'分析无效'};
  const stageNames = {mesh:'生成网格',static:'静力求解',assessment:'核查判据',report:'生成报告',pose:'切换姿态',probe_prepare:'准备任务测点',fixed_loads:'固定载荷检查',buckling:'屈曲求解',cache_hit:'完整证据缓存',level_cache_hit:'网格证据复用'};
  const metricNames = {strength:'强度利用率',stiffness:'刚度利用率',elastic_buckling:'屈曲利用率',task_displacement:'任务位移利用率'};
  Object.assign(stageNames,{modal:'模态求解',modal_audit:'核验特征对与质量',modal_match:'跨网格振型匹配'});
  Object.assign(stageNames,{motion:'计算运动状态与反力'});
  Object.assign(stageNames,{durability:'核对材料曲线与使用历程'});
  const conditionNames={material_verified:'材料参数',dimensions_verified:'实物尺寸',supports_represent_actual_mounting:'安装约束',load_pattern_verified:'实际载荷分布',self_weight_negligible:'自重可忽略',connection_parameters_verified:'连接参数'};
  const num = v => Number.isFinite(v) ? (Math.abs(v) >= 10000 || (Math.abs(v) < .001 && v !== 0) ? v.toExponential(3) : Number(v.toPrecision(4)).toString()) : '—';
  const current = () => state.runs.find(r => r.id === currentId);
  const data = () => current()?.datasets.find(d => d.id === datasetId);
  const node = (tag, cls, text) => {const e=document.createElement(tag); if(cls)e.className=cls; if(text!==undefined)e.textContent=text; return e;};
  const replace = (id, children) => $(id).replaceChildren(...children.filter(Boolean));
  const download = (name, value) => {const a=node('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),5000);};
  const noFemTask = () => !state.runs.length && state.tasks?.length>0 && state.tasks.every(t=>t.checks?.length>0&&t.checks.every(c=>c.method!=='fem'));
  function runStatus(r){return r.state==='pending'?'尚未完成':r.state==='interrupted'?'执行中断':r.state==='unavailable'?'显示证据不可用':r.fields_loaded===false?(r.field_load_error?'场加载失败 · 重新选择可重试':'结果已登记 · 场待核验'):r.usage_feedback?.status==='insufficient_evidence'?'使用要求证据不足':!r.signal?.valid_for_comparison&&['pass_under_stated_model','fail_under_stated_model'].includes(r.status)?'证据不足（判定受限）':statusNames[r.status]||'未判定';}
  function colorClass(r){return r.fields_loaded!==false&&r.state==='completed'&&r.signal?.valid_for_comparison&&r.usage_feedback?.status!=='insufficient_evidence'?(r.status==='pass_under_stated_model'?'good':'bad'):'warning';}
  function option(value,text){const o=node('option','',text);o.value=value;return o;}
  function comparable(a,b){const usage=a&&b&&(!a.usage_feedback&&!b.usage_feedback||a.usage_contract_sha256&&a.usage_contract_sha256===b.usage_contract_sha256&&a.usage_check_id===b.usage_check_id&&a.usage_feedback?.status!=='insufficient_evidence'&&b.usage_feedback?.status!=='insufficient_evidence');return usage&&a&&b&&a.fields_loaded!==false&&b.fields_loaded!==false&&a.state==='completed'&&b.state==='completed'&&a.signal?.valid_for_comparison&&b.signal?.valid_for_comparison&&a.signal.task_id&&a.signal.task_id===b.signal.task_id&&a.signal.task_contract_sha256===b.signal.task_contract_sha256&&(!a.design_review&&!b.design_review||a.design_context_sha256&&a.design_context_sha256===b.design_context_sha256&&a.design_depth===b.design_depth&&a.design_check_execution?.state==='completed'&&b.design_check_execution?.state==='completed');}
  function counterpart(){if(data()?.physics==='modal')return null;const b=state.runs.find(r=>r.id===$('baseline').value);return comparable(current(),b)?b?.datasets.find(d=>d.label===data()?.label):null;}
  function renderState(){
    if(!state.runs.some(r=>r.id===currentId))currentId=state.runs.at(-1)?.id||null;
    // Release unselected arrays before drawing their evidence status badges.
    if(live)for(const r of state.runs)if(![currentId,$('baseline').value].includes(r.id)){r.datasets=[];r.fields_loaded=false;}
    if(live)for(const [id,controller] of fieldRequests)if(![currentId,$('baseline').value].includes(id))controller.abort();
    $('title').textContent=state.title;document.title=state.title+' · SimpleCAE';
    $('session-path').textContent=state.session;
    $('task-progress').hidden=!(state.tasks?.length);
    const completionNames={pass:'本项通过',fail:'本项失败',pending:'待完成',insufficient_evidence:'证据不足'};
    const methodNames={geometry:'几何',calculation:'计算',fem:'有限元',physical_test:'实测',information:'信息'};
    const activeTask=(state.tasks||[]).find(t=>t.session===current()?.task_workspace||t.checks?.some(c=>c.latest?.review&&c.latest.review===current()?.design_review?.path));
    replace('task-checks',(activeTask?[activeTask]:state.tasks||[]).map(t=>{
      const group=node('div','');group.append(node('h3','',(t.request||'任务证据不可用')+(t.revision_sha256?' · '+t.revision_sha256.slice(0,8):'')));
      if(t.error)group.append(node('p','warning',t.error));
      for(const c of t.checks||[]){
        const line=node('div','evidence-line');line.append(node('strong',c.outcome==='pass'?'good':c.outcome==='fail'?'bad':'warning',(completionNames[c.outcome]||c.outcome)+' · '+(methodNames[c.method]||c.method)+' · '),node('span','',c.question+(c.latest?.kind==='externally_recorded'?'（外部记录）':'')+(c.required_for_claim?'':'（可选）')));group.append(line);
        if(c.acceptance)group.append(node('p','hint','本项判据：'+c.acceptance));
        for(const assumption of c.assumptions||[])group.append(node('p','hint','条件假设（非已验证事实）：'+assumption));
        for(const gap of c.not_assessed||[])group.append(node('p','hint','未评估：'+gap));
        for(const limitation of c.latest?.limitations||[])group.append(node('p','hint','本次证据限制：'+limitation));
        if(c.latest?.analysis?.message)group.append(node('p','hint',c.latest.analysis.message));
        if(c.latest?.analysis?.error)group.append(node('p','warning','分析原因：'+c.latest.analysis.error));
        else if(c.outcome!=='pass'&&c.latest?.kind==='externally_recorded'&&c.latest.summary){
          const summary=c.latest.summary;group.append(node('p','hint','外部记录：'+summary.slice(0,500)+(summary.length>500?'…（完整证据见检查记录）':'')));
        }
      }
      if(t.unknowns?.length)group.append(node('p','hint','仍未知：'+t.unknowns.join('；')));return group;
    }));
    replace('runs',state.runs.map((r,i)=>{const b=node('button','run'+(r.id===currentId?' selected':''));b.setAttribute('role','listitem');b.setAttribute('aria-pressed',r.id===currentId?'true':'false');b.setAttribute('aria-label',r.label+'，'+runStatus(r));const top=node('span','run-top');top.append(node('span','run-label',String(i+1).padStart(2,'0')+'  '+r.label),node('span','run-status '+colorClass(r),runStatus(r)));b.append(top,node('span','run-note',r.change_note||'未记录修改说明'));b.onclick=()=>{delete r.field_load_error;drafts.set(currentId,$('note-text').value);currentId=r.id;datasetId=null;selected=null;$('note-state').textContent='';$('note-text').value=drafts.get(currentId)||'';renderState();};return b;}));
    const run=current(), previousBaseline=$('baseline').value;
    replace('dataset',(run?.datasets||[]).map(d=>option(d.id,d.label)));
    if(!run?.datasets.some(d=>d.id===datasetId))datasetId=run?.datasets[0]?.id||null;
    $('dataset').value=datasetId||'';
    replace('baseline',[option('','无'),...state.runs.filter(r=>r.id!==currentId).map(r=>option(r.id,r.label))]);
    if(state.runs.some(r=>r.id===previousBaseline&&r.id!==currentId))$('baseline').value=previousBaseline;
    else $('baseline').value=state.runs.filter(r=>r.id!==currentId&&comparable(run,r)).at(-1)?.id||'';
    $('verdict').className='verdict'+(colorClass(run||{})==='good'?' pass':colorClass(run||{})==='bad'?' fail':'');
    $('verdict').textContent=run?runStatus(run)+' · '+(run.signal?.valid_for_comparison?'仅限声明的评估范围':'结论或比较受限'):noFemTask()?'本轮未选择有限元 · 查看检查进度':'尚无分析结果';
    $('run-detail').textContent=run?(run.change_note||'本次未记录修改说明。')+(run.error?' / '+run.error:''): noFemTask()?'本轮按使用目标进行几何、计算或实测检查；需要受力分析时再由 Agent 明确建模。':'让 Agent 使用 analyze --viewer-session 将实际分析接入此会话。';
    replace('events',(run?.events||[]).map(e=>node('li','',new Date(e.at_utc).toLocaleTimeString()+'  '+(stageNames[e.stage]||e.stage)+(e.level?' · 网格 '+e.level:'')+(e.pose?' · '+e.pose:''))));
    if(run?.state==='completed'&&!run.events.length)$('events').append(node('li','','历史导入未记录执行阶段；后续 analyze --viewer-session 会记录实际过程。'));
    if(run?.state==='pending')$('events').append(node('li','warning','尚无完成结果；最后记录的阶段不代表进程仍在运行。'));
    renderDetails();renderNotes();updateComparison();const key=currentId+'/'+datasetId+'/'+run?.result_sha256;if(key!==renderedKey){renderer.fit();renderedKey=key;}renderSelection();
    loadRun(currentId);loadRun($('baseline').value);
  }
  function metric(label,value,unit,sub,bad=false){const m=node('div','metric'),head=node('div','metric-head');const v=node('span','metric-value'+(bad?' bad':''),value);v.append(node('small','',unit));head.append(node('span','metric-name',label),v);m.append(head);if(sub)m.append(node('div','metric-sub',sub));return m;}
  function renderDetails(){
    const r=current(),d=data(),s=r?.signal,results=d?.results||{};
    const motion=!!r?.motion_display,durability=!!r?.durability_display;
    $('motion-panel').hidden=!motion;
    $('durability-panel').hidden=!durability;
    $('model').parentElement.hidden=motion||durability;
    $('field').closest('.toolbar').hidden=motion||durability;
    $('legend-label').parentElement.hidden=motion||durability;
    $('selection').hidden=motion||durability;
    if(durability){
      const points=r.durability_display.points;
      replace('durability-point',Object.entries(points).map(([id,p])=>option(id,p.target+' · '+id)));
      if(!points[durabilityPointId])durabilityPointId=Object.keys(points)[0];
      $('durability-point').value=durabilityPointId||'';
      renderDurability();
    }
    if(motion){
      const states=r.motion_display.states;
      replace('motion-state',states.map(s=>option(s.id,s.id)));
      if(!states.some(s=>s.id===motionStateId))motionStateId=states[0]?.id;
      $('motion-state').value=motionStateId||'';
      renderMotion();
    }
    $('empty').hidden=!!d||!!r?.thermal_display;
    $('empty').textContent=!r?(noFemTask()?'本轮没有有限元场；已记录的几何／计算检查见下方，实物和强度结论另行核实。':'等待第一份分析结果'):r.error||(r.fields_loaded===false&&r.state==='completed'?(r.field_load_error?'场加载失败；重新选择此版本重试。':'正在按需加载并核验完整场数据…'):(r.state==='pending'?'尚无完成结果。最后阶段：'+(stageNames[r.events.at(-1)?.stage]||r.events.at(-1)?.stage||'准备输入'):'此记录没有可显示的有限元场；请查看判定与覆盖范围。'));
    $('task').textContent=r?(r.case?.provenance?.task_id||s?.task_id||'未提供任务 ID')+(r.analysis==='thermal_solid'?' · 固体传热；温度通过不代表热强度或产品通过。':r.analysis==='thermal_network'?' · 集中参数热网络；区域温度不是三维热点。':r.analysis==='urdf_static'?(r.datasets?.length?' · 机器人任务；可选择连杆查看局部有限元场。':' · 机器人刚体计算；未计算结构强度或刚度。'):' · 声明的静力工况'):noFemTask()?state.tasks[0].task_id+' · 按使用目标选择检查':'等待分析';
    if(r?.fields_loaded===false)$('task').textContent=(r.case?.provenance?.task_id||s?.task_id||'未提供任务 ID')+' · 结果摘要；完整场与分析范围待载入核验。';
    const metrics=[];
    for(const p of r?.poses||[])for(const probe of (p.task_probe_assessment?.probes||[]))metrics.push(metric(p.name+' / '+probe.name,num(probe.value_mm),'mm','末端总位移，限值 '+num(probe.allowable_displacement_mm)+' mm',probe.utilization>1));
    if(d&&!['thermal','modal'].includes(d.physics)){metrics.push(metric('最大等效应力',num(results.max_von_mises_mpa),'MPa','当前对象积分点峰值，热点未裁剪'));metrics.push(metric('最大节点位移',num(results.max_displacement_mm),'mm',r.analysis==='urdf_static'?'局部连杆场值；不是机器人末端总位移':'当前有限元模型的最大节点位移'));}
    if(d?.physics==='modal'){metrics.push(metric('最低弹性频率',num(d.modal_modes[0].frequency_hz),'Hz','三档网格与振型对应核查；刚体模态另列'));$('task').textContent=(r.case?.provenance?.task_id||'')+' · 模态频段筛查；不提供真实振幅、噪声或寿命结论。';}
    if(motion)$('task').textContent=(r.case?.provenance?.task_id||'')+' · 指定运动状态的载荷与驱动检查；未评估连杆强度、刚度或完整轨迹。';
    if(durability)$('task').textContent=(r.case?.provenance?.task_id||'')+(r.analysis==='fatigue_data'?' · 所选位置的 S–N 累积损伤检查。':' · 所选位置的恒应力、恒温蠕变应变检查。')+'不代表整件或产品寿命。';
    for(const [k,v] of Object.entries(s?.utilizations||{}).sort((a,b)=>b[1]-a[1])){const criterion=s.criterion_assessments?.[k],state=criterion?.status;const sub=state==='pass_under_stated_model'?'此判据在声明模型下通过；整体结论另列':state==='fail_under_stated_model'?'此判据在声明模型下失败':state==='indeterminate'?'此判据证据不足；保留完整峰值':state==='invalid'?'此判据无效；检查原始诊断':v>1?'超过声明限值':s.valid_for_comparison?'数值门槛通过；物理条件另核':'该读数不构成完整通过';metrics.push(metric(metricNames[k]||k,num(v),' / 1',sub,v>1));}
    for(const [k,c] of Object.entries(s?.criterion_assessments||{}))if(c.utilization==null){
      const failed=c.status==='fail_under_stated_model',passed=c.status==='pass_under_stated_model';
      if(['thermal_network','thermal_solid'].includes(r.analysis)){
        const bound=c.governing_bound,at=c.governing_location_mm,hasBound=bound==='min'||bound==='max';
        const detail='最低 '+num(c.min_temperature_c)+' / 最高 '+num(c.max_temperature_c)+' °C · 裕量 '+num(c.margin_c)+' °C · '+(failed?'失败':passed?'模型内通过':'证据不足')+(hasBound?'；控制'+(bound==='min'?'下限':'上限')+(at?' @ '+at.map(num).join(', ')+' mm':''):'')+(r.case?.mode==='steady'?'；稳态':'；'+(hasBound?'控制':'峰值')+'时刻 '+num(hasBound?c.governing_time_s:c.peak_time_s)+' s');
        metrics.push(metric(c.target||k,num(hasBound?c.governing_temperature_c:c.max_temperature_c),'°C',detail,failed));
      }
      else if(r.analysis==='modal'){const detail=c.exclusion_band_hz?'排除区间 '+c.exclusion_band_hz.map(num).join('–')+' Hz · 计算覆盖至 '+num(c.covered_upper_hz)+' Hz':'要求高于 '+num(c.minimum_hz)+' Hz · 频率区间 '+(c.frequency_interval_hz||[]).map(num).join('–')+' Hz';metrics.push(metric(c.target||k,failed?'冲突':passed?'通过':'证据不足','',detail,failed));}
      else{metrics.push(metric(metricNames[k]||k,failed?'失败':passed?'通过':'证据不足','','声明模型内的分类判据；无虚构利用率，实物适用性另核',failed));}
    }
    replace('metrics',metrics);
    const lines=[];
    lines.push(node('div','evidence-line',r?.fields_loaded===false?'完整场尚未核验，暂不提供有利排名':noFemTask()?'本轮没有有限元求解；未提供结构强度或刚度结论。':s?.valid_for_comparison?(r?.usage_feedback?.status==='insufficient_evidence'?'原模型数值门槛有效；使用要求证据不足，禁止比较':'分析有效，可在相同任务条件下比较'):'完整性或质量门槛未满足，禁止据此给出有利排名'));
    lines.push(node('div','evidence-line',s?.physical_conditions_verified?'输入物理条件已有声明核验，仍非产品验收':'物理条件尚未全部核验'));
    lines.push(node('div','evidence-line','整机 / 安装产品验收：未提供'));
    if(r?.state==='completed')lines.push(node('div','evidence-line',r.fields_loaded===false?'结果摘要已登记；完整场待按需加载核验':'结果与场文件：本次载入哈希一致'));
    if(r?.error)lines.push(node('div','notice',r.error));
    const usageLines=[];
    if(r?.usage_feedback&&r.fields_loaded!==false){
      const u=r.usage_feedback;
      const statuses={pass_under_stated_model:'本项声明模型通过，仍需实物核验',fail_under_stated_model:'本项声明模型不满足要求',insufficient_evidence:'本项证据不足，不能下结论'};
      const actions={resolve_analysis_or_inputs:'先补充输入或解决计算问题',revise_targeted_design:'针对定位区域提出一个CAD修改假设并复验',keep_and_check_remaining_requirements:'保留本轮设计，继续其余使用要求'};
      usageLines.push(node('h3','','本次使用体验'),node('p','',u.scenario.use),node('p','gap','希望达到：'+u.scenario.success),node('p','gap','本轮关注：'+u.targets.join('、')),node('p','gap','影响使用：'+u.user_impact),node('p','',statuses[u.status]||u.status),node('p','gap','下一步：'+(['joint_compliance','model_validity'].includes(r.task_guidance?.focus)?r.task_guidance.message:(actions[u.action]||u.action))));
      if(r.task_guidance?.focus==='model_validity')usageLines.push(node('p','gap',r.task_guidance.next_step));
      if(r.task_guidance?.focus==='joint_compliance'){const g=r.task_guidance;usageLines.push(node('p','gap','控制任务 '+g.pose+'/'+g.probe+' 方向贡献 / mm：关节 '+num(g.joint_contribution_mm)+' · 连杆 '+num(g.link_contribution_mm)+' · 合成 '+num(g.total_mm)+' · 限值 '+num(g.allowable_mm)));}
      if((r.usage_remaining_checks||u.remaining_required_checks).length)usageLines.push(node('p','gap','其他必检项仍待完成：'+(r.usage_remaining_checks||u.remaining_required_checks).join('；')));
      if(u.missing_result_criteria.length)usageLines.push(node('p','gap','缺少结果判据：'+u.missing_result_criteria.join('、')));
      if(Object.keys(u.confirmed_failed_criteria||{}).length)usageLines.push(node('p','gap','已确认不满足的判据：'+Object.keys(u.confirmed_failed_criteria).join('、')));
    }
    replace('usage-summary',usageLines);
    if(r?.design_context){lines.push(node('h3','','本轮设计检查'),node('p','',r.design_context.question),node('p','gap','模型范围：'+r.design_context.scope),node('p','gap','执行：'+r.design_check_execution.state+' · 总预算 '+num(r.design_check_execution.budget_seconds)+' s · 实际 '+num(r.design_check_execution.elapsed_seconds)+' s'));if(r.fields_loaded!==false)for(const action of r.design_check_feedback?.next_actions||[])lines.push(node('p','gap',action));}
    for(const f of s?.feedback||[]){const msg=f.message||JSON.stringify(f),key=msg.startsWith('condition not verified: ')?msg.slice(24):null;lines.push(node('div','gap',key?(conditionNames[key]||key)+'：未核验':(f.scope?f.scope+'：':'')+msg));}
    replace('verification',lines);
    const gaps=[];for(const g of r?.not_assessed||[])gaps.push(node('p','gap',typeof g==='string'?g:JSON.stringify(g)));
    for(const g of r?.design_context?.assumptions||[])gaps.push(node('p','gap','条件假设：'+g));
    for(const g of r?.case?.assumptions||[])gaps.push(node('p','gap','分析假设：'+g));
    for(const g of r?.design_context?.not_assessed||[])gaps.push(node('p','gap','未评估：'+g));
    for(const [k,v] of Object.entries(r?.case?.conditions||{}))gaps.push(node('p','gap',(conditionNames[k]||k)+'：'+(v===true?'已声明核验':'未核验')));
    if(r?.coverage)gaps.push(node('p','gap',JSON.stringify(r.coverage,null,2)));
    replace('gaps',gaps.length?gaps:[node('p','gap','尚无记录。')]);
    replace('source',[node('p','gap','result SHA-256: '+(r?.result_sha256||'未完成')),node('p','gap','来源: '+(r?.result||r?.out||'—')),d?node('p','gap','最终网格：'+d.mesh.node_count+' 节点 / '+d.mesh.element_count+' 单元；尺寸 '+d.mesh.mesh_size_mm+' mm'):null,node('p','gap',live?'核对文件可重新读取证据。':'离线快照仅反映导出时证据，不能检查原文件后续变化。')]);
    const inputs=[];const c=d?.case||r?.case||{};
    if(r?.analysis==='thermal_network'){for(const key of ['mode','nodes','links','fixed_temperature_c','heat_w','phases','property_temperature_range_c'])if(c[key]!==undefined)inputs.push(node('h3','',key),node('pre','',JSON.stringify(c[key],null,2)));}
    if(r?.analysis==='urdf_static'){const task={};for(const key of ['model','base','poses','payloads','elastic_transfer','probes','conditions'])if(r.case[key]!==undefined)task[key]=r.case[key];inputs.push(node('h3','','机器人总任务与关节柔度'),node('pre','',JSON.stringify(task,null,2)));}
    for(const [key,label] of [['boundaries','热边界'],['duration_s','持续时间 / s'],['material','材料'],['body_materials','各体材料'],['supports','约束'],['loads','载荷'],['gravity','重力'],['criteria','判据'],['elastic_transfer','关节与连杆柔度'],['conditions','物理假设']])if(c[key]!==undefined){inputs.push(node('h3','',label),node('pre','',JSON.stringify(c[key],null,2)));}
    replace('input-data',inputs);
    $('view-label').textContent=r?.analysis==='thermal_network'?'热网络计算 · 无三维有限元场':(d?.label||'未选择对象')+' · 局部坐标 mm';
    for(const id of ['field','deformation','mesh','reset'])$(id).disabled=!d;
    if($('spatial-hint'))$('spatial-hint').hidden=!d;
    if($('spatial-axes'))$('spatial-axes').hidden=!d;
    $('model').setAttribute('aria-label',r?.analysis==='thermal_network'?'声明区域的温度历程；不是三维热点':'有限元结果，可拖动旋转、滚轮缩放、点击选择区域');
    $('download-result').disabled=!r||r.fields_loaded===false;
    const thermal=d?.physics==='thermal',modal=d?.physics==='modal';
    $('modal-tools').hidden=!modal;
    $('deformation').parentElement.hidden=modal;
    if(modal){const old=$('modal-mode').value;replace('modal-mode',d.modal_modes.map((m,i)=>option(String(i),'第 '+m.elastic_mode+' 阶 · '+num(m.frequency_hz)+' Hz')));$('modal-mode').value=old&&Number(old)<d.modal_modes.length?old:'0';$('deformation').disabled=true;$('task').textContent+=(d.rigid_mode_count?' · '+d.rigid_mode_count+' 个刚体模态另存':'');}
    else{modalPlaying=false;modalPhase=1;$('modal-play').textContent='播放示意';}
    for(const key of ['stress','strength','displacement'])$('field').querySelector('[value="'+key+'"]').disabled=thermal||modal;
    $('field').querySelector('[value="mode_shape"]').disabled=!modal;
    $('field').querySelector('[value="temperature"]').disabled=!thermal;
    $('field').querySelector('[value="thermal_history"]').disabled=!thermal;
    if(thermal&&!['temperature','thermal_history','boundary'].includes($('field').value))$('field').value='temperature';
    if(modal&&!['mode_shape','boundary'].includes($('field').value))$('field').value='mode_shape';
    if(!thermal&&!modal&&['temperature','thermal_history','mode_shape'].includes($('field').value))$('field').value='stress';
    if(thermal){$('deformation').value='0';$('deformation').disabled=true;}
    $('field').querySelector('[value="strength"]').disabled=!d?.strength?.length;
    if($('field').value==='strength'&&!d?.strength?.length)$('field').value='stress';
  }
  function renderMotion(){
    const display=current()?.motion_display,s=display?.states.find(s=>s.id===motionStateId);
    if(!s)return;
    const contents=[node('p','hint',display.meaning)],table=node('table','motion-table');
    const head=node('tr');for(const text of ['关节','所需力 / 力矩','速度','加速度'])head.append(node('th','',text));table.append(head);
    for(const [name,j] of Object.entries(s.joints)){
      const row=node('tr'),rotational=j.effort_unit==='N m';
      for(const text of [name,j.effort==null?'固定连接':num(j.effort)+' '+j.effort_unit,
          j.effort==null?'—':num(j.speed)+(rotational?' rad/s':' m/s'),
          j.effort==null?'—':num(j.acceleration)+(rotational?' rad/s²':' m/s²')])row.append(node('td','',text));
      table.append(row);
    }
    contents.push(table,node('h3','','机器人施加给安装座的载荷'));
    const w=s.base.robot_on_base_world;
    contents.push(node('p','','力 [X, Y, Z] = ['+w.slice(0,3).map(num).join(', ')+'] N'),
      node('p','','力矩 [X, Y, Z] = ['+w.slice(3).map(num).join(', ')+'] N·m'),
      node('p','hint','世界坐标；力矩参考点 ['+s.base.point_world_m.map(num).join(', ')+'] m。各分量来自同一状态，不能与其他状态的峰值拼接。'));
    const detail=node('details'),summary=node('summary','','连杆惯性分量');detail.append(summary);
    for(const [name,b] of Object.entries(s.bodies))detail.append(node('p','hint',name+
      ' · 质心加速度 ['+b.center_acceleration_m_s2.map(num).join(', ')+'] m/s² · 惯性力矩（质心） ['+
      b.inertial_moment_at_com_n_m.map(num).join(', ')+'] N·m'));
    contents.push(detail);replace('motion-values',contents);
  }
  $('motion-state').onchange=()=>{motionStateId=$('motion-state').value;renderMotion();};
  function renderDurability(){
    const d=current()?.durability_display,p=d?.points[durabilityPointId];if(!p)return;
    const contents=[node('p','hint',d.meaning),node('p','',p.target+' · '+p.frame+' 坐标 ['+p.position_mm.map(num).join(', ')+'] mm')];
    const gaps={missing_material_curve:'缺少材料曲线',material_manufacture_or_orientation_mismatch:'材料、制造方式或方向不匹配',
      temperature_not_covered:'温度超出已提供数据',stress_ratio_not_covered:'缺少该平均应力／应力比的数据',
      stress_amplitude_outside_curve:'应力幅超出曲线范围',constant_stress_needs_static_or_creep_check:'恒定应力应另查静力或蠕变',
      undefined_stress_ratio:'应力比无法按当前定义计算',constant_stress_outside_curve:'恒定应力不在数据范围内',
      duration_outside_curve:'持续时间超出数据范围',creep_strain_measure_mismatch:'总应变与纯蠕变应变的定义不一致'};
    if(p.gaps.length)contents.push(node('p','notice','证据缺口：'+p.gaps.map(g=>gaps[g]||g).join('；')+'。未进行外推。'));
    if(d.mode==='fatigue_data'){
      contents.push(node('h3','','循环损伤组成'),node('p','',p.damage==null?
        '总损伤尚不能确定；已覆盖部分的损伤下界为 '+num(p.known_damage_lower_bound):
        '累积损伤 D = '+num(p.damage)+'（无量纲；不是失效概率）'));
      const table=node('table','motion-table'),head=node('tr');
      for(const text of ['载荷段','最小 / 最大应力 MPa','应力幅 MPa','应力比 R','次数 n','曲线寿命 N','损伤 n/N'])head.append(node('th','',text));table.append(head);
      for(const b of p.blocks){const row=node('tr');for(const text of [b.service_id,num(b.minimum_mpa)+' / '+num(b.maximum_mpa),
          num(b.amplitude_mpa),num(b.stress_ratio),num(b.cycles),num(b.cycles_to_failure),num(b.damage)])row.append(node('td','',text));table.append(row);}
      contents.push(table,node('p','hint','应力幅是范围的一半。曲线寿命仅适用于该应力比、温度、制造条件与应力定义；无曲线的载荷段不会被按零损伤处理。'));
    }else{
      const label=p.strain_measure==='creep_only_magnitude'?'纯蠕变应变':'总轴向应变';
      contents.push(node('h3','',label+'历程'),node('p','','恒定应力 '+num(p.stress_mpa)+' MPa；末值 '+(p.strain==null?'尚不能确定':num(p.strain*100)+'%')));
      const criteria=Object.values(d.criteria).filter(c=>c.point===durabilityPointId);
      if(p.history.length){
        const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 640 250');svg.setAttribute('role','img');svg.setAttribute('aria-label',label+'随时间变化，虚线为限值');
        const maxX=p.history.at(-1)[0],maxY=Math.max(...p.history.map(v=>v[1]),...criteria.map(c=>c.limit),1e-12)*1.15;
        const x=v=>55+v/maxX*555,y=v=>210-v/maxY*175;
        const element=(tag,attrs,text)=>{const e=document.createElementNS(svg.namespaceURI,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,String(v));if(text!=null)e.textContent=text;svg.append(e);return e;};
        element('path',{d:'M55 35V210H610',fill:'none',stroke:'#84929e'});
        for(const c of criteria)element('line',{x1:55,x2:610,y1:y(c.limit),y2:y(c.limit),stroke:'#ad7740','stroke-dasharray':'6 4'});
        element('polyline',{points:p.history.map(v=>x(v[0])+','+y(v[1])).join(' '),fill:'none',stroke:'#34617b','stroke-width':2});
        for(const [xx,yy,text] of [[55,233,'0 s'],[530,233,num(maxX)+' s'],[8,35,num(maxY*100)+'%'],[8,210,'0%']])element('text',{x:xx,y:yy,fill:'#53616c','font-size':12},text);
        contents.push(svg,node('p','hint','仅在给定应力和时间网格内部线性插值；应变以百分比显示，JSON 中为无量纲小数。未推断破断时间或结构整体位移。'));
      }
    }
    for(const c of Object.values(d.criteria).filter(c=>c.point===durabilityPointId))contents.push(node('p','hint',
      c.quantity==='damage'?'损伤限值 '+num(c.limit):'应变限值 '+num(c.limit*100)+'%'));
    replace('durability-values',contents);
  }
  $('durability-point').onchange=()=>{durabilityPointId=$('durability-point').value;renderDurability();};
  function updateComparison(){
    const a=current(),b=state.runs.find(r=>r.id===$('baseline').value),valid=comparable(a,b);
    $('overlay').disabled=!valid||!counterpart();if($('overlay').disabled)$('overlay').checked=false;
    let text='选一版查看变化';
    if(b&&!valid)text='任务条件不同或证据不完整，停止数值比较';
    if(valid){const changes=[];for(const key of ['strength','stiffness']){const x=a.signal.utilizations[key],y=b.signal.utilizations[key];if(Number.isFinite(x)&&Number.isFinite(y)&&y>0)changes.push((metricNames[key]||key)+' '+((x/y-1)*100>=0?'+':'')+num((x/y-1)*100)+'%');}text='同一任务 · '+(changes.join(' / ')||'判据可比较')+(a.analysis==='motion_loads'?' · 相同关节运动状态，工作空间另查':a.analysis==='thermal_network'?' · 温度判据，无空间场叠加':' · 共享色标');}
    $('compare-message').textContent=text;renderer.draw();
    if(valid&&a.analysis==='modal')$('compare-message').textContent='同一任务 · 判据可比较；CAD 改变后的同阶编号不保证对应同一振型，不自动叠加';
    if(valid&&a.durability_display)$('compare-message').textContent='同一使用历程、材料数据与判据 · 仅比较声明位置的耐久检查';
  }
  function renderSelection(){
    const r=current(),d=data();
    if(selected&&(!d||selected.dataset_id!==d.id||selected.run_id!==r?.id))selected=null;
    const text=selected?'面 '+d.face_ids[selected.triangle]+' / 单元 '+d.element_ids[selected.triangle]+' / 区域中心 ['+selected.point.map(num).join(', ')+'] mm':r?.analysis==='thermal_network'?'节点对应 Agent 声明的区域；完整历史和热路径见结果文件':'点击模型，查看实际单元与区域位置';
    $('selection').textContent=text;$('note-target').textContent=selected?text:'未选择区域，将添加整版批注';renderer.draw();
  }
  function renderNotes(){const notes=state.notes.filter(n=>n.run_id===currentId);$('note-count').textContent=notes.length;replace('notes-list',notes.map(n=>{const e=node('div','note',n.text);e.append(node('small','',(n.region?n.region.dataset+' / 面 '+n.region.face_id:'整版批注')+' · '+new Date(n.created_at_utc).toLocaleString()),node('small','','已保存，未自动执行'));return e;}));}
  async function post(route,value){const res=await fetch(route,{method:'POST',headers:{'Content-Type':'application/json','X-SimpleCAE-Token':token},body:JSON.stringify(value)});const r=await res.json();if(!res.ok)throw Error(r.error||res.status);return r;}
  $('save-note').onclick=async()=>{const r=current(),text=$('note-text').value.trim();if(!r||r.state!=='completed'||!text){$('note-state').textContent='请先选择完整结果并填写批注。';return;}const value={run_id:r.id,result_sha256:r.result_sha256,text,...(selected?{dataset_id:selected.dataset_id,triangle:selected.triangle}:{})};try{if(live){await post('/feedback',value);await refresh(true);$('note-state').textContent='已保存到 feedback；等待 Agent 读取。';}else{download('simplecae-feedback.json',{schema_version:'simplecae-viewer-feedback-1.0',...value,result:r.result,region:selected?{dataset:data().label,point_mm:selected.point,face_id:data().face_ids[selected.triangle],element_id:data().element_ids[selected.triangle]}:null,meaning:'Offline user annotation; not an executed instruction.'});$('note-state').textContent='离线批注已下载，请交给 Agent。';}$('note-text').value='';}catch(e){$('note-state').textContent='保存失败：'+e.message;}};
  $('download-result').onclick=()=>download('simplecae-review.json',current());
  document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('.panel').forEach(x=>x.classList.toggle('active',x.id===b.dataset.tab));});
  $('dataset').onchange=()=>{datasetId=$('dataset').value;selected=null;renderDetails();updateComparison();renderer.fit();renderSelection();};
  ['field','deformation','mesh','overlay'].forEach(id=>$(id).onchange=()=>renderer.draw());
  $('baseline').onchange=()=>{const r=state.runs.find(r=>r.id===$('baseline').value);if(r)delete r.field_load_error;renderState();renderer.fit();};
  $('reset').onclick=()=>renderer.fit();
  $('modal-mode').onchange=()=>{selected=null;renderer.draw();};
  $('modal-play').onclick=()=>{cancelAnimationFrame(modalFrame);modalPlaying=!modalPlaying;$('modal-play').textContent=modalPlaying?'暂停示意':'播放示意';if(modalPlaying)modalFrame=requestAnimationFrame(animateModal);else{modalPhase=1;renderer.draw();}};
  function animateModal(t){if(!modalPlaying||data()?.physics!=='modal')return;modalPhase=Math.sin(t*.003);renderer.draw();modalFrame=requestAnimationFrame(animateModal);}

  class Renderer {
    constructor(canvas){this.canvas=canvas;this.ctx=canvas.getContext('2d');this.yaw=-.65;this.pitch=.55;this.zoom=1;this.pan=[0,0];this.pick=[];let drag=null;
      new ResizeObserver(()=>this.draw()).observe(canvas);
      canvas.onpointerdown=e=>{drag={x:e.clientX,y:e.clientY,moved:0};canvas.setPointerCapture(e.pointerId);};
      canvas.onpointermove=e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.moved+=Math.abs(dx)+Math.abs(dy);if(e.shiftKey){this.pan[0]+=dx;this.pan[1]+=dy;}else{this.yaw+=dx*.008;this.pitch=Math.max(-1.5,Math.min(1.5,this.pitch+dy*.008));}drag.x=e.clientX;drag.y=e.clientY;this.draw();};
      canvas.onpointerup=e=>{if(drag&&drag.moved<5)this.select(e);drag=null;};canvas.onpointercancel=()=>{drag=null;};
      canvas.onwheel=e=>{e.preventDefault();this.zoom=Math.max(.15,Math.min(20,this.zoom*Math.exp(-e.deltaY*.001)));this.draw();};
    }
    fit(){this.zoom=1;this.pan=[0,0];this.draw();}
    project(p){const q=p.map((v,i)=>v-this.center[i]),cy=Math.cos(this.yaw),sy=Math.sin(this.yaw),cp=Math.cos(this.pitch),sp=Math.sin(this.pitch);const x=cy*q[0]-sy*q[1],y=sy*q[0]+cy*q[1];return [this.w/2+x*this.scale+this.pan[0],this.h/2-(cp*q[2]-sp*y)*this.scale+this.pan[1],sp*q[2]+cp*y];}
    fieldValues(d){switch($('field').value){case 'mode_shape':{const m=d.modal_modes[Number($('modal-mode').value)||0];return d.triangles.map(t=>Math.max(...t.map(i=>m.nodal_magnitude[i])));}case 'temperature':return d.temperature;case 'displacement':return d.triangles.map(t=>Math.max(...t.map(i=>Math.hypot(...d.displacements[i]))));case 'strength':return d.strength;default:return d.stress;}}
    color(value,max){const stops=[[45,87,137],[76,159,168],[201,206,140],[219,161,83],[179,74,60]],s=Math.max(0,Math.min(1,value/(max||1)))*4,i=Math.min(3,Math.floor(s)),f=s-i;return stops[i].map((c,j)=>Math.round(c*(1-f)+stops[i+1][j]*f));}
    draw(){const d=data(),c=this.canvas,ctx=this.ctx;this.w=c.clientWidth;this.h=c.clientHeight;if(!this.w||!this.h)return;const ratio=Math.min(window.devicePixelRatio||1,2);if(c.width!==Math.round(this.w*ratio)||c.height!==Math.round(this.h*ratio)){c.width=Math.round(this.w*ratio);c.height=Math.round(this.h*ratio);}ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,this.w,this.h);this.pick=[];
      if(d){const historyView=$('field').value==='thermal_history';for(const id of ['spatial-hint','spatial-axes'])if($(id))$(id).hidden=historyView;$('view-label').textContent=historyView?'区域温度历程 · 最细网格':d.label+' · 局部坐标 mm';$('mesh').disabled=historyView;}
      if(!d){$('legend-label').textContent=current()?.thermal_display?'区域温度 / °C · 虚线为声明温度限值':'尚无可显示的场';$('field-note').textContent=current()?.thermal_display?'曲线仅作显示抽样，保留极值和阶段边界；全部历史见结果文件':'';for(const id of ['ramp','legend-min','legend-max'])$(id).style.display='none';if(current()?.thermal_display)this.thermal(current().thermal_display);return;}
      if($('field').value==='thermal_history'&&d.thermal_history){$('legend-label').textContent='区域最高／最低温度历程 / °C';$('field-note').textContent='最细网格的全部时刻；全局判定保留每档网格与时间步的极值';for(const id of ['ramp','legend-min','legend-max'])$(id).style.display='none';this.thermal(d.thermal_history);return;}
      const other=counterpart(),all=other?d.xyz.concat(other.xyz):d.xyz,lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];for(const p of all)for(let i=0;i<3;i++){lo[i]=Math.min(lo[i],p[i]);hi[i]=Math.max(hi[i],p[i]);}this.center=lo.map((v,i)=>(v+hi[i])/2);this.scale=1;const projected=all.map(p=>this.project(p)),screenLo=[Infinity,Infinity],screenHi=[-Infinity,-Infinity];for(const p of projected)for(let i=0;i<2;i++){screenLo[i]=Math.min(screenLo[i],p[i]);screenHi[i]=Math.max(screenHi[i],p[i]);}this.scale=.72*Math.min(this.w/(screenHi[0]-screenLo[0]||1),this.h/(screenHi[1]-screenLo[1]||1))*this.zoom;
      const field=$('field').value,values=this.fieldValues(d),others=other?this.fieldValues(other):[];
      const fullMax=x=>field==='mode_shape'?1:field==='temperature'?x?.results.max_temperature_c:field==='stress'?x?.results.max_von_mises_mpa:field==='displacement'?x?.results.max_displacement_mm:x?.assessment.strength_utilization;
      const maximum=values.concat(others,[fullMax(d)??-Infinity,fullMax(other)??-Infinity]).reduce((a,b)=>Math.max(a,b),field==='temperature'?-Infinity:field==='strength'?1:0);
      const minimum=field==='temperature'?Math.min(d.temperature_min_c,other?.temperature_min_c??Infinity):0;
      $('legend-label').textContent={temperature:'温度 / °C',stress:'等效应力 / MPa',strength:'强度利用率 / 1',displacement:'位移模长 / mm',boundary:'蓝：约束　橙：载荷面'}[field];if(field==='boundary'&&d.physics==='thermal')$('legend-label').textContent='蓝：恒温　橙：热输入／对流';$('legend-min').textContent=num(minimum);$('legend-max').textContent=num(maximum);$('ramp').style.display=field==='boundary'?'none':'';$('legend-min').style.display=field==='boundary'?'none':'';$('legend-max').style.display=field==='boundary'?'none':'';
      const modal=d.physics==='modal',factor=modal?(field==='boundary'?0:modalPhase*d.display_amplitude_mm):Number($('deformation').value);$('field-note').textContent=modal?'归一化节点振型，最大节点模长为 1；示意幅度和慢放速度任意，不是物理位移':field==='temperature'?'二次面片峰值映射；圆点标出实体峰值（可能在内部）':factor?'变形 ×'+factor+'；原形为灰线':field==='displacement'?'三角形节点模长最大值 / mm':field==='boundary'?'安装与载荷条件仍须核实':'积分点峰值映射，未裁剪热点';
      if(modal&&field!=='boundary'){$('legend-label').textContent='归一化节点振型模长 / 1';$('view-label').textContent='弹性振型 '+(Number($('modal-mode').value)+1)+' · '+num(d.modal_modes[Number($('modal-mode').value)||0].frequency_hz)+' Hz · 几何坐标 mm';}
      if(factor)this.wire(d.xyz,d.triangles,'rgba(110,124,135,.17)');
      if($('overlay').checked&&other)this.wire(other.xyz,other.triangles,'rgba(70,84,95,.38)');
      const displacement=modal?d.modal_modes[Number($('modal-mode').value)||0].normalized_shape:d.displacements;
      const points=d.xyz.map((p,i)=>this.project(p.map((v,j)=>v+factor*displacement[i][j]))),triangles=d.triangles.map((t,i)=>({i,t,p:t.map(n=>points[n]),z:t.reduce((s,n)=>s+points[n][2],0)/3})).sort((a,b)=>a.z-b.z);
      const support=new Set(Object.values(d.mesh.support_faces||{}).flat()),load=new Set((d.mesh.loads||[]).flatMap(l=>l.face_ids||[]));
      for(const tri of triangles){const p=tri.p;ctx.beginPath();ctx.moveTo(p[0][0],p[0][1]);ctx.lineTo(p[1][0],p[1][1]);ctx.lineTo(p[2][0],p[2][1]);ctx.closePath();let rgb=field==='boundary'?(support.has(d.face_ids[tri.i])?[67,115,157]:load.has(d.face_ids[tri.i])?[196,136,66]:[193,203,211]):this.color((values[tri.i]??0)-minimum,Math.max(maximum-minimum,1e-12));
        const cross=(p[1][0]-p[0][0])*(p[2][1]-p[0][1])-(p[1][1]-p[0][1])*(p[2][0]-p[0][0]);const light=cross<0?.95:1;ctx.fillStyle='rgb('+rgb.map(v=>Math.round(v*light)).join(',')+')';ctx.fill();if($('mesh').checked){ctx.strokeStyle='rgba(34,50,61,.22)';ctx.lineWidth=.45;ctx.stroke();}this.pick.push(tri);
      }
      if(field==='temperature'&&d.hotspot){const at=this.project(d.hotspot.max_location_mm);ctx.beginPath();ctx.arc(at[0],at[1],5,0,2*Math.PI);ctx.fillStyle='#241c17';ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.stroke();ctx.fillStyle='#241c17';ctx.font='12px Segoe UI';ctx.fillText(num(d.hotspot.max_temperature_c)+' °C',at[0]+9,at[1]-7);}
      if(field==='boundary')for(const l of d.mesh.loads||[]){const f=l.total_force_n||[0,0,0],norm=Math.hypot(...f);if(!norm)continue;const at=l.centroid_mm||[0,0,0],span=45/this.scale,a=this.project(at.map((v,i)=>v-span*f[i]/norm)),b=this.project(at);this.arrow(a,b,'#80521e');}
      if(selected&&selected.run_id===currentId&&selected.dataset_id===d.id){const tri=this.pick.find(t=>t.i===selected.triangle);if(tri){ctx.beginPath();tri.p.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.closePath();ctx.fillStyle='rgba(255,255,255,.35)';ctx.fill();ctx.strokeStyle='#1e3547';ctx.lineWidth=2;ctx.stroke();}}
      const origin=this.project(this.center),axes=[[1,0,0,'#a05d51','X'],[0,1,0,'#5f8164','Y'],[0,0,1,'#527c9b','Z']];for(const a of axes){const p=this.project(this.center.map((v,i)=>v+a[i]*30/this.scale));const offset=[45-origin[0],this.h-43-origin[1]];const start=[origin[0]+offset[0],origin[1]+offset[1]],end=[p[0]+offset[0],p[1]+offset[1]];this.arrow(start,end,a[3]);ctx.fillStyle=a[3];ctx.font='10px Segoe UI';ctx.fillText(a[4],end[0]+3,end[1]);}
    }
    thermal(display){
      const ctx=this.ctx,series=display.series;if(!series.length)return;
      const colors=['#2c6485','#b35c36','#587c56','#815887','#916e26','#3d8a89','#9c4b67','#626879'];
      let low=Infinity,high=-Infinity,end=0;
      for(const s of series){for(const [t,v] of s.points){low=Math.min(low,v);high=Math.max(high,v);end=Math.max(end,t);}for(const v of s.limits_c){low=Math.min(low,v);high=Math.max(high,v);}}
      const pad=Math.max(2,(high-low)*.08);low-=pad;high+=pad;
      const left=48,right=this.w-24,top=65+series.length*18,bottom=this.h-48;
      if(bottom<=top+40)return;
      const x=t=>end?left+t/end*(right-left):(left+right)/2,y=v=>bottom-(v-low)/(high-low)*(bottom-top);
      ctx.font='12px Segoe UI';ctx.fillStyle='#394d5a';ctx.fillText(data()?.physics==='thermal'?'三维场区域极值历程；位置见温度场与判据记录':'声明区域温度；不能用于认定空间热点',left,45);
      series.forEach((s,i)=>{ctx.fillStyle=colors[i];ctx.fillText(s.target.slice(0,50),left,66+i*18);});
      for(let i=0;i<=4;i++){const v=low+(high-low)*i/4;ctx.strokeStyle='#dfe5e8';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(left,y(v));ctx.lineTo(right,y(v));ctx.stroke();ctx.fillStyle='#52636f';ctx.fillText(num(v),4,y(v)+4);}
      series.forEach((s,i)=>{ctx.strokeStyle=colors[i];ctx.fillStyle=colors[i];ctx.lineWidth=2;ctx.beginPath();s.points.forEach(([t,v],j)=>j?ctx.lineTo(x(t),y(v)):ctx.moveTo(x(t),y(v)));ctx.stroke();if(s.points.length===1){ctx.beginPath();ctx.arc(x(0),y(s.points[0][1]),5,0,Math.PI*2);ctx.fill();}ctx.setLineDash([5,5]);ctx.lineWidth=1;for(const v of s.limits_c){ctx.beginPath();ctx.moveTo(left,y(v));ctx.lineTo(right,y(v));ctx.stroke();}ctx.setLineDash([]);});
      ctx.fillStyle='#52636f';ctx.fillText(end?'0 s':'稳态计算',left,bottom+24);if(end)ctx.fillText(num(end)+' s',right-55,bottom+24);
      if(display.omitted_nodes)ctx.fillText('另有 '+display.omitted_nodes+' 个节点，全部判据见结果信息',left,this.h-6);
    }
    wire(xyz,tris,color){const ctx=this.ctx,p=xyz.map(x=>this.project(x));ctx.beginPath();for(const t of tris){ctx.moveTo(p[t[0]][0],p[t[0]][1]);ctx.lineTo(p[t[1]][0],p[t[1]][1]);ctx.lineTo(p[t[2]][0],p[t[2]][1]);ctx.closePath();}ctx.strokeStyle=color;ctx.lineWidth=.55;ctx.stroke();}
    arrow(a,b,color){const ctx=this.ctx,angle=Math.atan2(b[1]-a[1],b[0]-a[0]);ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();ctx.beginPath();ctx.moveTo(b[0],b[1]);for(const s of [-1,1])ctx.lineTo(b[0]-7*Math.cos(angle+s*.38),b[1]-7*Math.sin(angle+s*.38));ctx.closePath();ctx.fill();}
    select(e){const d=data();if(!d)return;const rect=this.canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;const hit=this.pick.slice().reverse().find(({p})=>{const a=(p[1][0]-x)*(p[2][1]-y)-(p[1][1]-y)*(p[2][0]-x),b=(p[2][0]-x)*(p[0][1]-y)-(p[2][1]-y)*(p[0][0]-x),c=(p[0][0]-x)*(p[1][1]-y)-(p[0][1]-y)*(p[1][0]-x);return Math.abs(a+b+c)>.01&&((a>=0&&b>=0&&c>=0)||(a<=0&&b<=0&&c<=0));});selected=hit?{run_id:currentId,dataset_id:d.id,triangle:hit.i,point:[0,1,2].map(i=>hit.t.reduce((s,n)=>s+d.xyz[n][i],0)/3)}:null;renderSelection();}
  }
  const renderer=new Renderer($('model'));
  async function refresh(force=false){if(!live||busy)return;busy=true;try{const response=await fetch('/index');if(!response.ok)throw Error('HTTP '+response.status);const index=await response.json();if(force||index.signature!==lastSignature){const response=await fetch('/state');if(!response.ok)throw Error('无法核对证据');const next=await response.json();for(const r of next.runs){const old=state.runs.find(v=>v.id===r.id);if(r.state==='completed'&&old?.state==='completed'&&old.fields_loaded&&old.evidence_signature===r.evidence_signature){r.datasets=old.datasets;r.fields_loaded=true;r.status=old.status;r.signal=old.signal;}}state=next;token=state.feedback_token;lastSignature=index.signature;renderState();}$('connection').textContent='已连接 · 阶段记录每 3 秒同步';}catch(e){$('connection').textContent='连接中断 · 保留最近快照';}finally{busy=false;}}
  $('refresh').onclick=()=>live?refresh(true):($('connection').textContent='离线快照 · 启动 view --serve 可核对原文件');
  renderState();if(live){$('connection').textContent='正在核对并加载证据…';refresh(true);setInterval(refresh,3000);}else $('connection').textContent='离线快照 · '+new Date(state.exported_at_utc).toLocaleString();
})();
