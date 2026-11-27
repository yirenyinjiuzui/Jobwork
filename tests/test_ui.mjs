import { mockedDOM } from './mock_dom.mjs';
import { inspectPage } from '../extension/page.mjs';
import { loadProfile, makePlan } from '../extension/matcher.mjs';
// Lightweight JavaScript UI + real Python HTTP integration test; no browser dependency.
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import vm from 'node:vm';
import {inspectJobPage,makeCaptureLink} from '../extension/capture.mjs';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';

const project = fileURLToPath(new URL('../', import.meta.url));
const temp = fs.mkdtempSync(join(tmpdir(), 'job-workbench-ui-'));
const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const server = spawn(python, ['-u', 'server.py', '--data', join(temp, 'test.sqlite3'),
  '--port', '0', '--interval', '0', '--no-browser'], {cwd:project, stdio:['ignore','pipe','pipe']});
let stderr = '';
server.stderr.on('data', chunk => stderr += chunk.toString());
const exited = once(server, 'exit').catch(() => []);
class Element {
  constructor(tag){this.tagName=tag;this.children=[];this.handlers={};this.attrs={};this.dataset={};this.classList={toggle:()=>{}};this.nodeType=1;this.disabled=false;this.value='';this.files=[];}
  append(...children){this.children.push(...children);}
  replaceChildren(...nodes){this.children=nodes;}
  set textContent(v){this.children=[{nodeType:3,textContent:String(v)}];}
  get textContent(){return this.children.map(c=>c.textContent??'').join('');}
  setAttribute(k,v){this.attrs[k]=v;}
  removeAttribute(k){delete this.attrs[k];}
  addEventListener(k,f){this.handlers[k]=f;}
  focus(){}
  reportValidity(){return true;}
  click(){}
  remove(){}
  scrollIntoView(){}
  scrollTo({top}){this.scrollTop=Math.max(0,top);}
  getBoundingClientRect(){return {top:0,bottom:0};}
  get elements(){return Object.fromEntries(nodes(this).filter(c=>c.name).map(c=>[c.name,c]));}
  querySelector(s){return nodes(this).find(x=>matches(x,s));}
  querySelectorAll(s){return nodes(this).filter(el=>s.split(',').some(selector=>
    selector.endsWith('[name]') ? el.tagName===selector.slice(0,-6)&&el.name : matches(el,selector)));}
}
function nodes(e){return [e,...(e.children??[]).flatMap(nodes)];}
function matches(x,s){if(s.startsWith('#'))return x.id===s.slice(1);if(s==='[type=submit]')return x.type==='submit';if(s==='[data-tab]')return !!x.dataset?.tab;return x.tagName===s;}
let host;
const downloads=[];
class BrowserURL extends URL{
  static createObjectURL(file){downloads.push(file);return 'blob:fixture-profile';}
  static revokeObjectURL(){}
}
const root=new Element('body'), nav=['dashboard','discovery','tracking','profile'].map(id=>{const x=new Element('button');x.dataset.tab=id;return x;});
root.append(...nav);
for(const id of ['content','main','errors','status','clock']){const el=new Element('div');el.id=id;root.append(el);}
const document={createElement:tag=>new Element(tag),createTextNode:s=>({nodeType:3,textContent:String(s)}),querySelector:s=>root.querySelector(s),querySelectorAll:s=>nodes(root).filter(x=>matches(x,s)),body:root,hidden:false};
function init(){
const location={origin:host,hash:''};
const window={handlers:{},history:{state:null,replaceState(s,t,hash){this.state=s;location.hash=hash;}},
  addEventListener(event,fn){this.handlers[event]=fn;},scrollTo(){},confirm(){return true;}};
const context={document,location,window, URL:BrowserURL,URLSearchParams,Blob,Date,Intl,FileReader:class{readAsDataURL(file){this.result='data:message/rfc822;base64,'+Buffer.from(file.content).toString('base64');this.onload();}},fetch:(p,i)=>fetch(host+p,i),setInterval(){},setTimeout,queueMicrotask,FormData:class{constructor(f){return Object.entries(f.elements).filter(([,e])=>e.type!=='file').map(([k,e])=>[k,e.value]);}}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(join(project,'web','app.js'),'utf8'),context);
return expr=>vm.runInContext(expr,context);
}
let run;
const click=async(label)=>{const b=nodes(root).find(e=>e.tagName==='button'&&(e.attrs['aria-label']||e.textContent)===label);assert(b,'button '+label);await b.handlers.click();};
const byid=id=>{const e=document.querySelector('#'+id);assert(e,'field '+id);return e;};
const text=()=>byid('content').textContent;
const submit=async(field)=>{const e=byid(field);const form=nodes(root).find(x=>x.tagName==='form'&&nodes(x).includes(e));assert(form,'form for '+field);form.handlers.submit({preventDefault(){}});for(let i=0;i<100;i++){if(!run('pendingActions'))return;await new Promise(r=>setTimeout(r,15));}throw Error('form timeout');};
async function main(){
  await run('refresh()');assert(text().includes('今天先做什么'));
  await click('载入演示记录');assert(text().includes('预留 60 分钟完成网测'));
  run("setTab('discovery')");assert(text().includes('目标公司'));
  assert(byid('source-provider').children.some(x=>x.value==='smartrecruiters'));
  await click('检查全部招聘源');assert(byid('status').textContent.includes('个来源已建立基线'),byid('status').textContent);
  await click('检查全部招聘源');assert(byid('status').textContent.includes('发现 1 个新开'),byid('status').textContent);
  run("jobRoute='hk'; render()");assert(text().includes('存到投递台账'));
  await click('存到投递台账');
  run(`location.hash='#discovery?capture='+encodeURIComponent(JSON.stringify({
    company:'捕获测试公司', title:'公开职位示例', requisition:'CAPTURE-123', location:'香港', career_type:'intern',
    url:'https://example.com/jobs?gh_jid=123&session=private#fragment', deadline:'2026-12-01',
    eligibility:'硕士在读', start:'每周三天', ignoredField:'ignored'
  })); window.handlers.hashchange()`);
  assert.equal(run('location.hash'),'#discovery');
  assert.equal(byid('manual-job').open,true);
  assert.equal(byid('job-company').value,'捕获测试公司');
  assert.equal(byid('job-url').value,'https://example.com/jobs?gh_jid=123');
  assert(!(await run("request('/api/state')")).jobs.some(j=>j.requisition==='CAPTURE-123'),'capture must not persist without submit');
  await submit('job-company');
  assert((await run("request('/api/state')")).jobs.some(j=>j.requisition==='CAPTURE-123'),'accepted capture must persist');
  assert.equal(byid('manual-job').open,false);
  run("location.hash='#discovery?capture=%7Bbroken'; window.handlers.hashchange()");
  assert.equal(run('location.hash'),'#discovery');
  assert.equal(byid('manual-job').open,false);
  assert(byid('errors').textContent.includes('草稿无法读取'));
  run("setTab('tracking')");assert(text().includes('全部投递'));
  byid('app-company').value='测试公司';byid('app-title').value='自动化实习';byid('app-requisition').value='JR-2234';byid('app-status').value='submitted';byid('app-resume_label').value='英文简历 v4';
  await submit('app-company');assert(byid('status').textContent.includes('投递记录已保存'),byid('errors').textContent);
  byid('notice-company').value='测试公司';byid('notice-title').value='自动化实习';byid('notice-requisition').value='JR-2234';
  byid('notice-text').value='You have been invited to attend an interview on 2026-12-15 at 14:00 (HKT).';byid('notice-received_at').value='2026-11-20 10:00';
  await submit('notice-text');assert(text().includes('确认本次导入'),byid('errors').textContent);
  assert.equal(byid('review-status').value,'interview');
  assert(byid('review-target').value&&!byid('review-target').value.startsWith('__'));
  const current=run('state.applications.find(a => a.requisition === "JR-2234")');
  assert.equal(current.status,'submitted');
  await submit('review-status');assert(byid('status').textContent.includes('通知已存入台账'),byid('errors').textContent);
  assert.equal(run('state.applications.find(a => a.requisition === "JR-2234").status'),'interview');
  const rowBeforeBoard=await run("request('/api/state')");
  assert.equal(rowBeforeBoard.applications.find(a=>a.id===current.id).resume_label,'英文简历 v4');
  const icsLink=nodes(root).find(n=>n.tagName==='a'&&n.href?.endsWith('/api/calendar?id='+current.id));
  assert(icsLink,'calendar link for interview');
  const ics=await fetch(icsLink.href);
  assert(ics.ok);
  assert.match(ics.headers.get('content-type'),/^text\/calendar/);
  assert.match(await ics.text(),/BEGIN:VEVENT/);
  await click('看板');
  const board=nodes(root).find(n=>n.attrs?.['aria-label']==='按状态组织的投递看板');
  assert(board?.textContent?.includes('自动化实习'));
  assert(board?.textContent?.includes('英文简历 v4'));
  const select=byid('board-'+current.id+'-status');
  const update=nodes(board).find(n=>n.className==='board-item'&&nodes(n).includes(select));
  const button=nodes(update).find(n=>n.tagName==='button'&&n.textContent==='保存状态');
  assert(button.disabled,'quick save initially disabled');
  select.value='waiting';select.handlers.change();
  assert(!button.disabled,'quick save enabled after selecting different status');
  assert.equal((await run("request('/api/state')")).applications.find(a=>a.id===current.id).status,'interview');
  await button.handlers.click();
  assert.equal((await run("request('/api/state')")).applications.find(a=>a.id===current.id).status,'waiting');
  assert(!nodes(root).find(n=>n.tagName==='a'&&n.href?.endsWith('/api/calendar?id='+current.id)),'waiting has no active calendar item');
  await click('列表');
  const history=await run("request('/api/history?id='+currentEdit)");
  assert(Array.isArray(history)&&history[0].status==='interview');
  run("setTab('profile')");
  assert.equal(byid('profile-coverage-education').textContent,'0/0');
  const basic=byid('resume-section-basic');
  const originalFilled=Number(byid('profile-coverage-basic').textContent.split('/')[0]);
  const hadName=Boolean(byid('profile-full_name').value.trim());
  byid('profile-full_name').value='   ';basic.handlers.input();
  assert.equal(byid('profile-coverage-basic').textContent,(originalFilled-Number(hadName))+'/9');
  byid('profile-full_name').value='许示例';basic.handlers.input();
  assert.equal(byid('profile-coverage-basic').textContent,(originalFilled-Number(hadName)+1)+'/9');
  byid('profile-email').value='fixture@example.invalid';byid('profile-resume_en').value='EnglishResume-v3';
  const demoLink=nodes(root).find(item=>item.tagName==='a'&&item.textContent==='查看分组卡片');
  assert.equal(demoLink.href,host+'/demo-form.html?preview=1');
  const previewModule=await fetch(host+'/review-cards.mjs');
  assert.equal(previewModule.status,200);
  assert.match(previewModule.headers.get('content-type'),/^text\/javascript/);
  byid('profile-answers').value='为什么申请？ = 希望实践测试开发。';
  const gender=byid('profile-gender');
  assert.equal(gender.tagName,'select');
  assert.deepEqual(gender.children.map(option=>option.value),['','男','女']);
  assert.equal(gender.value,'');
  gender.value='女';
  const city=byid('profile-city');
  assert(byid(city.attrs.list).children.some(option=>option.value==='香港'));
  city.value='演示城市';
  run("setProfileInputValue(qs('#profile-political_status'),'演示资料')");
  byid('profile-id_card').value='本地证件号演示标记';
  byid('profile-target_position').value='测试开发';
  await click('添加教育经历');
  byid('profile-education-0-school').value='示例本科院校';
  await click('添加教育经历');
  byid('profile-education-1-school').value='示例研究生院校';
  byid('profile-education-1-start').value='2025-09';
  byid('profile-education-1-gpa').value='3.75';
  byid('profile-education-1-diploma_number').value='本地学历证书演示标记';
  await click('添加教育经历');
  byid('profile-education-2-counselor_contact').value='仅本地联系方式';
  await click('添加实习经历');
  byid('profile-internships-0-company').value='示例实习单位';
  await click('添加工作经历');
  byid('profile-work_experience-0-company').value='示例工作单位';
  byid('profile-work_experience-0-reference_name').value='本地证明人演示标记';
  await click('添加校园经历');
  byid('profile-campus_experience-0-organization').value='示例校园组织';
  await click('添加获奖记录');
  byid('profile-awards-0-name').value='示例奖项';
  await click('添加外语记录');
  byid('profile-languages-0-language').value='英语';
  await click('添加家庭成员');
  byid('profile-family_relations-0-name').value='示例家人';
  await click('添加专利');
  byid('profile-patents-0-title').value='示例专利';
  await click('添加论文');
  byid('profile-publications-0-title').value='示例论文';
  await submit('profile-full_name');assert(byid('status').textContent.includes('资料已保存到本地'),byid('errors').textContent);
  assert.equal(run('state.profile.email'),'fixture@example.invalid');
  assert.equal(run('state.profile.resume_en'),'EnglishResume-v3');
  assert.equal(byid('profile-education-0-school').value,'示例本科院校');
  assert.equal(byid('profile-education-1-start').value,'2025-09');
  assert.equal(byid('profile-education-1-gpa').value,'3.75');
  assert.equal(byid('profile-id_card').value,'本地证件号演示标记');
  assert.equal(byid('profile-internships-0-company').value,'示例实习单位');
  assert.equal(byid('profile-gender').value,'女');
  assert.equal(byid('profile-city').value,'演示城市');
  assert.equal(byid('profile-political_status').value,'演示资料');
  assert(byid('profile-political_status').children.some(option=>option.value==='演示资料'));
  const companies=byid(byid('profile-work_experience-0-company').attrs.list).children.map(option=>option.value);
  assert.deepEqual(companies,['示例工作单位']);
  assert.equal(byid('profile-id_card').attrs.list,undefined);
  assert.equal(byid('profile-work_experience-0-reference_name').attrs.list,undefined);
  assert.equal(byid('profile-family_relations-0-name').value,'示例家人');
  assert.equal(byid('profile-patents-0-title').value,'示例专利');
  assert.equal(byid('profile-publications-0-title').value,'示例论文');
  await click('移除此条教育经历');
  await submit('profile-full_name');
  assert.equal(byid('profile-education-0-school').value,'示例研究生院校');
  assert.equal(run('state.profile.resume_details.education.length'),2);
  await click('导出填表资料 JSON');
  const exportedProfile=JSON.parse(await downloads.at(-1).text()).profile;
  assert.equal(exportedProfile.email,'fixture@example.invalid');
  assert.deepEqual(exportedProfile.resume_details,{
    gender:'女',political_status:'演示资料',
    education:[{school:'示例研究生院校',start:'2025-09'},{}],internships:[{company:'示例实习单位'}],
    work_experience:[{company:'示例工作单位'}],campus_experience:[{organization:'示例校园组织'}],
    awards:[{name:'示例奖项'}],languages:[{language:'英语'}],
  });
  assert(!('resume_en' in exportedProfile));
  byid('profile-email').value='draft@example.invalid';
  nodes(root).find(e=>e.className==='profile-form').handlers.input();
  run('window.confirm=()=>false');
  run("setTab('tracking')");
  assert.equal(run('tab'),'profile');
  assert.equal(byid('profile-email').value,'draft@example.invalid');
  await click('保存并导出填表资料 JSON');
  assert.equal(JSON.parse(await downloads.at(-1).text()).profile.email,'draft@example.invalid');
  assert.equal((await run("request('/api/state')")).profile.email,'draft@example.invalid');
  const downloadCount=downloads.length;
  await run("request('/api/profile',{...state.profile,resume_fields_version:1,profile_revision:state.profile_revision,email:'other-tab@example.invalid'})");
  await click('导出填表资料 JSON');
  assert.equal(downloads.length,downloadCount);
  assert.equal(byid('profile-email').value,'other-tab@example.invalid');
  assert(byid('status').textContent.includes('核对'));
  await click('导出填表资料 JSON');
  assert.equal(JSON.parse(await downloads.at(-1).text()).profile.email,'other-tab@example.invalid');
  run("const profileFetch=fetch;let finishRead;fetch=async (...args)=>{const response=await profileFetch(...args);await new Promise(resolve=>finishRead=resolve);return response;}");
  const pendingExport=click('导出填表资料 JSON');
  for(let i=0;i<100&&!run('finishRead');i++)await new Promise(r=>setTimeout(r,10));
  byid('profile-email').value='during-read@example.invalid';
  run('fetch=profileFetch;finishRead()');
  await pendingExport;
  assert.equal(downloads.length,downloadCount+1);
  assert.equal(byid('profile-email').value,'during-read@example.invalid');
  assert.equal((await run("request('/api/state')")).profile.email,'other-tab@example.invalid');
  run('window.confirm=()=>true');
  // The profile editor keeps one draft across sections. Import has separate review and save actions.
  await click('教育经历');
  assert.equal(run('profileSectionKey'),'education');
  await click('基本信息');
  assert.equal(run('profileSectionKey'),'basic');
  assert(nodes(byid('resume-scroll')).includes(byid('resume-section-education')));
  assert(!byid('resume-section-education').hidden);
  const resumeText='姓名：另一演示姓名\n常用名：演示昵称\n教育经历\n学校：示例研究生院校\n学校：新演示学校 | 专业：电气';
  byid('resume-import-file').files=[{name:'demo.txt',size:Buffer.byteLength(resumeText),content:resumeText}];
  await submit('resume-import-file');
  assert(text().includes('已有相同记录'),byid('errors').textContent);
  assert.equal(byid('profile-preferred_name').value,'');
  assert.equal((await run("request('/api/state')")).profile.resume_details.education.length,2);
  await click('将所选内容加入资料草稿');
  assert.equal(byid('profile-full_name').value,'许示例');
  assert.equal(byid('profile-preferred_name').value,'演示昵称');
  assert.equal(byid('profile-education-2-school').value,'新演示学校');
  assert.equal((await run("request('/api/state')")).profile.resume_details.education.length,2);
  await submit('profile-preferred_name');
  assert.equal((await run("request('/api/state')")).profile.resume_details.education.length,3);
  assert.equal(run('link("bad", "javascript:alert(1)")'),null);
  // Synthetic MIME import through the actual file-selection/preview/confirm UI.
  const mailA=await run("request('/api/application',{submitted_at:'2026-11-01T10:00+08:00',company:'Fictional UI Harbor',title:'Data Intern',requisition:'UI-A1001',status:'submitted'})");
  const mailB=await run("request('/api/application',{submitted_at:'2026-11-01T10:00+08:00',company:'Fictional UI Harbor',title:'Systems Graduate',requisition:'UI-B2002',status:'interview',interview_at:'2026-12-03T14:00+08:00'})");
  await run('refresh()');run(`currentEdit=${mailA.application.id};setTab('tracking');render()`);
  function syntheticMail(plain){
    const content=['Subject: Application update','From: no-reply@example.invalid','Date: Thu, 19 Nov 2026 06:00:00 +0000','MIME-Version: 1.0','Content-Type: multipart/alternative; boundary="fictional-boundary"','','--fictional-boundary','Content-Type: text/plain; charset=utf-8','',plain,'--fictional-boundary','Content-Type: text/html; charset=utf-8','','<p>Company: Fictional UI Harbor</p><p>Role: Data Intern</p><p>Job ID: UI-A1001</p><p>Your application was unsuccessful.</p><script>evil()</script><img src="https://example.invalid/pixel?token=private">','--fictional-boundary--',''].join('\r\n');
    return {content,size:Buffer.byteLength(content)};
  }
  byid('notice-eml').files=[syntheticMail('Please do not reply.')];
  await submit('notice-eml');
  assert.equal(byid('review-target').value,String(mailA.application.id));
  assert.equal(byid('review-status').value,'closed');
  assert(text().includes('判断证据（仅文本，不打开邮件资源）'));
  assert(text().includes('HTML 正文'));assert(text().includes('Your application was unsuccessful.'));
  assert(!text().includes('evil()'));assert(!text().includes('token=private'));
  assert.equal(run(`state.applications.find(a=>a.id===${mailA.application.id}).status`),'submitted');
  await submit('review-status');
  assert.equal(run(`state.applications.find(a=>a.id===${mailA.application.id}).status`),'closed');
  assert.deepEqual((await run("request('/api/state')")).applications.find(a=>a.id===mailB.application.id),mailB.application);
  byid('notice-eml').files=[syntheticMail('Company: Fictional UI Harbor\nRole: Data Intern\nJob ID: UI-A1001\nInterview is confirmed.')];
  await submit('notice-eml');
  assert.equal(byid('review-target').value,'');
  assert.equal(byid('review-status').value,'');
  assert(text().includes('状态冲突'));
  byid('review-target').value=String(mailA.application.id);
  await submit('review-status');
  assert(byid('errors').textContent.includes('请先勾选已复核'));
  byid('review-review_confirmed').checked=true;
  await submit('review-status');
  assert(byid('status').textContent.includes('未覆盖当前状态'));
  assert.equal(run(`state.applications.find(a=>a.id===${mailA.application.id}).status`),'closed');
  assert.deepEqual((await run("request('/api/state')")).applications.find(a=>a.id===mailB.application.id),mailB.application);
  console.log('MIME UI+HTTP passed: file import, inert quoted evidence, preview without writes, only A closed, B unchanged, conflict target/status blank, review checkbox required, no-change history.');
  // Real capture module (synthetic page) -> draft fragment -> UI form -> HTTP/SQLite -> HK filter.
  const locationCases=[
    ['True HK','The internship is based in Hong Kong.','hk_onsite'],
    ['Overseas internship','The internship is based in Singapore. After graduation the permanent role is in Hong Kong.','conflict'],
    ['Overseas headquarters','Our headquarters are in London. The internship is based in Hong Kong.','hk_onsite'],
    ['Mandatory rotation','The internship is based in Hong Kong. Mandatory training in Singapore is required.','rotation'],
    ['Missing evidence','','missing']
  ];
  for(const [fixtureIndex,[name,description,status]] of locationCases.entries()){
    const title='Fixture-location '+name+' Intern';
    const localHTML=fs.readFileSync(join(project,'tests','fixtures',`location-${fixtureIndex}.html`),'utf8');
    const data=JSON.parse(localHTML.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/)[1]);
    assert.equal(data.title,title);assert.equal(data.description,description);
    const scan=vm.runInNewContext('('+inspectJobPage.toString()+')()',{
      location:new URL('https://example.invalid/jobs/'+encodeURIComponent(name)),URL,
      document:{querySelector:()=>null,querySelectorAll:()=>[{textContent:JSON.stringify(data)}]},getComputedStyle:()=>({visibility:'visible'})
    });
    const capture=new URL(makeCaptureLink(8765,scan.draft));
    run(`location.hash=${JSON.stringify(capture.hash)};window.handlers.hashchange()`);
    assert.equal(byid('job-location').value,'Hong Kong');
    if(description)assert(byid('job-description').value.includes('[正文:元数据]'));
    assert(!(await run("request('/api/state')")).jobs.some(j=>j.title===title),'draft only before confirmation');
    await submit('job-company');
    const saved=(await run("request('/api/state')")).jobs.find(j=>j.title===title);
    assert.equal(saved.location,'Hong Kong');assert.equal(saved.location_review.status,status);
  }
  run("jobSearch='Fixture-location';jobRoute='hk';render()");
  const results=byid('job-results');
  const reviewSection=results.children.find(n=>n.tagName==='section');
  const supportedText=results.children.filter(n=>n!==reviewSection).map(n=>n.textContent||'').join('');
  assert(supportedText.includes('正文支持香港实地实习 2 个岗位'));
  assert(supportedText.includes('True HK'));assert(supportedText.includes('Overseas headquarters'));
  assert(!supportedText.includes('Overseas internship'));assert(!supportedText.includes('Mandatory rotation'));
  assert(reviewSection.textContent.includes('不计入香港实地实习'));assert(reviewSection.textContent.includes('3 个'));
  for(const name of ['Overseas internship','Mandatory rotation','Missing evidence'])assert(reviewSection.textContent.includes(name));
  assert(reviewSection.textContent.includes('JobPosting.description'));
  run("jobRoute='';render()");
  for(const [name] of locationCases)assert(byid('job-results').textContent.includes(name));
  // Search terms may appear in different fields, in any order, with flexible whitespace.
  const searchJobs=(value)=>{
    const input=byid('job-filter-search');
    input.value=value;input.handlers.input({target:input});
    return byid('job-results').textContent;
  };
  assert(searchJobs('Hong Kong   True HK').includes('True HK'),'location and title terms must match regardless of order');
  assert(!byid('job-results').textContent.includes('Overseas headquarters'));
  assert(searchJobs('  ＦＩＸＴＵＲＥ-location   TRUE  HK  ').includes('True HK'),'width, case and whitespace normalization');
  assert(searchJobs('True HK nonexistent-token').includes('匹配 0 个岗位'),'every search term must match the same job');
  searchJobs('Hong Kong True HK');
  const route=byid('job-filter-route');
  route.value='hk';route.handlers.change({target:route});
  assert(!byid('job-results').textContent.includes('Overseas internship'),'unmatched title should not appear in location review');
  searchJobs('Hong Kong Fixture-location');
  assert(byid('job-results').textContent.includes('正文支持香港实地实习 2 个岗位'));
  assert(byid('job-results').textContent.includes('地点待复核（不计入香港实地实习）：3 个'));
  route.value='';route.handlers.change({target:route});
  searchJobs('   ');
  for(const [name] of locationCases)assert(byid('job-results').textContent.includes(name));
  console.log('Location capture/UI/HTTP passed: 5 synthetic pages, confirmed save only, raw HK preserved, 2 supported HK and 3 visible review rows, all remain in all-regions view.');
  const identityInputs=[
    {url:'https://example.invalid/identity/A',requisition:'I-1'},
    {url:'https://example.invalid/identity/B',requisition:'I-2'},
    {url:'https://other.invalid/identity/A',requisition:'I-1'},
    {url:'https://example.invalid/identity/C',requisition:''},
    {url:'https://example.invalid/identity/D',requisition:''}
  ];
  for(const [index,item] of identityInputs.entries()){
    const draft={company:'Fictional UI Identity',title:'Same Data Intern',location:'Hong Kong',career_type:'intern',description:'Synthetic responsibility '+index,...item};
    run(`location.hash='#discovery?capture='+encodeURIComponent(${JSON.stringify(JSON.stringify(draft))});window.handlers.hashchange()`);
    assert.equal((await run("request('/api/state')")).jobs.filter(j=>j.company==='Fictional UI Identity').length,index);
    await submit('job-company');
  }
  run("jobSearch='Fictional UI Identity';jobRoute='';render()");
  assert(byid('job-results').textContent.includes('相似岗位或编号重复，已分别保留'));
  assert(searchJobs('I-2 Fictional UI Identity').includes('编号 I-2'));
  assert(!byid('job-results').textContent.includes('编号 I-1'));
  searchJobs('Fictional UI Identity');
  const saveButtons=nodes(byid('job-results')).filter(n=>n.tagName==='button'&&n.textContent==='存到投递台账');
  assert.equal(saveButtons.length,5);
  for(const button of saveButtons)await button.handlers.click();
  let identityState=await run("request('/api/state')");
  let identityApps=identityState.applications.filter(a=>a.company==='Fictional UI Identity');
  assert.equal(identityApps.length,5);
  await run(`request('/api/application',${JSON.stringify({...identityApps[0],status:'interview'})})`);
  await saveButtons[0].handlers.click();
  identityApps=(await run("request('/api/state')")).applications.filter(a=>a.company==='Fictional UI Identity');
  assert.equal(identityApps.length,5);assert.equal(identityApps.filter(a=>a.status==='interview').length,1);assert.equal(identityApps.filter(a=>a.status==='saved').length,4);
  console.log('Identity UI/HTTP passed: 5 separate confirmed drafts and applications; reused ID and no-ID similarity reviewed; repeated save preserves independent status.');
  // One company/job/application through all three core features; temporary DB only.
  const loopSource=await run("request('/api/source',{company:'Fictional Core Loop',provider:'demo',board:'core-loop'})");
  await run(`request('/api/source/check',{id:${loopSource.source.id}})`);
  const discovered=await run(`request('/api/source/check',{id:${loopSource.source.id}})`);
  assert.equal(discovered.results[0].new,1);
  await run('refresh()');run("jobSearch='Fictional Core Loop';jobRoute='';setTab('discovery');render()");
  assert(!(await run("request('/api/state')")).applications.some(a=>a.company==='Fictional Core Loop'));
  const loopJob=run("state.jobs.find(j=>j.company==='Fictional Core Loop'&&j.requisition==='AGENT-03')");
  run("jobSearch='AGENT-03';render()");
  // Select exact company's row; other demo sources may also have AGENT-03.
  const loopRow=nodes(byid('job-results')).reverse().find(n=>n.textContent?.includes('Fictional Core Loop')&&nodes(n).some(c=>c.tagName==='button'&&c.textContent==='存到投递台账'));
  assert(loopRow);await nodes(loopRow).find(n=>n.tagName==='button'&&n.textContent==='存到投递台账').handlers.click();
  const loopApp=(await run("request('/api/state')")).applications.find(a=>a.company==='Fictional Core Loop');
  assert.equal(loopApp.requisition,loopJob.requisition);
  const practice=await (await fetch(host+'/demo-form.html')).text();assert(practice.includes('method="dialog"'));
  const simulated=mockedDOM();let submissions=0;
  const sampleForm={id:'sample-career-form',getAttribute:()=>'',submit(){submissions++;},requestSubmit(){submissions++;}};
  for(const id of ['fullName','email']){
    const label=practice.match(new RegExp('<label for="'+id+'">([^<]+)'))[1];
    simulated.nodes.push(new simulated.FakeInput(label,{id,type:id==='email'?'email':'text',form:sampleForm}));
  }
  const scan=inspectPage('scan');
  const sampleProfile=loadProfile(JSON.parse(fs.readFileSync(join(project,'extension/demo-profile.json'),'utf8')));
  const plan=makePlan(scan.fields,sampleProfile).filter(r=>r.match);
  assert(simulated.nodes.every(n=>n.value===''),'preview must not fill');assert.equal(submissions,0);
  const confirmed=plan.map(r=>({index:r.field.index,token:r.field.token,value:r.value}));
  assert.equal(inspectPage('fill',confirmed,simulated.url.href,scan.session).filled,2);assert.equal(submissions,0);
  assert.equal(simulated.nodes[1].value,sampleProfile.email);
  await run(`request('/api/application',${JSON.stringify({...loopApp,status:'submitted',submitted_at:'2026-11-01T10:00+08:00'})})`);
  async function loopPreview(name){
    await run('refresh()');run(`currentEdit=${loopApp.id};setTab('tracking');render()`);
    const content=fs.readFileSync(join(project,'tests/fixtures/core-loop',name+'.eml'),'utf8');
    byid('notice-eml').files=[{content,size:Buffer.byteLength(content)}];await submit('notice-eml');
  }
  const loopCurrent=async()=> (await run("request('/api/state')")).applications.find(a=>a.id===loopApp.id);
  await loopPreview('01-invitation');assert.equal((await loopCurrent()).status,'submitted');
  await submit('review-status');assert.equal((await loopCurrent()).deadline,'2026-11-03T18:00+08:00');
  for(const [name,due] of [['02-extension','2026-11-05T10:00+08:00'],['03-extension','2026-11-06T10:00+08:00']]){
    await loopPreview(name);assert(text().includes('LOOP-TEST-1'));assert(text().includes('估算'));
    const before=await loopCurrent();await submit('review-status');assert.equal((await loopCurrent()).deadline,before.deadline,'unchecked must not update');
    byid('review-same_assessment_confirmed').checked=true;await submit('review-status');
    assert.equal((await loopCurrent()).deadline,due);assert.equal((await loopCurrent()).date_precision.deadline,'estimated');
  }
  await loopPreview('03-extension');byid('review-same_assessment_confirmed').checked=true;await submit('review-status');
  assert(byid('status').textContent.includes('已导入过'));
  await loopPreview('02-extension');byid('review-same_assessment_confirmed').checked=true;await submit('review-status');
  assert.equal((await loopCurrent()).deadline,'2026-11-06T10:00+08:00');
  for(const name of ['04-unknown','06-different-test']){
    await loopPreview(name);byid('review-target').value=String(loopApp.id);byid('review-review_confirmed').checked=true;await submit('review-status');
    assert.equal((await loopCurrent()).deadline,'2026-11-06T10:00+08:00');
  }
  await loopPreview('07-second-test');await submit('review-status');
  await loopPreview('08-completed-first');
  assert.equal(byid('review-status').value,'waiting');
  await submit('review-status');assert.equal((await loopCurrent()).status,'assessment');
  assert(!(await loopCurrent()).assessment_tasks.find(t=>t.id==='LOOP-TEST-1').completed);
  byid('review-assessment_completion_confirmed').checked=true;await submit('review-status');
  assert.equal((await loopCurrent()).deadline,'2026-11-08T12:00+08:00');
  assert((await loopCurrent()).assessment_tasks.find(t=>t.id==='LOOP-TEST-1').completed);
  assert(!(await loopCurrent()).assessment_tasks.find(t=>t.id==='LOOP-TEST-2').completed);
  await loopPreview('09-completed-second');byid('review-assessment_completion_confirmed').checked=true;await submit('review-status');
  assert.equal((await loopCurrent()).status,'waiting');assert.equal((await loopCurrent()).deadline,'');
  await loopPreview('08-completed-first');byid('review-assessment_completion_confirmed').checked=true;await submit('review-status');
  assert(byid('status').textContent.includes('已导入过'));
  await loopPreview('03-extension');byid('review-same_assessment_confirmed').checked=true;await submit('review-status');
  assert.equal((await loopCurrent()).status,'waiting');assert.equal((await loopCurrent()).deadline,'');
  console.log('COMPLETION LOOP PASS: explicit confirmation only; A completed while B remains due; B completion waits for result; duplicate receipt and old extension cannot reopen; evidence retained.');
  await loopPreview('05-interview');await submit('review-status');
  assert.equal((await loopCurrent()).status,'interview');assert.equal((await loopCurrent()).interview_at,'2026-11-10T14:00+08:00');
  const loopHistory=await run(`request('/api/history?id=${loopApp.id}')`);
  assert(JSON.stringify(loopHistory).includes('LOOP-TEST-1'));assert(JSON.stringify(loopHistory).includes('2026-11-03T18:00'));
  console.log('CORE LOOP PASS: new offline job -> confirmed application -> practice preview/explicit fill/no submit -> same application invitation/two confirmed 48h extensions/interview; original evidence, dedup, old order and unknown/different assessment protected. DOM simulated; HTTP/SQLite real.');
  const ackApp=(await run("request('/api/application',{company:'Fictional UI Receipt',title:'Test Developer',requisition:'ACK-UI',status:'assessment',deadline:'2026-12-01T10:00+08:00',next_action:'Keep original assessment'})")).application;
  await run('refresh()');run(`currentEdit=${ackApp.id};setTab('tracking');render()`);
  byid('notice-text').value='Your application for Test Developer was submitted. Thank you for applying.';
  byid('notice-company').value=ackApp.company;byid('notice-title').value=ackApp.title;byid('notice-requisition').value=ackApp.requisition;byid('notice-received_at').value='2026-11-20 10:00';
  await submit('notice-text');assert.equal(byid('review-status').value,'waiting');assert(text().includes('粘贴通知当前正文'));assert(text().includes('application for Test Developer'));
  await submit('review-status');
  assert(byid('status').textContent.includes('未覆盖当前状态'));
  const ackAfter=(await run("request('/api/state')")).applications.find(a=>a.id===ackApp.id);
  assert.equal(ackAfter.status,'assessment');assert.equal(ackAfter.deadline,ackApp.deadline);assert.equal(ackAfter.next_action,ackApp.next_action);
  console.log('RECEIPT LOOP PASS: pasted ordinary Test Developer acknowledgement previews original text, confirms history only, preserves assessment deadline/action.');
  console.log('UI+HTTP smoke passed: tabs, demo baseline and notification, filter/save, create, preview only until explicit confirmation, history, profile, resume label, draft review and fragment removal, board status change, actual calendar download, safe URL rejection.');
}
try{
  host=await new Promise((resolve,reject)=>{
    let output='';
    const timer=setTimeout(()=>reject(new Error('Local test server startup timed out: '+stderr)),10000);
    server.stdout.on('data',chunk=>{
      output+=chunk.toString();
      const m=output.match(/http:\/\/127\.0\.0\.1:\d+/);
      if(m){clearTimeout(timer);resolve(m[0]);}
    });
    server.once('error',e=>{clearTimeout(timer);reject(e);});
    server.once('exit',status=>{clearTimeout(timer);reject(new Error('Local test server stopped ('+status+'): '+stderr));});
  });
  run=init();
  await main();
}finally{
  server.kill();
  await exited;
  fs.rmSync(temp,{recursive:true,force:true});
}
