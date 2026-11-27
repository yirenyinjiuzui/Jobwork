'use strict';

const qs = (s, root=document) => root.querySelector(s);
const content = qs('#content');
const errorBox = qs('#errors');
const statusBox = qs('#status');
const statusLabels = {saved:'待投递', submitted:'已投递', waiting:'待反馈', assessment:'笔试／网测', interview:'面试', offer:'Offer', closed:'流程终止'};
const typeLabels = {intern:'实习', graduate:'校招', other:'其他／待核实'};
const providerLabels = {greenhouse:'Greenhouse', greenhouse_eu:'Greenhouse 欧洲', lever:'Lever', lever_eu:'Lever 欧洲', ashby:'Ashby', smartrecruiters:'SmartRecruiters', demo:'演示数据'};
const emptyState = () => ({applications:[],companies:[],sources:[],jobs:[],notifications:[],today:[],profile:{}});
let pendingActions=0, pollActive=false, desktopAlerts=false;
let captureDraft=null, applicationView='list';
const applicationPageSize=150;
let applicationLimit=applicationPageSize;
let state=emptyState(), tab='dashboard', currentEdit=null, companyEdit=null, sourceEdit=null, search='', statusFilter='', jobSearch='', jobRoute='', openOnly=true, generation=0;
let resumeSchema;
let profileHasChanges=null;
const pages=['dashboard','discovery','tracking','profile'];

function node(tag, cls='', ...children){
  const o=document.createElement(tag);
  if(cls) o.className=cls;
  for(const c of children.flat(Infinity)){
    if(c!==null && c!==undefined && c!==false) o.append(c.nodeType?c:document.createTextNode(String(c)));
  }
  return o;
}
function paragraph(text, cls='muted'){return node('p',cls,text);}
function empty(text){return node('div','empty',text);}
function badge(label,cls=''){return node('span','badge '+cls,label);}
function btn(text,fn,cls=''){
  const o=node('button','btn '+cls,text); o.type='button';
  if(fn) o.addEventListener('click',()=>withBusy(o,fn));
  return o;
}
function submit(text){const o=btn(text,null,'primary');o.type='submit';return o;}
function link(label, url, cls=''){
  if(!url)return null;
  try{const u=new URL(url, location.origin);
    if(!['http:','https:'].includes(u.protocol)||u.username||u.password||(!(String(url).startsWith('/')&&!String(url).startsWith('//'))&&!/^https?:\/\//i.test(url)))return null;
    const o=node('a',cls,label);o.href=u.href;o.target='_blank';o.rel='noopener noreferrer';return o;
  }catch{return null;}
}
function list(items){return node('ul','rows',items);}
function row(main,...actions){return node('li','row',node('div','row-main',main),actions.filter(Boolean).length?node('div','row-actions',actions):null);}
function card(title,...body){return node('section','card',node('h2','',title),body);}
function head(k,title,sub,actions=[]){return node('header','hero',node('div','',node('p','eyebrow',k),node('h1','',title),paragraph(sub)),actions.length?node('div','hero-actions',actions):null);}
function field(formKey,key,label,opts={}){
  const {kind='text', value='', required=false, placeholder='', full=false, options=[], hint='', maxLength=400}=opts;
  const id=formKey+'-'+key;
  const l=node('label','',label);l.htmlFor=id;
  let input;
  if(kind==='textarea'){input=node('textarea');input.rows=3;}
  else if(kind==='select'){
    input=node('select');
    for(const [v,name] of options){const o=node('option','',name);o.value=v;input.append(o);}
  } else {input=node('input'); input.type=kind;}
  input.name=key;input.id=id;input.required=required;input.placeholder=placeholder;
  if(opts.step)input.step=opts.step;
  if(kind==='file') input.accept=opts.accept||'';
  else input.value=value??'';
  if(!['file','select','datetime-local','date','checkbox'].includes(kind)) input.maxLength=maxLength;
  const note=hint?node('span','subtle',hint):null;if(note){note.id=id+'-hint';input.setAttribute('aria-describedby',note.id);}
  return node('div','field'+(full?' full':''),l,input,note);
}
function actualData(form){return Object.fromEntries([...new FormData(form)].filter(([,v])=>typeof v==='string').map(([k,v])=>[k,v.trim()]));}
function form(children, onSubmit, buttonText, extra=[]){
  const f=node('form','',children,node('div','actions',submit(buttonText),extra));
  f.addEventListener('submit',event=>{event.preventDefault();const b=f.querySelector('[type=submit]');withBusy(b,()=>onSubmit(f));});
  return f;
}
function details(title,...children){return node('details','details',node('summary','',title),children);}
function announce(msg, isError=false){
  const el=isError?errorBox:statusBox;
  el.textContent=msg||'';el.hidden=!msg;
}
function clearMessages(){announce('');announce('',true);}
async function withBusy(button,fn){
  if(button.disabled) return;
  button.disabled=true;pendingActions++;clearMessages();
  try{await fn();}
  catch(e){announce(e instanceof Error?e.message:'操作失败，请稍后再试。',true);}
  finally{button.disabled=false;pendingActions--;}
}
async function request(url,body){
  const init=body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};
  let response;
  try{response=await fetch(url,init);}catch{throw new Error('无法连接本地服务。请检查启动窗口是否仍在运行。');}
  let obj;
  try{obj=await response.json();}catch{throw new Error('本地服务返回无法读取的结果。');}
  if(!response.ok||obj?.error){
    const error=new Error(typeof obj?.error==='string'?obj.error:'服务请求失败（'+response.status+'）。');
    error.status=response.status;throw error;
  }
  return obj;
}
async function refresh(){
  const thisGen=++generation;
  const [next,schema]=await Promise.all([request('/api/state'),resumeSchema||request('/resume-fields.json')]);
  if(thisGen!==generation)return;
  resumeSchema=schema;
  state={...emptyState(),...next};
  render();
}
async function mutate(path,payload,message,after){
  const r=await request(path,payload);
  if(after)after(r);
  await refresh();
  if(message)announce(typeof message==='function'?message(r):message);
  return r;
}
function niceDate(value){
  if(!value) return '';
  const s=String(value);
  if(/^\d{4}-\d\d-\d\d$/.test(s))return s;
  const d=new Date(s);
  if(Number.isNaN(d.getTime()))return s;
  return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Hong_Kong',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(d);
}
function fieldDate(value){
  if(!value)return '';
  if(/^\d{4}-\d\d-\d\d$/.test(value))return value;
  const d=new Date(value);
  if(Number.isNaN(d.getTime()))return value;
  const entries=Object.fromEntries(new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Hong_Kong',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(d).map(x=>[x.type,x.value]));
  return entries.year+'-'+entries.month+'-'+entries.day+' '+entries.hour+':'+entries.minute;
}
const captureKeys=['company','title','requisition','location','career_type','deadline','url','eligibility','start','description'];
function captureFromHash(){
  const prefix='#discovery?';
  const route=location.hash;
  if(!route.startsWith(prefix)||!route.slice(prefix.length).startsWith('capture='))return false;
  window.history.replaceState(window.history.state,'','#discovery');
  tab='discovery';
  try{
    const rest=route.slice(prefix.length);
    if(rest.length>24000)throw new Error();
    const params=new URLSearchParams(rest);
    if(params.size!==1)throw new Error();
    const raw=JSON.parse(params.get('capture'));
    if(!raw||typeof raw!=='object'||Array.isArray(raw))throw new Error();
    const next=Object.fromEntries(captureKeys.map(k=>[k,typeof raw[k]==='string'?raw[k].trim().slice(0,k==='url'?2200:k==='description'?600:400):'']));
    if(!Object.hasOwn(typeLabels,next.career_type))next.career_type='other';
    if(next.url){
      try{
        const u=new URL(next.url);
        if(!['http:','https:'].includes(u.protocol)||u.username||u.password)next.url='';
        else {
          u.hash='';
          // Only retain query keys commonly used for public job identifiers.
          const publicKeys=new Set(['gh_jid','jobid','job_id','positionid','requisitionid','reqid','postingid','id']);
          for(const key of [...u.searchParams.keys()])if(!publicKeys.has(key.toLowerCase()))u.searchParams.delete(key);
          next.url=u.href;
        }
      }catch{next.url='';}
    }
    if(!captureKeys.some(k=>k!=='career_type'&&next[k]))throw new Error();
    captureDraft=next;
    announce('已接收岗位草稿。核对信息后点击「录入岗位」，目前尚未保存。');
  }catch{
    announce('岗位草稿无法读取，请重试浏览器扩展或手动录入。',true);
  }
  return true;
}
function bringCaptureIntoView(){
  const section=qs('#manual-job');
  if(!captureDraft||!section||tab!=='discovery')return;
  section.scrollIntoView({block:'center'});
  qs('#job-company')?.focus({preventScroll:true});
}
function allowProfileExit(){
  if(profileHasChanges?.()&&!window.confirm('资料有未保存的改动。确定放弃草稿并离开？取消可继续编辑。')){
    if(location.hash!=='#profile')location.hash='profile';
    return false;
  }
  profileHasChanges=null;
  return true;
}
function setTab(next, focus=true){
  if(!pages.includes(next))return;
  if(tab==='profile'&&(next==='profile'||!allowProfileExit()))return;
  tab=next;
  if(location.hash!=='#'+next)location.hash=next;
  clearMessages();render();
  if(focus){qs('#main').focus({preventScroll:true});window.scrollTo({top:0});}
}
function goTrack(app){
  currentEdit=app?.id||null;
  setTab('tracking');
  if(app) queueMicrotask(()=>qs('#editor')?.scrollIntoView({block:'start'}));
}
function render(){
  if(tab==='profile'&&profileHasChanges?.())return;
  document.querySelectorAll('[data-tab]').forEach(x=>{
    const selected=x.dataset.tab===tab;
    x.classList.toggle('active',selected);
    if(selected)x.setAttribute('aria-current','page');else x.removeAttribute('aria-current');
  });
  content.replaceChildren(...({dashboard,discovery,tracking,profile}[tab])().filter(Boolean));
  content.removeAttribute('aria-busy');
}
function statusName(x){return statusLabels[x]||'待核实';}
function plain(s){return String(s??'').trim();}
function equalId(a,b){return a!==null&&a!==undefined&&b!==null&&b!==undefined&&String(a)===String(b);}
function shortMeta(...p){return node('div','meta',p.filter(Boolean).join(' · '));}
function precisionLabel(record,key){
  const p=record.date_precision?.[key];
  if(!record[key])return '';
  if(p==='estimated')return '（推算）';
  if(p==='date'||p==='date_only'||/^\d{4}-\d\d-\d\d$/.test(record[key]))return '（未注明时刻）';
  return '';
}
function stamp(record,key,label){return record[key]?label+' '+niceDate(record[key])+precisionLabel(record,key):'';}
function deadlineStamp(a){return a.status==='interview'?stamp(a,'interview_reply_by','面试回复截止'):stamp(a,'deadline','截止');}
function calendarContents(a){
  const l=calendarLink(a);return l?[l,paragraph('导出 .ics 文件，不自动同步。','subtle')]:[];
}
function calendarLink(a){
  if(!/^[1-9]\d*$/.test(String(a.id)))return null;
  if(!((['saved','assessment','offer'].includes(a.status)&&a.deadline)||(a.status==='interview'&&(a.interview_at||a.interview_reply_by))))return null;
  const l=link('导出日历 (.ics)','/api/calendar?id='+encodeURIComponent(a.id),'btn small');
  l.removeAttribute('target');l.title='下载文件，不自动同步日历';return l;
}
async function enableDesktopAlerts(){
  const granted=Notification.permission==='granted' ? 'granted' : await Notification.requestPermission();
  if(granted!=='granted'){announce('浏览器未允许桌面提醒；不影响工作台内提醒。');return;}
  desktopAlerts=true;announce('已为当前页面开启桌面提醒。关闭页面后只保存工作台内提醒。');render();
}
async function pollDashboard(){
  if((tab!=='dashboard'&&!desktopAlerts)||pendingActions||pollActive||(document.hidden&&!desktopAlerts))return;
  pollActive=true;
  const previousGeneration=generation;
  try{
    const data=await request('/api/state');
    if((tab!=='dashboard'&&!desktopAlerts)||pendingActions||previousGeneration!==generation)return;
    const next={...emptyState(),...data};
    if(JSON.stringify(next)===JSON.stringify(state))return;
    const known=new Set(state.notifications.map(n=>n.id));
    const additions=next.notifications.filter(n=>!n.read&&!known.has(n.id));
    state=next;if(tab==='dashboard')render();
    if(additions.length&&desktopAlerts&&Notification.permission==='granted'){
      try{new Notification('求职工作台',{body:'有 '+additions.length+' 条新的岗位提醒，打开工作台查看。',tag:'job-workbench'});}catch{ /* In-app reminders are still available. */ }
    }
  }catch{ /* The visible workbench remains usable if a background check fails. */ }
  finally{pollActive=false;}
}
function updateClock(){
  qs('#clock').textContent='香港时间 '+new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Hong_Kong',month:'long',day:'numeric',weekday:'short',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date());
}
function dashboard(){
  const active=state.applications.filter(a=>!['closed','offer','saved'].includes(a.status)).length;
  const unread=state.notifications.filter(n=>!n.read);
  const todos=state.today;
  const counts=node('div','stats',[[todos.length,'当前待办'],[active,'推进中的投递'],[unread.length,'未读开招提醒']].map(([n,name])=>node('div','stat',node('b','',n),node('span','',name))));
  const taskRows=todos.slice(0,8).map(a=>{
    const why=typeof a.reason==='string'?a.reason:'';
    const target=a.next_action||({assessment:'查看网测要求',interview:'准备面试',saved:'决定是否投递'}[a.status]||'查看进展');
    return row([node('strong','',target),shortMeta(a.company,a.title),shortMeta(why||null,deadlineStamp(a),stamp(a,'interview_at','面试')),badge(statusName(a.status),a.status)],calendarLink(a),btn('看记录',()=>goTrack(a),'small'));
  });
  const alertRows=state.notifications.slice(0,12).map(n=>row([node('strong','',n.title||'岗位更新'),n.read?null:' ',n.read?null:badge('新','active'),n.body?paragraph(n.body,'meta'):null,shortMeta(n.created_at?niceDate(n.created_at):'')],link('原始入口',n.url,'btn small'),n.read?null:btn('标为已读',()=>mutate('/api/notifications/read',{id:n.id},'已标为已读。'),'small')));
  return [head('工作台 / 01','今天先做什么','开招、网测、面试与下一步放在同一个地方。',[btn('+ 记一笔投递',()=>{currentEdit=null;goTrack(null);queueMicrotask(()=>qs('#editor')?.scrollIntoView());},'primary')]),counts,node('div','grid',card('优先处理',paragraph('根据记录里的日期和当前状态安排，等回复的岗位无需反复翻查。','meta'),taskRows.length?list(taskRows):empty('暂无需要处理的事项。添加投递记录，或导入一封网测、面试通知。'),todos.length>8?paragraph('其余记录可在投递追踪查看。','subtle'):null),card('岗位提醒',paragraph('首次成功检查只建立基线，以后发现新岗位或重新开放时，会在这里提示。启动本机程序后才会轮询。','meta'),typeof Notification!=='undefined'&&!desktopAlerts?btn('开启桌面提醒（本页）',enableDesktopAlerts,'small'):null,alertRows.length?list(alertRows):empty('还没有开招提醒。请先在「公司与岗位」添加招聘来源。'),unread.length?node('div','actions',btn('全部标为已读',()=>mutate('/api/notifications/read',{},'已标记全部提醒为已读。'),'small')):null)),state.applications.length===0?card('先试用模拟数据',paragraph('不会读取真实邮箱，也不会联系招聘方。'),btn('载入演示记录',()=>mutate('/api/demo',{},'演示记录已加载。'))):null];
}
function inferHK(loc){return /香港|hong\s*kong|\bHKSAR\b|\bHK\b|Kowloon|九龍|九龙/i.test(loc||'');}
function mainlandCandidate(loc){
  const s=plain(loc);
  return !!s&&!inferHK(s)&&/中国大陆|中国内地|中国(?!香港|澳門|澳门|台湾|臺灣)|\bChina\b|mainland|北京|深圳|上海|广州|廣州|杭州|成都|武汉|武漢|珠海|南京|苏州|蘇州|西安|天津|重庆|重慶|长沙|長沙|厦门|廈門|合肥|青岛|青島|宁波|寧波|济南|濟南|北上广深|Beijing|Shenzhen|Shanghai|Guangzhou|Hangzhou|Chengdu|Wuhan|Zhuhai|Nanjing|Suzhou|Tianjin|Chongqing/i.test(s)&&!/澳門|澳门|台湾|臺灣|Macao|Macau|Taiwan/i.test(s);
}
function discovery(){
  const company=state.companies.find(c=>equalId(c.id,companyEdit))||{};
  const source=state.sources.find(s=>equalId(s.id,sourceEdit))||{};
  const companyForm=form(node('div','fields',
    field('company','name','公司名称',{value:company.name,required:true}),
    field('company','website','公司官网',{kind:'url',value:company.website,placeholder:'https://…'}),
    field('company','career_url','招聘官网',{kind:'url',value:company.career_url,placeholder:'https://…'}),
    field('company','notes','备注',{value:company.notes,maxLength:800})),
    f=>{const d=actualData(f);if(company.id)d.id=company.id;return mutate('/api/company',d,'公司记录已保存。',()=>{companyEdit=null;});},company.id?'保存公司':'添加公司',company.id?[btn('取消编辑',()=>{companyEdit=null;render();})]:[]);
  const sourceForm=form(node('div','fields',
    field('source','company','显示的公司名称',{value:source.company,required:true}),
    field('source','provider','招聘来源',{kind:'select',value:source.provider||'greenhouse',options:Object.entries(providerLabels)}),
    field('source','board','公开招聘站标识',{value:source.board,required:true,full:true,placeholder:'例如：jobs.lever.co/示例 中的「示例」',hint:'支持 Greenhouse、Lever、Ashby、SmartRecruiters。只填网址中的公司标识，演示来源填 sample。'})),
    f=>{const d=actualData(f);if(source.id)d.id=source.id;return mutate('/api/source',d,'招聘来源已保存。',()=>{sourceEdit=null;});},source.id?'保存来源':'添加来源',source.id?[btn('取消编辑',()=>{sourceEdit=null;render();})]:[]);
  const companyRows=state.companies.map(c=>row([node('strong','',c.name),c.notes?paragraph(c.notes,'meta'):null],link('招聘官网',c.career_url,'btn small'),link('公司官网',c.website,'btn small'),btn('编辑',()=>{companyEdit=c.id;render();qs('#company-name')?.focus();},'small')));
  const sourceRows=state.sources.map(s=>row([node('strong','',s.company),' ',badge(providerLabels[s.provider]||s.provider),shortMeta(s.board,s.last_checked?'上次检查 '+niceDate(s.last_checked):'未检查'),s.last_error?paragraph(s.last_error,'meta'):null],btn('检查',()=>mutate('/api/source/check',{id:s.id},r=>checkMessage(r)),'small'),btn('编辑',()=>{sourceEdit=s.id;render();qs('#source-company')?.focus();},'small'),btn('移除',()=>{if(window.confirm('移除该招聘来源？'))return mutate('/api/source/delete',{id:s.id},'已移除来源。',()=>{if(equalId(sourceEdit,s.id))sourceEdit=null;});},'small')));
  const draft=captureDraft||{};
  const manual=form(node('div','fields',
    field('job','company','公司',{value:draft.company,required:true}),
    field('job','title','岗位名称',{value:draft.title,required:true}),
    field('job','requisition','岗位编号',{value:draft.requisition,placeholder:'如有就填写'}),
    field('job','location','页面地点标注（保留原文）',{value:draft.location,placeholder:'例如：香港'}),
    field('job','description','地点相关原文与来源（限 600 字）',{kind:'textarea',value:draft.description,full:true,maxLength:600,hint:'保留实习、转正与异地培训安排的原文；缺失或矛盾会列为待复核。'}),
    field('job','career_type','岗位类型',{kind:'select',value:draft.career_type||'other',options:Object.entries(typeLabels)}),
    field('job','deadline','截止时间（香港）',{value:draft.deadline,placeholder:'2026-12-01 或 2026-12-01 18:00'}),
    field('job','eligibility','毕业或资格要求',{value:draft.eligibility,placeholder:'例如：2027 届／硕士在读'}),
    field('job','start','到岗条件',{value:draft.start,placeholder:'例如：12 月起，每周 3 天'}),
    field('job','url','职位原始网址',{kind:'url',value:draft.url,placeholder:'https://…',maxLength:2200,full:true})),
    f=>mutate('/api/job',actualData(f),'岗位已录入。',()=>{captureDraft=null;}),'录入岗位',captureDraft?[btn('放弃草稿',()=>{
      if(window.confirm('放弃这个尚未保存的岗位草稿？')){captureDraft=null;render();qs('#manual-job summary')?.focus();}
    })]:[]);
  if(captureDraft)manual.addEventListener('input',()=>{captureDraft=actualData(manual);});
  const manualDetails=details('手动录入岗位',captureDraft?node('div','notice warn','扩展导入的草稿尚未保存，请核对公司、岗位、截止日期与网页地址。'):null,paragraph('BOSS、企业自建官网等未接入的来源，可以粘贴分享链接，也可由扩展提取公开职位信息。','meta'),manual);
  manualDetails.id='manual-job';manualDetails.open=Boolean(captureDraft);
  const routeField=field('job-filter','route','筛选范围',{kind:'select',value:jobRoute,options:[['','全部范围'],['hk','香港实习'],['cn','内地校招'],['intern','所有地区实习'],['graduate','所有地区校招']]});
  qs('select',routeField).addEventListener('change',e=>{jobRoute=e.target.value;renderJobs(jobHolder);});
  const searchField=field('job-filter','search','搜索岗位',{kind:'search',value:jobSearch,placeholder:'输入公司、岗位或地点'});
  qs('input',searchField).addEventListener('input',e=>{jobSearch=e.target.value;renderJobs(jobHolder);});
  const only=node('input');only.type='checkbox';only.checked=openOnly;only.addEventListener('change',()=>{openOnly=only.checked;renderJobs(jobHolder);});
  const jobHolder=node('div');jobHolder.id='job-results';renderJobs(jobHolder);
  return [head('工作台 / 02','公司与岗位','收藏招聘入口，监测公开职位，把值得投的岗位放进台账。',[btn('检查全部招聘源',()=>mutate('/api/source/check',{},r=>checkMessage(r)),'primary')]),
    node('div','grid equal stack',card('目标公司',paragraph('添加公司官网和校招入口。','meta'),companyForm,companyRows.length?list(companyRows):empty('还没有目标公司。')),card('招聘来源',paragraph('仅检查公开招聘接口，不登录、不绕过站点限制。','meta'),sourceForm,sourceRows.length?list(sourceRows):empty('添加来源后再点「检查」。'))),
    card('可投岗位',paragraph('公开招聘接口不一定提供毕业或到岗条件；职位详情和资格以原始入口为准。','meta'),node('div','inline',routeField,searchField,node('label','check',only,'只看开放岗位')),jobHolder,manualDetails)];
}
function checkMessage(r){
  const results=r?.results||[];
  if(!results.length)return '还没有可检查的招聘来源。请先添加一个。';
  const errors=results.filter(x=>x.error);
  const openings=results.reduce((sum,x)=>sum+Number(x.new||0)+Number(x.reopened||0),0);
  const baseline=results.filter(x=>x.baseline).length;
  const uncertain=results.reduce((sum,x)=>sum+Number(x.unverified||0),0);
  return '检查结束：'+(openings?'发现 '+openings+' 个新开或重新开放岗位；':'没有新开或重新开放岗位；')+(baseline?' '+baseline+' 个来源已建立基线；':'')+(uncertain?' 有 '+uncertain+' 项暂不可核实，保留最后状态；':'')+(errors.length?' '+errors.length+' 个来源失败，具体原因见来源列表。':'可在总览查看提醒。');
}
function recordSearch(query){
  const normalize=value=>String(value??'').normalize('NFKC').toLowerCase();
  const terms=normalize(query).trim().split(/\s+/).filter(Boolean);
  return record=>{
    const fields=[record.company,record.title,record.location,record.requisition].map(normalize);
    return terms.every(term=>fields.some(value=>value.includes(term)));
  };
}
function renderJobs(target){
  const pool=state.jobs.filter(j=>!openOnly||j.active!==false&&j.active!==0)
    .filter(recordSearch(jobSearch));
  const rows=pool.filter(j=>jobRoute==='hk'?j.career_type==='intern'&&j.location_review?.hk_onsite===true:jobRoute==='cn'?j.career_type==='graduate'&&(['mainland','both'].includes(j.region)||!j.region&&mainlandCandidate(j.location)):!jobRoute||j.career_type===jobRoute);
  const review=jobRoute==='hk'?pool.filter(j=>j.career_type==='intern'&&j.location_review?.requires_review):[];
  target.replaceChildren(shortMeta((jobRoute==='hk'?'正文支持香港实地实习 ':'匹配 ')+rows.length+' 个岗位'+(rows.length>120?' · 显示前 120 个':'')));
  const renderRow=j=>row([node('strong','',j.title),' ',badge(typeLabels[j.career_type]||typeLabels.other),j.active===false||j.active===0?badge('已下架','closed'):null,
    shortMeta(j.company,'原地点：'+(j.location||'未标注'),j.requisition?'编号 '+j.requisition:null,j.deadline?'截止 '+niceDate(j.deadline):null),
    j.source_verification?paragraph(j.source_verification.message,'meta'):null,
    j.source_verification?.closure_evidence?paragraph('关闭核实记录：'+j.source_verification.closure_evidence.reason+' · '+j.source_verification.closure_evidence.confirmed_at,'meta'):null,
    j.source_verification?.close_token?btn('核对原页后确认关闭',()=>{if(window.confirm('请先打开职位详情，确认原页明确说明此岗位已关闭。接口空列表、超时或页面打不开不算关闭证据。确认关闭「'+j.title+'」？'))return mutate('/api/job/confirm-closed',{id:j.id,token:j.source_verification.close_token,reviewed:true,evidence_url:j.url,reason:'用户核对原职位页明确显示岗位已关闭'},'已按人工核实证据关闭岗位；投递记录未改。');},'small'):null,
    j.identity_review?paragraph(j.identity_review,'meta'):null,
    j.location_review?node('div','',badge(j.location_review.requires_review?'地点待复核':j.location_review.hk_onsite?'正文支持香港实习':'地点信息'),paragraph(j.location_review.reason,'meta'),details('地点证据与来源',list(j.location_review.evidence.map(e=>row(paragraph(e.source+'：'+e.quote,'meta')))))):null,
    j.eligibility?shortMeta('毕业要求：'+j.eligibility):null,j.start?shortMeta('到岗条件：'+j.start):null,j.description?details('查看摘要',paragraph(j.description.slice(0,600),'meta')):null],link('职位详情',j.url,'btn small'),btn('存到投递台账',()=>mutate('/api/job/save',{id:j.id},'已存入投递台账。'),'small'));
  if(rows.length)target.append(list(rows.slice(0,120).map(renderRow)));
  else target.append(empty('没有符合当前筛选的明确岗位。可查看待复核项或切回全部范围。'));
  if(review.length)target.append(node('section','details',node('h3','','地点待复核（不计入香港实地实习）：'+review.length+' 个'),paragraph('仍可查看、手动核对和收藏；没有删除或覆盖原地点。','meta'),list(review.slice(0,120).map(renderRow))));
}

function tracking(){
  const a=state.applications.find(a=>equalId(a.id,currentEdit))||{};
  const searchField=field('app-filter','search','搜索记录',{kind:'search',value:search,placeholder:'输入公司、岗位或编号'});
  const filterField=field('app-filter','status','当前状态',{kind:'select',value:statusFilter,options:[['','全部状态'],...Object.entries(statusLabels)]});
  const holder=node('div');holder.id='application-results';holder.tabIndex=-1;
  const switches=['list','board'].map(view=>{
    const b=btn(view==='list'?'列表':'看板',()=>{
      applicationView=view;
      switches.forEach((x,i)=>x.setAttribute('aria-pressed',String((i===0?'list':'board')===view)));
      renderApplications(holder);
    },'view-choice');
    b.setAttribute('aria-pressed',String(view===applicationView));
    b.setAttribute('aria-controls',holder.id);
    return b;
  });
  const viewPicker=node('div','view-switch',switches);viewPicker.setAttribute('role','group');viewPicker.setAttribute('aria-label','投递查看方式');
  renderApplications(holder);
  qs('input',searchField).addEventListener('input',e=>{search=e.target.value;applicationLimit=applicationPageSize;renderApplications(holder);});
  qs('select',filterField).addEventListener('change',e=>{statusFilter=e.target.value;applicationLimit=applicationPageSize;renderApplications(holder);});
  const resumeExamples=[state.profile?.resume_zh,state.profile?.resume_en].filter(Boolean)
    .map(x=>String(x).split(/[\\/]/).filter(Boolean).slice(-1)[0]).filter(Boolean);
  const editorCalendar=node('div','calendar-action',calendarContents(a));editorCalendar.id='editor-calendar';
  const editor=card(a.id?'编辑投递记录':'记录一笔投递',
    form(node('div','fields',
      field('app','company','公司',{value:a.company,required:true}),
      field('app','title','岗位名称',{value:a.title,required:true}),
      field('app','requisition','岗位编号',{value:a.requisition}),
      field('app','location','工作地点',{value:a.location}),
      field('app','career_type','岗位类型',{kind:'select',value:a.career_type||'other',options:Object.entries(typeLabels)}),
      field('app','status','当前状态',{kind:'select',value:a.status||'saved',options:Object.entries(statusLabels)}),
      field('app','submitted_at','实际投递时间（香港，可留空）',{value:fieldDate(a.submitted_at),placeholder:'2026-11-01 10:00',hint:'填写实际提交申请的时间；不是录入时间或面试时间。不确定请留空。'}),
      field('app','deadline','申请或其他流程截止（香港）',{value:fieldDate(a.deadline),placeholder:'2026-12-01 或 2026-12-01 18:00',hint:a.status==='interview'&&a.deadline?'原截止保留供核对。如果招聘方要求限时回复，请填写面试回复期限。':''}),
      field('app','interview_at','面试时间（香港）',{value:fieldDate(a.interview_at),placeholder:'2026-12-01 18:00'}),
      field('app','interview_reply_by','面试回复期限（香港，可留空）',{value:fieldDate(a.interview_reply_by),placeholder:'2026-12-01 或 2026-12-01 18:00'}),
      field('app','resume_label','实际使用的简历版本',{value:a.resume_label,full:true,placeholder:'例如：英文简历 v3',hint:resumeExamples.length?'资料库版本：'+resumeExamples.join('、'):'只记版本名，不上传文件。'}),
      field('app','next_action','下一步',{value:a.next_action,full:true,placeholder:'例如：完成网测；等待回复'}),
      field('app','source_url','来源链接',{kind:'url',value:a.source_url,full:true,placeholder:'https://…'})),
      f=>{
        const d=actualData(f);
        if(a.id){
          d.id=a.id;
          const saved=state.applications.find(row=>equalId(row.id,a.id))||a;
          for(const k of ['deadline','interview_at','interview_reply_by','submitted_at']){
            if(d[k]===fieldDate(saved[k]))delete d[k];
          }
        }
        return mutate('/api/application',d,'投递记录已保存。',r=>{currentEdit=r.application?.id||r.id||a.id||null;});
      },a.id?'保存修改':'添加记录',
      a.id?[btn('切换到新增',()=>{currentEdit=null;render();qs('#app-company')?.focus();})]:[]),
    editorCalendar,
    a.id?historyDetails(a):null);
  editor.id='editor';
  return [head('工作台 / 03','投递追踪','区分每个岗位的状态，改期和延期留在同一条时间线。',[btn('+ 新增记录',()=>{currentEdit=null;render();qs('#editor')?.scrollIntoView();qs('#app-company')?.focus({preventScroll:true});},'primary'),link('导出投递 CSV','/api/export','btn')]),
    node('div','grid stack',editor,noticeCard(a)),
    card('全部投递',node('div','inline',searchField,filterField,viewPicker),holder)];
}
function renderApplications(target){
  const rows=state.applications.filter(a=>!statusFilter||a.status===statusFilter).filter(recordSearch(search));
  const visible=rows.slice(0,applicationLimit);
  target.replaceChildren(shortMeta('匹配 '+rows.length+' 条记录'+(visible.length<rows.length?' · 已显示 '+visible.length+' 条':'')));
  if(!rows.length){target.append(empty('暂无匹配的投递。先建立一条投递记录，或导入模拟数据。'));return;}
  if(applicationView==='board')target.append(applicationBoard(visible,target));
  else target.append(list(visible.map(a=>row([node('strong','',a.title),' ',badge(statusName(a.status),a.status),
    shortMeta(a.company,a.location,a.requisition?'编号 '+a.requisition:null,a.resume_label?'简历 '+a.resume_label:null),
    a.assessment_tasks?.length?details('各测评状态',list(a.assessment_tasks.map(t=>paragraph(t.id+'：'+(t.completed?'已完成，等待结果':'待完成')+(t.deadline?' · '+t.deadline+' · '+(t.precision==='estimated'?'估算':'原记录时间'):''),'meta')))):null,
    shortMeta(a.next_action,deadlineStamp(a),stamp(a,'interview_at','面试'))],
    link('来源',a.source_url,'btn small'),calendarLink(a),editApplicationButton(a)))));
  if(visible.length<rows.length){
    const more=btn('显示更多投递',()=>{
      applicationLimit+=applicationPageSize;
      renderApplications(target);
      (qs('#application-more',target)||target).focus({preventScroll:true});
    },'small');
    more.id='application-more';
    target.append(node('div','actions',more));
  }
}
function editApplicationButton(a){
  return btn('查看／修改',()=>{currentEdit=a.id;render();qs('#editor')?.scrollIntoView();qs('#app-company')?.focus({preventScroll:true});},'small');
}
function applicationBoard(applications,target){
  const groups=Object.entries(statusLabels).filter(([k])=>!statusFilter||statusFilter===k);
  const board=node('div','board',groups.map(([status,label])=>{
    const rows=applications.filter(a=>a.status===status);
    const title=node('h3','board-heading',badge(label,status),' ',String(rows.length));title.id='board-title-'+status;
    const run=node('section','board-column',title,rows.length?node('ol','board-items',rows.map(a=>{
      const changeStatus=field('board-'+a.id,'status','更新状态',{kind:'select',value:a.status,options:Object.entries(statusLabels)});
      const select=qs('select',changeStatus);
      select.setAttribute('aria-label',a.company+' '+a.title+'：更新状态');
      const update=btn('保存状态',async ()=>{
        const next=select.value;
        if(!Object.hasOwn(statusLabels,next)||next===a.status)return;
        const r=await request('/api/application',{id:a.id,status:next});
        const updated=r.application;
        const latest=await request('/api/state');
        state={...emptyState(),...latest};
        if(tab==='tracking'){
          // Keep unsaved edits in the full editor intact.
          if(equalId(currentEdit,a.id)){
            const statusSelect=qs('#app-status');
            if(statusSelect?.value===a.status)statusSelect.value=updated?.status||next;
            const reply=qs('#app-interview_reply_by');
            if(updated&&reply?.value===fieldDate(a.interview_reply_by))reply.value=fieldDate(updated.interview_reply_by);
            qs('#editor-calendar')?.replaceChildren(...calendarContents(updated||{...a,status:next}));
          }
          renderApplications(target);
          (qs('#board-'+a.id+'-status')||qs('#app-filter-status'))?.focus({preventScroll:true});
        }
        announce('已将「'+a.title+'」更新为'+statusName(next)+'。');
      },'small');
      update.disabled=true;
      select.addEventListener('change',()=>{update.disabled=select.value===a.status;});
      return node('li','board-item',node('strong','board-title',a.title),shortMeta(a.company,a.location,a.requisition,a.resume_label?'简历 '+a.resume_label:null),
        a.assessment_tasks?.length?details('各测评状态',list(a.assessment_tasks.map(t=>paragraph(t.id+'：'+(t.completed?'已完成，等待结果':'待完成')+(t.deadline?' · '+t.deadline+' · '+(t.precision==='estimated'?'估算':'原记录时间'):''),'meta')))):null,
    shortMeta(a.next_action,deadlineStamp(a),stamp(a,'interview_at','面试')),
        node('div','actions',editApplicationButton(a),calendarLink(a)),node('div','board-update',changeStatus,update));
    })):paragraph('暂无记录','board-empty'));
    run.setAttribute('aria-labelledby',title.id);return run;
  }));
  board.tabIndex=0;board.setAttribute('role','region');board.setAttribute('aria-label','按状态组织的投递看板');
  return board;
}
function historyDetails(application){
  const holder=node('div','',paragraph('展开后读取该岗位的时间线。','meta'));
  const box=details('查看时间线',holder);let loaded=false;
  box.addEventListener('toggle',async()=>{
    if(!box.open||loaded)return;
    loaded=true;holder.replaceChildren(paragraph('读取中…','meta'));
    try{
      const response=await request('/api/history?id='+encodeURIComponent(application.id));
      const events=Array.isArray(response)?response:response.events||response.history||[];
      holder.replaceChildren(events.length?list(events.map(e=>row([node('strong','',statusName(e.status)),' ',badge(e.applied===0||e.applied===false?'仅保留历史':'已记录'),shortMeta(e.received_at?'邮件 '+niceDate(e.received_at):null,e.created_at?'导入 '+niceDate(e.created_at):null),e.notes?paragraph(Array.isArray(e.notes)?e.notes.join('；'):e.notes,'meta'):null],link('来源',e.source_url,'btn small')))):empty('还没有已确认的导入通知。'));
    }catch(e){loaded=false;holder.replaceChildren(paragraph(e.message,'meta'));}
  });
  return box;
}
function readAsBase64(file, max){
  if(file.size>max)throw new Error('文件过大，请换用更小的文件。');
  return new Promise((resolve,reject)=>{
    const r=new FileReader();
    r.onload=()=>{const value=String(r.result);const at=value.indexOf(',');if(at<0)reject(new Error('读取文件失败。'));else resolve(value.slice(at+1));};
    r.onerror=()=>reject(new Error('无法读取文件。'));
    r.readAsDataURL(file);
  });
}
function noticeCard(app){
  const previewHolder=node('div');
  const noticeEntry=form(node('div','fields',
    field('notice','text','粘贴招聘通知',{kind:'textarea',full:true,placeholder:'建议包含主题、公司、岗位和时间；也可以直接选择 .eml 文件。',maxLength:60000}),
    field('notice','eml','或导入邮件文件',{kind:'file',accept:'.eml,message/rfc822',full:true}),
    field('notice','received_at','通知发送时间（香港）',{placeholder:'2026-11-19 10:30',full:true,hint:'用于时序核对和相对日期推算；.eml 默认读取 Date 发送时间，不是本次导入时间。收到后时限需另核对实际收件时间。'}),
    field('notice','source_url','邮件或岗位链接',{kind:'url',placeholder:'https://…',full:true}),
    field('notice','company','公司（可选）',{placeholder:app.company||'不确定可留空'}),
    field('notice','title','岗位名称（可选）',{placeholder:app.title||'不确定可留空'}),
    field('notice','requisition','岗位编号（可选）',{placeholder:app.requisition||'如有就填写',full:true})),
    async f=>{
      previewHolder.replaceChildren();
      const d=actualData(f);const file=f.elements.eml.files[0];
      if(!d.text&&!file)throw new Error('请先粘贴通知内容，或选一个 .eml 文件。');
      if(file)d.eml_base64=await readAsBase64(file,2_000_000);
      const preview=await request('/api/notice/preview',d);
      previewHolder.append(renderPreview(preview));
      previewHolder.querySelector('h3')?.focus({preventScroll:true});previewHolder.scrollIntoView({block:'nearest'});
    },'解析并预览');
  return card('导入招聘通知',paragraph('不会连接邮箱或发消息。解析结果可能不准，确认之后才写入台账。','meta'),noticeEntry,previewHolder);
}
function renderPreview({token,notice:n,match:m}){
  if(!n||!token)throw new Error('没有收到有效的预览结果。');
  const rows=state.applications||[];
  const options=n.assessment_completion?[['','请选择对应的已有投递']]:[['','请选择对应岗位或新建'],['__new','新建投递记录']];
  options.push(...rows.map(a=>[String(a.id),a.company+' / '+a.title+(a.requisition?' · '+a.requisition:'')]));
  const exact=rows.find(a=>equalId(a.id,m?.match_id));
  const selection=exact&&!m?.ambiguous?String(exact.id):'';
  const title=node('h3','','确认本次导入');title.tabIndex=-1;
  const warning=[...(Array.isArray(n.warnings)?n.warnings:[]),m?.ambiguous?(m.reason||'匹配不明确，必须由你复核。'):!selection?'没有自动关联，请核对要写入的岗位。':''].filter(Boolean);
  const oldVals={company:plain(n.company),title:plain(n.title),requisition:plain(n.requisition),status:n.has_explicit_status===false?'':plain(n.status),deadline:fieldDate(n.deadline),interview_at:fieldDate(n.interview_at),interview_reply_by:fieldDate(n.interview_reply_by),next_action:plain(n.next_action)};
  return node('section','details',title,
    paragraph(exact?'建议关联：'+exact.company+' / '+exact.title:'当前没有自动匹配。','meta'),
    shortMeta(({high:'提取置信度：高',medium:'提取置信度：中',low:'提取置信度：低'})[n.confidence],n.received_at?'通知发送时间 '+niceDate(n.received_at):''),
    n.timing_evidence?paragraph('发送：'+(n.timing_evidence.sent_at||'未知')+'；预约：'+(n.timing_evidence.event_at||'未识别')+'；实际投递：'+n.timing_evidence.applications.map(a=>'#'+a.id+' '+(a.submitted_at||'未知')).join(' / '),'meta'):null,
    warning.length?node('div','notice warn',warning.join('\n')):null,
    n.notes?paragraph(Array.isArray(n.notes)?n.notes.join('；'):n.notes,'meta'):null,
    Array.isArray(n.evidence)&&n.evidence.length?details('判断证据（仅文本，不打开邮件资源）',list(n.evidence.map(e=>row(paragraph(e.source+' / '+({company:'公司',title:'岗位',requisition:'编号',status:'状态'}[e.field]||e.field)+'：'+(e.field==='status'?(statusLabels[e.value]||e.value)+' · ':'')+e.quote))))):null,
    form(node('div','fields',
      field('review','target','写入哪个岗位',{kind:'select',value:selection,required:true,full:true,options}),
      field('review','company','提取到的公司',{value:oldVals.company}),
      field('review','title','提取到的岗位',{value:oldVals.title}),
      field('review','requisition','提取到的编号',{value:oldVals.requisition}),
      field('review','status','本次状态',{kind:'select',value:oldVals.status,options:[['','不变更'],...Object.entries(statusLabels)]}),
      field('review','deadline','申请或其他流程截止（香港）',{value:oldVals.deadline,hint:precisionLabel(n,'deadline')}),
      field('review','interview_at','本次面试时间（香港）',{value:oldVals.interview_at,hint:precisionLabel(n,'interview_at')}),
      field('review','interview_reply_by','本次面试回复期限（香港）',{value:oldVals.interview_reply_by,hint:precisionLabel(n,'interview_reply_by')}),
      field('review','next_action','本次下一步',{value:oldVals.next_action,full:true}),
      n.assessment_completion_confirmation_required?field('review','assessment_completion_confirmed','确认仅完成测评 '+(n.assessment_id||'（未知，不能清除待办）'),{kind:'checkbox',value:'yes',full:true}):null,
      n.assessment_confirmation_required?field('review','same_assessment_confirmed','已核实来源与发送时间，并确认本通知属于同一测评 '+(n.assessment_id||'（编号未知，不能自动改截止）'),{kind:'checkbox',value:'yes',full:true,hint:'仅推算截止；未知编号或原测评不一致时只能复核留历史。'}):null,
      n.requires_review?field('review','review_confirmed','我已核对正文冲突、身份与所选岗位',{kind:'checkbox',value:'yes',full:true,hint:'默认不变更状态；明确选择新状态后才更新。'}):null),
      f=>{
        const d=actualData(f);const create=d.target==='__new';
        if(!d.target)throw new Error('请指定要写入的投递记录。');
        if(create&&(!d.company||!d.title))throw new Error('新建记录至少需要公司和岗位名称。');
        if(!create&&exact&&!equalId(exact.id,d.target)){
          const chosen=rows.find(a=>equalId(a.id,d.target));
          if(!window.confirm('通知建议关联「'+exact.title+'」，你选了「'+chosen?.title+'」。确认写入所选记录？'))return;
        }
        const overrides={};
        if(n.assessment_completion_confirmation_required&&f.elements.assessment_completion_confirmed?.checked)overrides.assessment_completion_confirmed=true;
        if(n.assessment_confirmation_required&&f.elements.same_assessment_confirmed?.checked)overrides.same_assessment_confirmed=true;
        if(!create&&exact&&!equalId(exact.id,d.target))overrides.review_confirmed=true;
        if(n.requires_review){
          if(!f.elements.review_confirmed?.checked)throw new Error('请先勾选已复核邮件证据与岗位。');
          overrides.review_confirmed=true;
        }
        for(const key of Object.keys(oldVals)){
          if(d[key]!==oldVals[key])overrides[key]=key==='status'&&!d[key]?(rows.find(a=>equalId(a.id,d.target))?.status||'waiting'):d[key];
        }
        if(create){overrides.company=d.company;overrides.title=d.title;overrides.requisition=d.requisition;}
        return mutate('/api/notice/apply',{token,application_id:create?undefined:d.target,create,overrides},r=>r.duplicate?'该通知已导入过，没有重复写入。':((r.applied===false?'通知已留存，未覆盖当前状态。':'通知已存入台账。')+(Array.isArray(r.warnings)&&r.warnings.length?'\n'+r.warnings.join('\n'):'')),r=>{currentEdit=r.application?.id||r.application_id||(create?null:d.target);});
      },'确认写入'));
}
const profileSections=[
  ['基本信息', [
    ['full_name','姓名'],['preferred_name','常用名'],['email','邮箱','email'],['phone','手机号码','tel'],['city','现居城市'],
  ], [['gender','性别'],['political_status','政治面貌'],['student_origin','生源地'],['candidate_status','应届身份']]],
  ['求职意向', [['available_from','可到岗时间']], [
    ['target_position','目标岗位'],['target_industry','期望行业'],['target_city','期望工作城市'],['transfer_preference','是否接受调剂'],
  ]],
  ['最高学历', [['school','学校'],['degree','学历'],['major','专业'],['graduation','预计毕业时间']], []],
];
const profileExtraSections=[
  ['技能与自我评价', [['project_summary','项目简介（填表用）','textarea']], [['skills','技能专长','textarea'],['self_evaluation','自我评价','textarea']]],
  ['简历版本与链接', [
    ['resume_zh','中文简历版本／本地路径'],['resume_en','英文简历版本／本地路径'],
    ['linkedin','LinkedIn','url'],['github','GitHub','url'],['portfolio','作品集','url'],
  ], []],
];
const FILLABLE_PROFILE_RECORDS={
  education:['school','department','major','degree','start','end','grade','description'],
  internships:['company','department','role','start','end','description'],
  work_experience:['company','department','role','start','end','description'],
  projects:['name','role','start','end','description'],
  campus_experience:['organization','role','start','end','description'],
  awards:['name','issuer','date','level'],
  certificates:['name','issuer','date','level'],
  languages:['language','qualification','score','date'],
};
function setProfileInputValue(input,value){
  value=value??'';
  if(input.tagName.toLowerCase()==='select'&&!Array.from(input.children).some(option=>option.value===value)){
    const option=node('option','',value);option.value=value;input.append(option);
  }
  input.value=value;
}
const narrowFullWidthKeys=new Set([
  'diploma_number','degree_certificate_number','patent_number','doi','id_card','project_link',
  'address','household_address','resume_zh','resume_en','phone','emergency_phone','reference_contact','counselor_contact',
]);
function profileInputs(fields, values, prefix=''){
  const group=prefix.split('-')[0];
  const history=state.profile?.resume_details?.[group]||[];
  return fields.map(([key,label,kind])=>{
    const scoped=group+'.'+key;
    const choices=resumeSchema.choices?.[scoped]||resumeSchema.choices?.[key];
    if(choices){
      const options=[['','请选择'],...choices.map(value=>[value,value])];
      const wrapper=field('profile',prefix+key,label,{kind:'select',options});
      setProfileInputValue(wrapper.querySelector('select'),values[key]);
      return wrapper;
    }
    const wrapper=field('profile',prefix+key,label,{
      kind,value:values[key],full:kind==='textarea',maxLength:kind==='textarea'?2800:400,step:kind==='number'?'any':undefined,
    });
    if(['email','url','tel'].includes(kind) || narrowFullWidthKeys.has(key))wrapper.className+=' narrow-full';
    if(kind&&kind!=='text')return wrapper;
    const standard=resumeSchema.suggestions?.find(([keys])=>keys.includes(scoped)||keys.includes(key))?.[1]||[];
    const previous=FILLABLE_PROFILE_RECORDS[group]?.includes(key)?history.map(record=>record[key]).filter(Boolean):[];
    const suggestions=new Set([...standard,...previous]);
    if(suggestions.size){
      const input=wrapper.querySelector('input'),list=node('datalist');
      list.id=input.id+'-choices';input.setAttribute('list',list.id);
      for(const value of suggestions){const option=node('option');option.value=value;list.append(option);}
      wrapper.append(list);
    }
    return wrapper;
  });
}
function profileRecordSection([key,title,item,fields,extra],saved,onEdit){
  const list=node('div','profile-records');
  const allFields=[...fields,...extra];
  const rows=new Set();
  let nextIndex=0;
  function numberRows(){
    Array.from(list.children).forEach((row,i)=>{row.querySelector('legend').textContent=item+' · 第 '+(i+1)+' 条';});
  }
  function append(record){
    const prefix=key+'-'+nextIndex+++'-';
    rows.add(prefix);
    const remove=btn('移除此条'+item,()=>{rows.delete(prefix);row.remove();numberRows();onEdit();add.focus();},'small');
    const more=extra.length?details('更多'+item+'字段',node('div','fields',profileInputs(extra,record,prefix))):null;
    const row=node('fieldset','profile-record',node('legend','',item),
      node('div','fields',profileInputs(fields,record,prefix)),more,remove);
    list.append(row);
    numberRows();
    return row;
  }
  const add=btn('添加'+item,()=>{
    if(rows.size>=20)throw new Error(title+'最多保存 20 条。');
    const row=append({});onEdit();row.querySelector('input, select, textarea')?.focus();
  },'small');
  if(Array.isArray(saved))saved.forEach(append);
  return {
    key, append,
    view:node('section','profile-section',node('div','section-actions',node('h3','',title),add),list),
    read:data=>Array.from(rows,prefix=>Object.fromEntries(allFields.map(([name])=>[name,data[prefix+name]||'']))),
  };
}
function downloadProfile(saved){
  const {resume_zh, resume_en, resume_details, ...shareable}=saved;
  const records={};
  for(const key of ['gender','political_status']){
    if(resume_details?.[key])records[key]=resume_details[key];
  }
  for(const [group,keys] of Object.entries(FILLABLE_PROFILE_RECORDS)){
    const rows=resume_details?.[group];
    if(!Array.isArray(rows))continue;
    const allowed=rows.map(row=>Object.fromEntries(keys.filter(key=>Object.hasOwn(row,key)).map(key=>[key,row[key]])));
    if(allowed.some(row=>Object.keys(row).length))records[group]=allowed;
  }
  if(Object.keys(records).length)shareable.resume_details=records;
  const wrapper={profile:shareable};
  const file=new Blob([JSON.stringify(wrapper,null,2)],{type:'application/json'});
  const url=URL.createObjectURL(file);
  const a=node('a');a.href=url;a.download='job-workbench-profile.json';
  document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),5000);
  announce('资料 JSON 已导出。请保存在只有你能访问的位置。');
}
function resumeImportCard(profileForm, sections, groups, onApply){
  const output=node('div','import-preview');
  output.setAttribute('aria-live','polite');
  const fileField=field('resume-import','file','选择简历文件',{kind:'file',accept:'.pdf,.docx,.txt',required:true});
  const picker=qs('input',fileField);
  picker.addEventListener('change',()=>output.replaceChildren());
  const upload=form(fileField,async ()=>{
    const file=picker.files[0];
    if(!file)throw new Error('请选择简历文件。');
    output.replaceChildren(paragraph('正在本机解析…','meta'));
    let preview;
    try{
      preview=await request('/api/profile/import-preview',{filename:file.name,content_base64:await readAsBase64(file,5*1024*1024)});
    }catch(error){output.replaceChildren();throw error;}
    if(picker.files[0]!==file)return;
    const choices=[], blocks=[];
    const option=(title,body,conflict,apply)=>{
      const check=node('input');check.type='checkbox';check.checked=!conflict;check.disabled=!!conflict;
      choices.push({check,apply});
      return node('label','import-option',check,node('span','',node('strong','',title),body,conflict?node('small','',conflict):null));
    };
    for(const [title,base,extra] of sections){
      const items=[];
      for(const [key,label] of [...base,...extra]){
        const value=Object.hasOwn(preview.fields,key)?preview.fields[key]:preview.details[key];
        if(!value)continue;
        const control=profileForm.elements[key];
        items.push(option(label,node('span','import-value',value),control.value.trim()?'已有值，保留原内容':'',()=>{
          if(control.value.trim())return false;
          setProfileInputValue(control,value);
          return control.value===value;
        }));
      }
      if(items.length)blocks.push(node('fieldset','import-group',node('legend','',title),items));
    }
    for(const [key,title,item,primary,extra] of resumeSchema.records){
      const rows=preview.records[key]||[];
      if(!rows.length)continue;
      const group=groups.find(entry=>entry.key===key);
      const current=()=>group.read(actualData(profileForm));
      const seen=(record,existing)=>existing.some(row=>Object.entries(record).every(([name,value])=>row[name]===value));
      const entries=rows.map((record,index)=>{
        const values=[...primary,...extra].filter(([name])=>record[name]).map(([name,label])=>
          node('span','import-record-field',node('small','',label),record[name]));
        const existing=current();
        const reason=seen(record,existing)?'已有相同记录':existing.length>=20?'此类记录已满':'';
        return option(item+' · 第 '+(index+1)+' 条',node('span','import-record-values',values),reason,()=>{
          const latest=current();
          if(latest.length>=20||seen(record,latest))return false;
          group.append(record);
          return true;
        });
      });
      blocks.push(node('fieldset','import-group',node('legend','',title+'（追加记录）'),entries));
    }
    const apply=btn('将所选内容加入资料草稿',()=>{
      const selected=choices.filter(({check})=>check.checked&&!check.disabled);
      if(!selected.length)throw new Error('请先勾选要加入草稿的内容。');
      const count=selected.filter(entry=>entry.apply()).length;
      onApply();
      const skipped=selected.length-count;
      picker.value='';
      output.replaceChildren(paragraph('已加入 '+count+' 项'+(skipped?'，跳过 '+skipped+' 项已有值、重复或超限的记录':'')+'。请在下方核对，再点击「保存资料」。','notice success'));
    },'primary');
    output.replaceChildren(node('h3','','解析预览'),paragraph(file.name+' · 只勾选要加入草稿的字段或整条经历。','meta'),
      ...preview.warnings.map(warning=>paragraph(warning,'notice warn')),...blocks,
      ...(choices.length?[node('div','actions',choices.some(({check})=>!check.disabled)?apply:null,
        btn('放弃预览',()=>{picker.value='';output.replaceChildren();}))]:[paragraph('未提取到可导入的字段，可在下方手动编辑。','meta')]));
  },'解析并预览');
  upload.className='resume-upload';
  const glyph=node('span','resume-file-icon');glyph.setAttribute('aria-hidden','true');
  return node('section','resume-import-strip',glyph,node('div','resume-import-copy',node('h2','','导入简历'),
    paragraph('Word、文字版 PDF 或 UTF-8 TXT · 最大 5 MiB','meta')),upload,output);
}

let profileSectionKey='basic';
function profileNavigator(panels){
  const nav=node('nav','profile-nav');
  nav.setAttribute('aria-label','资料内容导航');
  const compact=node('select','profile-jump');compact.setAttribute('aria-label','跳转到资料栏目');
  const rows=new Map();
  const filledText=node('p','progress-total'),percentText=node('span'),remainingText=node('span','progress-remaining');
  const meter=node('progress','profile-meter');meter.setAttribute('aria-label','资料完成度');
  const missingView=node('section','profile-missing');
  missingView.hidden=true;missingView.tabIndex=-1;missingView.id='profile-missing-items';
  const previousOffset=qs('#resume-scroll')?.scrollTop;
  const viewport=node('div','profile-scroll',missingView,panels.map(panel=>panel.view));
  viewport.id='resume-scroll';viewport.tabIndex=0;
  viewport.setAttribute('role','region');viewport.setAttribute('aria-label','简历资料编辑区');
  let lastField=null,missingOffset=0;
  const toggle=btn('查看空白字段',()=>{
    if(!missingView.hidden){jump(profileSectionKey);return;}
    missingView.hidden=false;
    toggle.setAttribute('aria-expanded','true');toggle.textContent='返回编辑';
    renderMissing();
    const maxOffset=Math.max(0,missingView.offsetHeight-viewport.clientHeight);
    scrollToTarget(missingView,missingView,Math.min(missingOffset,maxOffset));
  },'progress-toggle');
  toggle.setAttribute('aria-controls',missingView.id);toggle.setAttribute('aria-expanded','false');
  const controls=panel=>Array.from(panel.view.querySelectorAll('input[name],select[name],textarea[name]'));
  const isEmpty=control=>!control.value.trim();
  const nextMissing=btn('下一缺项',()=>{
    const section=panels.findIndex(panel=>panel.key===profileSectionKey);
    const ordered=panels.slice(section).concat(panels.slice(0,section));
    const fields=ordered.flatMap(panel=>controls(panel).map(control=>({key:panel.key,control})));
    const start=fields.findIndex(field=>field.control===lastField)+1;
    const next=fields.slice(start).concat(fields.slice(0,start)).find(field=>isEmpty(field.control));
    if(next)jump(next.key,next.control);
  },'next-missing');
  function renderMissing(){
    const openGroups=new Map(Array.from(missingView.querySelectorAll('details'),group=>[group.dataset.key,group.open]));
    const sections=[];
    for(const panel of panels){
      const missing=controls(panel).filter(isEmpty);
      if(!missing.length)continue;
      const items=missing.map(control=>{
        const ordinal=control.closest('fieldset')?.querySelector('legend')?.textContent;
        const label=control.labels[0].textContent;
        return btn(ordinal?ordinal+' · '+label:label,()=>jump(panel.key,control),'missing-link');
      });
      const group=details(panel.title+' · '+missing.length+' 项',node('div','missing-fields',items));
      group.dataset.key=panel.key;
      group.open=openGroups.get(panel.key)??(panel.key===profileSectionKey);
      sections.push(group);
    }
    if(!openGroups.size && sections.length && !sections.some(section=>section.open))sections[0].open=true;
    missingView.replaceChildren(node('div','section-actions',node('h2','','资料库空白字段'),
      btn('返回当前栏目',()=>jump(profileSectionKey),'small')),
      paragraph(sections.length?'点击字段名即可编辑。尚未添加的经历不计入空白数。':'当前资料中的字段已全部填写。','meta'),...sections);
  }
  function refresh(key){
    let filled=0,total=0;
    for(const panel of panels){
      const row=rows.get(panel.key);
      if(!key || key===panel.key){
        const fields=controls(panel);
        row.total=fields.length;
        row.filled=fields.filter(control=>!isEmpty(control)).length;
        const remaining=row.total-row.filled;
        const complete=row.total>0 && !remaining;
        row.button.dataset.progress=complete?'complete':row.total?'partial':'empty';
        row.count.textContent=row.filled+'/'+row.total;
        row.note.textContent=row.total?(complete?'已全部填写':'空白 '+remaining+' 项'):'尚未新增内容';
        row.line.hidden=complete;
        row.bar.hidden=!remaining;
        row.bar.max=row.total||1;row.bar.value=row.filled;
        row.mark.textContent=complete?'✓':'';
        row.option.textContent=panel.title+'　'+row.count.textContent;
      }
      filled+=row.filled;total+=row.total;
    }
    filledText.textContent='已填写 '+filled+' / '+total+' 个字段';
    const percent=total?Math.round(filled/total*100):0;
    percentText.textContent='完成度 '+(filled<total?Math.min(99,percent):percent)+'%';
    remainingText.textContent='空白 '+(total-filled)+' 项';
    nextMissing.disabled=filled===total;
    meter.max=total||1;meter.value=filled;
    meter.dataset.complete=String(total>0 && filled===total);
    if(!missingView.hidden)renderMissing();
  }
  function markCurrent(key){
    profileSectionKey=key;
    for(const [name,{button}] of rows){
      if(name===key)button.setAttribute('aria-current','location');else button.removeAttribute('aria-current');
    }
    compact.value=key;
    const button=rows.get(key).button;
    if(nav.clientHeight){
      const bounds=nav.getBoundingClientRect(),item=button.getBoundingClientRect();
      if(item.top<bounds.top)nav.scrollTop+=item.top-bounds.top;
      else if(item.bottom>bounds.bottom)nav.scrollTop+=item.bottom-bounds.bottom;
    }
  }
  function offsetOf(target){
    return viewport.scrollTop+target.getBoundingClientRect().top-viewport.getBoundingClientRect().top-8;
  }
  function scrollToTarget(target,anchor=target,top){
    target.focus({preventScroll:true});
    const bounds=viewport.getBoundingClientRect();
    if(bounds.top<0 || bounds.top>window.innerHeight*0.6)viewport.scrollIntoView({block:'start',behavior:'instant'});
    viewport.scrollTo({top:top??offsetOf(anchor)});
  }
  function jump(key,control){
    if(!missingView.hidden)missingOffset=viewport.scrollTop;
    lastField=control||null;
    missingView.hidden=true;toggle.setAttribute('aria-expanded','false');toggle.textContent='查看空白字段';
    const target=control||rows.get(key).view;
    const more=control?.closest('details');if(more)more.open=true;
    markCurrent(key);
    scrollToTarget(target,control?.closest('.field')||target);
  }
  function syncWithScroll(){
    if(!missingView.hidden && missingView.getBoundingClientRect().bottom>viewport.getBoundingClientRect().top+12)return;
    const edge=viewport.getBoundingClientRect().top+12;
    const active=panels.findLast(panel=>panel.view.getBoundingClientRect().top<=edge)||panels[0];
    if(active.key!==profileSectionKey)markCurrent(active.key);
  }
  for(const panel of panels){
    const count=node('span','progress-count'),mark=node('span','progress-mark');
    mark.setAttribute('aria-hidden','true');
    const bar=node('progress','profile-meter');bar.setAttribute('aria-hidden','true');
    const note=node('span'),line=node('span','progress-row-detail',note,bar);
    const button=btn('',()=>jump(panel.key),'profile-nav-item');
    button.append(node('span','progress-row-head',node('span','progress-title',panel.title),count,mark),line);
    button.setAttribute('aria-label',panel.title);
    count.id='profile-coverage-'+panel.key;button.setAttribute('aria-describedby',count.id);
    const targetId='resume-section-'+panel.key;
    panel.view.id=targetId;panel.view.tabIndex=-1;
    button.setAttribute('aria-controls',targetId);
    const option=node('option','',panel.title);option.value=panel.key;compact.append(option);
    rows.set(panel.key,{button,count,mark,bar,note,line,option,view:panel.view});
    nav.append(button);
    panel.view.addEventListener('focusin',e=>{if(e.target.name)lastField=e.target;});
    for(const event of ['input','change'])panel.view.addEventListener(event,()=>refresh(panel.key));
    panel.view.addEventListener('invalid',e=>{
      if(e.target.form.querySelector(':invalid')!==e.target)return;
      jump(panel.key,e.target);
    },true);
  }
  compact.addEventListener('change',()=>jump(compact.value));
  viewport.addEventListener('scroll',syncWithScroll,{passive:true});
  markCurrent(rows.has(profileSectionKey)?profileSectionKey:panels[0].key);
  queueMicrotask(()=>{
    if(!viewport.isConnected)return;
    viewport.scrollTo({top:previousOffset??offsetOf(rows.get(profileSectionKey).view),behavior:'instant'});
    syncWithScroll();
  });
  refresh();
  const summary=node('div','profile-progress-summary',node('h2','','内容导航'),filledText,
    node('div','progress-overview',percentText,remainingText),meter,
    paragraph('资料库可按需填写。网申必填项以招聘方表单为准。','progress-hint'),toggle);
  return {view:node('aside','profile-contents',summary,compact,nav),viewport,refresh,nextMissing};
}
function profile(){
  if(!resumeSchema)return [card('资料与填表',paragraph('正在读取资料字段…'))];
  const p=state.profile||{};
  const resume=p.resume_details||{};
  const additional=resumeSchema.sections.map(([title,fields])=>[title,[],fields.filter(([key])=>key!=='gender')]);
  const sections=[...profileSections,...profileExtraSections,...additional];
  const groups=resumeSchema.records.map(definition=>profileRecordSection(definition,resume[definition[0]],()=>{
    navigation.refresh(definition[0]);updateExportLabel();
  }));
  const section=([title,baseFields,resumeFields])=>node('section','profile-section',node('h3','',title),
    node('div','fields',profileInputs(baseFields,p),profileInputs(resumeFields,resume)));
  const answerObject=p.answers&&typeof p.answers==='object'&&!Array.isArray(p.answers)?p.answers:{};
  const answerText=Object.entries(answerObject).map(([q,a])=>q+' = '+a).join('\n');
  const answerField=field('profile','answers','问题与答案',{kind:'textarea',full:true,value:answerText,
    placeholder:'为什么申请这个岗位？ = 我对…',hint:'每行一组，使用「问题 = 答案」。',maxLength:8000});
  const scalarPanel=(key,definition)=>({key,title:definition[0],view:section(definition)});
  const panels=[
    ...profileSections.map((definition,i)=>scalarPanel(['basic','intent','degree'][i],definition)),
    ...groups.map((group,i)=>({key:group.key,title:resumeSchema.records[i][1],view:group.view})),
    ...additional.map(definition=>scalarPanel(definition[2][0][0],definition)),
    ...profileExtraSections.map(definition=>scalarPanel(definition[1][0][0],definition)),
    {key:'answers',title:'常见问题',view:node('section','profile-section',node('h3','','常见问题'),answerField)},
  ];
  const navigation=profileNavigator(panels);
  let revision=state.profile_revision, saving=false;
  const conflict=node('div','notice warn',
    paragraph('另一页已保存资料。本页草稿仍在。打开最新版，对照两页，把需要保留的改动填到新页，再在那里保存。'),
    link('在新标签页打开最新资料','/#profile','btn'));
  conflict.hidden=true;conflict.tabIndex=-1;
  async function saveProfile(exportAfter=false){
    if(!conflict.hidden){conflict.focus();return;}
    if(saving)return;
    if(!profileForm.reportValidity())return;
    const d=actualData(profileForm);const answers=Object.create(null);
    for(const l of d.answers.split('\n').map(x=>x.trim()).filter(Boolean)){
      const i=l.indexOf('=');if(i<1||!l.slice(i+1).trim())throw new Error('常见问题格式不正确。请使用「问题 = 答案」，一行一项。');
      const k=l.slice(0,i).trim();if(!k)throw new Error('常见问题不能为空。');
      answers[k]=l.slice(i+1).trim();
    }
    const base=Object.fromEntries(sections.flatMap(([,fields])=>fields.map(([key])=>[key,d[key]])));
    const resumeDetails=Object.fromEntries(sections.flatMap(([, ,fields])=>fields.map(([key])=>[key,d[key]])));
    for(const group of groups)resumeDetails[group.key]=group.read(d);
    saving=true;
    try{
      const saved=await request('/api/profile',{...base,answers,resume_fields_version:1,resume_details:resumeDetails,profile_revision:revision});
      revision=saved.profile_revision;
      baseline=JSON.stringify(d);
      if(state.profile_revision<=revision){
        state.profile=saved.profile;state.profile_revision=revision;
      }
      if(profileHasChanges!==hasChanges)return;
      if(hasChanges()){
        updateExportLabel();
        announce('已保存提交时的资料。刚输入的改动仍在草稿中，请再次保存。');return;
      }
      render();
      if(exportAfter)downloadProfile(saved.profile);
      else announce('资料已保存到本地。');
    }catch(error){
      if(error.status!==409)throw error;
      conflict.hidden=false;conflict.focus();
      announce(error.message,true);
    }finally{saving=false;}
  }
  const profileForm=form(navigation.viewport,()=>saveProfile(),'保存资料',navigation.nextMissing);
  profileForm.className='profile-form';
  let baseline=JSON.stringify(actualData(profileForm));
  const hasChanges=()=>JSON.stringify(actualData(profileForm))!==baseline;
  profileHasChanges=hasChanges;
  const exportButton=btn('导出填表资料 JSON',async ()=>{
    if(!conflict.hidden){conflict.focus();return;}
    if(hasChanges()){
      if(exportButton.textContent==='导出填表资料 JSON'&&!window.confirm('资料有未保存的改动。保存并导出当前资料？'))return;
      return saveProfile(true);
    }
    const latest=await request('/api/state');
    if(profileHasChanges!==hasChanges)return;
    if(hasChanges()){updateExportLabel();announce('资料有新改动，请点击「保存并导出填表资料 JSON」。');return;}
    if(latest.profile_revision!==revision){
      state.profile=latest.profile;state.profile_revision=latest.profile_revision;
      render();announce('资料已在另一页更新。已显示最新内容，请核对后再次点击导出。');return;
    }
    downloadProfile(latest.profile);
  });
  function updateExportLabel(){exportButton.textContent=hasChanges()?'保存并导出填表资料 JSON':'导出填表资料 JSON';}
  profileForm.addEventListener('input',updateExportLabel);
  profileForm.addEventListener('change',updateExportLabel);
  const header=node('header','resume-page-heading',node('div','',node('h1','','我的简历'),paragraph('在本机整理网申资料，按栏目编辑与保存。','meta')),
    node('div','actions',link('预览下拉选项','/demo-form.html?preview=select','btn'),exportButton));
  return [header,conflict,
    resumeImportCard(profileForm,sections,groups,()=>{navigation.refresh();updateExportLabel();}),
    node('div','profile-editor',navigation.view,node('section','card resume-sheet',profileForm)),
    node('div','grid equal',
      card('分条填表预览',paragraph('导出的资料可在浏览器扩展中逐条预览。证件、家庭和证明人资料留在本机。','meta'),
        link('查看分组卡片','/demo-form.html?preview=1','btn')),
      node('div','stack',
        card('Chrome / Edge 辅助填表',node('ol','',
          node('li','','打开扩展程序管理页，启用开发者模式。'),
          node('li','','选择「加载解压缩的扩展程序」，选中软件包里的 extension 文件夹。'),
          node('li','','在想填写的页面，打开扩展图标，导入上方导出的 JSON。'),
          node('li','','扫描整张表单或先点击要识别的输入框，再核对预览后填入。附件、资格承诺和提交仍由你操作。')),
          link('打开本地练习表单','/demo-form.html','btn'),paragraph('练习使用模拟资料，不会提交到招聘平台。','meta')),
        ocrCard()))];
}
function ocrCard(){
  const output=field('ocr-result','text','识别结果（可编辑）',{kind:'textarea',full:true,maxLength:24000});
  const dest=qs('textarea',output);
  return card('图片文字识别（可选）',paragraph('仅在电脑安装本地 Tesseract 后使用，不把图片发给第三方。可以复制识别出的字段标签，按扩展里的文字提示手动校对。','meta'),
    form(node('div','fields',field('ocr','image','表单截图',{kind:'file',accept:'image/png,image/jpeg',full:true,required:true}),
      field('ocr','language','识别语言',{kind:'select',full:true,value:'chi_sim+eng',options:[['chi_sim+eng','简体中文＋英文（需语言包）'],['eng','英文'],['chi_tra+eng','繁体中文＋英文（需语言包）']]})),async f=>{
      const file=f.elements.image.files[0];if(!file)throw new Error('请选择一张截图。');
      const r=await request('/api/ocr',{image_base64:await readAsBase64(file,3_000_000),language:f.elements.language.value});
      dest.value=r.text||'';dest.focus();
    },'识别文字'),output);
}
for(const b of document.querySelectorAll('[data-tab]'))b.addEventListener('click',()=>setTab(b.dataset.tab));
window.addEventListener('hashchange',()=>{
  if(tab==='profile'&&location.hash.startsWith('#discovery?capture=')&&!allowProfileExit())return;
  if(captureFromHash()){render();bringCaptureIntoView();return;}
  const next=location.hash.slice(1);if(pages.includes(next)&&next!==tab)setTab(next);
});
window.addEventListener('beforeunload',event=>{
  if(profileHasChanges?.()){event.preventDefault();event.returnValue='';}
});
const startupCapture=captureFromHash();
updateClock();setInterval(updateClock,60_000);setInterval(pollDashboard,25_000);
if(!startupCapture&&pages.includes(location.hash.slice(1)))tab=location.hash.slice(1);
refresh().then(()=>{if(startupCapture)bringCaptureIntoView();}).catch(e=>{announce(e.message,true);content.removeAttribute('aria-busy');content.replaceChildren(btn('重新连接',refresh,'primary'));});
