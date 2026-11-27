import { mockedDOM } from './mock_dom.mjs';
import assert from 'node:assert/strict';
import { test } from 'node:test';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { loadProfile, makePlan, matchField, textSuggestions } from '../extension/matcher.mjs';
import { inspectPage } from '../extension/page.mjs';

const SAMPLE_PROFILE = { profile: {
  full_name: 'Practice Candidate', preferred_name: 'Practice', email: 'practice@example.com',
  phone: '+852 2345 9876', city: '香港', school: '示例大学', major: '计算机科学',
  graduation: '2099-12-01', available_from: '2099-04-01', github: 'https://github.com/example',
  project_summary: '第一行\n第二行', answers: { sponsorship: 'yes' },
}};
const profile = loadProfile(SAMPLE_PROFILE);
const file = name => JSON.parse(readFileSync(new URL('../extension/' + name, import.meta.url), 'utf8'));
const field = (label, extras = {}) => ({ type: 'text', label, ...extras });

test('permission model uses only explicit active tab and scripting', () => {
  const m = file('manifest.json');
  assert.equal(m.manifest_version, 3);
  assert.deepEqual(m.permissions, ['activeTab', 'scripting']);
  assert.equal(m.host_permissions, undefined);
  assert.equal(m.content_scripts, undefined);
  assert.equal(m.background, undefined);
});
test('profile whitelist ignores high-risk values and invalid external URLs', () => {
  assert.equal(profile.graduation, undefined);
  assert.equal(profile.available_from, undefined);
  assert.equal(profile.answers, undefined);
  assert.equal(loadProfile({ ...SAMPLE_PROFILE.profile, github: 'https://github.com.evil.test/example' }).github, undefined);
  assert.equal(loadProfile({ portfolio: 'javascript:alert(1)' }).portfolio, undefined);
  assert.equal(loadProfile({ email: 'one@example.com\ntwo@example.com' }).email, undefined);
  assert.throws(() => loadProfile('no'));
});
test('matches visible bilingual labels and supporting metadata, not just hidden field names', () => {
  assert.equal(matchField(field('姓名 *', { name: 'full_name', autocomplete: 'name' }), profile).key, 'full_name');
  assert.equal(matchField(field('专业（必填）', { id: 'major' }), profile).key, 'major');
  assert.equal(matchField(field('', { type:'email', aria: 'Email address' }), profile).key, 'email');
  assert.equal(matchField(field('', { placeholder: '手机号' }), profile).confidence, '中');
  assert.equal(matchField(field('', { name: 'full_name' }), profile).match, false);
  assert.equal(matchField(field('GitHub URL', { type:'url' }), profile).key, 'github');
});
test('recognizes simplified application labels while verification and eligibility stay manual', () => {
  assert.equal(matchField(field('应聘者姓名'), profile).key, 'full_name');
  assert.equal(matchField(field('电子邮箱地址', { type: 'email', name: 'email' }), profile).key, 'email');
  for (const label of ['确认电子邮箱', '工作许可', '紧急联系人电话']) {
    assert.equal(matchField(field(label, { placeholder: '联系电话' }), profile).match, false);
  }
});
test('does not overwrite, fill ambiguous or duplicate fields, or process credentials and right-to-work', () => {
  const hardManual = [
    field('姓名', { hasValue: true }), field('Email', { maxLength: 3 }), field('邮箱', { type: 'password' }),
    field('邮箱', { context: '付款联系方式' }), field('Email', { context: 'external form action' }), field('姓名', { context: 'login-form' }),
    field('邮箱', { aria: '工作许可' }), field('graduation date'), field('确认邮箱', { name: 'email' }),
    field('个人网站', { name: 'portfolio', type: 'file' }), field('电话', { name: 'phone-country-code' }),
    field('姓名', { aria: 'Email address' }), field('电话', { disabled: true }), field('邮箱', { readonly: true }),
    field('邮箱', { type: 'textarea' }), field('邮箱', { type: 'email', auth: true }),
  ];
  for (const f of hardManual) assert.equal(matchField(f, profile).match, false, JSON.stringify(f));
  assert.ok(makePlan([field('邮箱'), field('Email address')], profile).every(r => !r.match));
});
test('text-only fallback never binds page fields or creates fill commands', () => {
  const rows = textSuggestions('姓名\n预计毕业时间\nEmail address', profile);
  assert.deepEqual(rows.map(r => r.key), ['full_name', undefined, 'email']);
  assert.ok(rows.every(x => !('index' in x) && !('token' in x)));
});

test('dropdowns require a single visible matching option, explicit field label and safe context', () => {
  const p=loadProfile({degree:'本科',resume_details:{gender:'女',political_status:'共青团员'}});
  const degree=field('最高学历',{type:'select',options:[{index:3,label:'大学本科'}]});
  assert.deepEqual(matchField(degree,p),{match:true,key:'degree',value:'大学本科',optionIndex:3,confidence:'中'});
  for(const patch of [{options:[]},{hasValue:true},{options:[...degree.options,{index:4,label:'本科'}]},
    {aria:'性别'},{name:'work_permit'},{context:'家庭资料'},{label:'学位'},{label:'',name:'degree'}]){
    assert.equal(matchField({...degree,...patch},p).match,false);
  }
  const edu=p.resume_details={education:[{degree:'硕士研究生'},{degree:'本科'}]};
  const rows=makePlan([1,2].map(number=>({...degree,options:[...degree.options,{index:4,label:'硕士'}],
    record:{kind:'education',number,count:2}})),p);
  assert.deepEqual(rows.map(row=>row.value),['硕士','大学本科']);
  assert.equal(edu.education.length,2);
  assert(!matchField(field('性别'),p).match);
  assert(!matchField(field('政治面貌'),p).match);
});

test('mock native select binds option identity, preserves an existing choice and dispatches once after confirmation',()=>{
  const {nodes,FakeInput,url}=mockedDOM();
  const input=new FakeInput('性别',{tagName:'SELECT',type:'select-one',id:'candidate_gender'});
  input.size=0;input.selectedIndex=0;
  input.options=[['请选择',''],['男','M'],['女','F']].map(([label,value])=>({label,value,closest:()=>null}));
  Object.defineProperty(input,'selectedOptions',{get:()=>[input.options[input.selectedIndex]]});
  nodes.push(input);
  const profile=loadProfile({resume_details:{gender:'女'}});
  const prepare=()=>{
    const scan=inspectPage('scan'),[m]=makePlan(scan.fields,profile);
    assert.equal(m.match,true);
    return [ [{index:0,token:m.field.token,value:m.value,optionIndex:m.optionIndex}],url.href,scan.session ];
  };
  const events=[];
  for(const type of ['input','change','submit'])input.addEventListener(type,()=>events.push(type));
  const stale=prepare();input.options[2]={...input.options[2]};
  assert.match(inspectPage('fill',...stale).error,/重新扫描/);
  const edited=prepare();input.selectedIndex=1;
  assert.match(inspectPage('fill',...edited).error,/重新扫描/);
  assert.equal(input.selectedIndex,1);assert.deepEqual(events,[]);
  input.selectedIndex=0;const fresh=prepare();
  assert.deepEqual(inspectPage('fill',...fresh),{filled:1,skipped:[]});
  assert.equal(input.selectedOptions[0].value,'F');assert.deepEqual(events,['input','change']);
  assert.match(inspectPage('fill',...fresh).error,/重新扫描/);
});

test('actual page injection only fills approved blank controls and refuses drift', () => {
  const { nodes, FakeInput, url } = mockedDOM();
  const first = new FakeInput('姓名'), nested = new FakeInput('专业', { visible: false });
  const existing = new FakeInput('邮箱', { type: 'email', value: 'old@example.com' });
  const moving = new FakeInput('学校');
  nodes.push(first, nested, existing, moving);
  let inputEvents = 0;
  first.addEventListener('input', () => { inputEvents++; moving.labels[0].innerText = '邮箱'; });
  let scan = inspectPage('scan');
  assert.equal(first.value, '');
  assert.equal(scan.fields.some(f => f.index === 1), false);
  const plan = makePlan(scan.fields, profile).filter(r => r.match);
  const chosen = plan.map(r => ({ index: r.field.index, token: r.field.token, value: r.value }));
  assert.equal(inspectPage('fill', chosen, 'http://localhost:8765/changed').filled, undefined);
  assert.equal(first.value, '');
  scan = inspectPage('scan');
  const done = inspectPage('fill', chosen, url.href, scan.session);
  assert.deepEqual(done, { filled: 1, skipped: [3], stopped: true });
  assert.equal(first.value, 'Practice Candidate');
  assert.equal(existing.value, 'old@example.com');
  assert.equal(moving.value, '');
  assert.equal(inputEvents, 1);
});
test('main-frame scanner declines non-TLS external pages and visible credential controls', () => {
  const { nodes, FakeInput } = mockedDOM();
  nodes.push(new FakeInput('密码', { type: 'password' }));
  assert.match(inspectPage('scan').error, /登录/);
  globalThis.location = new URL('http://example.com/jobs');
  assert.match(inspectPage('scan').error, /HTTPS/);
});

// Regression: old metadata tokens alone accepted an identical replacement node.
test('same URL identical replacement form field must require a new preview', () => {
  const {nodes,FakeInput,url}=mockedDOM();
  const original=new FakeInput('姓名');nodes.push(original);
  const scan=inspectPage('scan');
  const choices=[{index:0,token:scan.fields[0].token,value:'Fictional Candidate'}];
  original.connected=false;nodes[0]=new FakeInput('姓名');
  const result=inspectPage('fill',choices,url.href,scan.session);
  assert.equal(nodes[0].value,'','must never fill the replacement node');
  assert.match(result.error,/重新扫描/);
});

function selectOne(scan, value='Fictional Candidate') {
  return [{index:scan.fields[0].index,token:scan.fields[0].token,value}];
}
test('same-origin different URL rejects preview and its replay', () => {
  const {nodes,FakeInput,url}=mockedDOM();nodes.push(new FakeInput('姓名'));
  const scan=inspectPage('scan');const original=url.href;
  url.pathname='/jobs/B';
  assert.match(inspectPage('fill',selectOne(scan),original,scan.session).error,/重新扫描/);
  assert.equal(nodes[0].value,'');
  url.href=original;
  assert.match(inspectPage('fill',selectOne(scan),original,scan.session).error,/重新扫描/);
});
test('same URL SPA job-heading mutation invalidates otherwise unchanged controls', () => {
  const {nodes,FakeInput,url,mutate}=mockedDOM();nodes.push(new FakeInput('姓名'));
  const scan=inspectPage('scan');mutate();
  assert.match(inspectPage('fill',selectOne(scan),url.href,scan.session).error,/重新扫描/);
  assert.equal(nodes[0].value,'');
});
test('unchanged URL and metadata cannot move the original node to an identical new form', () => {
  const {nodes,FakeInput,url}=mockedDOM();
  const form=()=>({id:'apply',getAttribute:()=>'',querySelector:()=>null});
  const first=new FakeInput('姓名',{form:form()});nodes.push(first);
  const scan=inspectPage('scan');first.form=form();
  assert.match(inspectPage('fill',selectOne(scan),url.href,scan.session).error,/重新扫描/);
  assert.equal(first.value,'');
});
test('a full selection is checked before any write', () => {
  const {nodes,FakeInput,url}=mockedDOM();nodes.push(new FakeInput('姓名'),new FakeInput('邮箱',{type:'email'}));
  const scan=inspectPage('scan');nodes[1].labels[0].innerText='工作许可';
  const choices=scan.fields.map((f,i)=>({index:f.index,token:f.token,value:i?'fictional@example.invalid':'Fictional Candidate'}));
  assert.match(inspectPage('fill',choices,url.href,scan.session).error,/重新扫描/);
  assert(nodes.every(n=>!n.value));
});
test('input listener replacing remaining form stops without filling replacement', () => {
  const {nodes,FakeInput,url,mutate}=mockedDOM();
  const first=new FakeInput('姓名'),second=new FakeInput('邮箱',{type:'email'});nodes.push(first,second);
  first.addEventListener('input',()=>{second.connected=false;nodes[1]=new FakeInput('邮箱',{type:'email'});mutate();});
  const scan=inspectPage('scan');
  const choices=scan.fields.map((f,i)=>({index:f.index,token:f.token,value:i?'fictional@example.invalid':'Fictional Candidate'}));
  const result=inspectPage('fill',choices,url.href,scan.session);
  assert.equal(result.filled,1);assert.equal(result.stopped,true);
  assert.equal(second.value,'');assert.equal(nodes[1].value,'');
});
test('unchanged practice page fills once with no retained personal value or replay', () => {
  const {nodes,FakeInput,url}=mockedDOM();nodes.push(new FakeInput('姓名'));
  const scan=inspectPage('scan');const session=globalThis.__jobWorkbenchFormPreviewV113;
  assert(!JSON.stringify(scan).includes('Fictional Candidate'));
  assert.deepEqual(Object.keys(session.bindings.get(0)).sort(),['form','node','token']);
  assert.deepEqual(inspectPage('fill',selectOne(scan),url.href,scan.session),{filled:1,skipped:[]});
  assert.equal(globalThis.__jobWorkbenchFormPreviewV113,undefined);
  nodes[0].value='';
  assert.match(inspectPage('fill',selectOne(scan),url.href,scan.session).error,/重新扫描/);
});
test('hidden tab, switch away and back, expired session, and same URL new document stop', () => {
  for(const scenario of ['hidden','back','expired','document']){
    const {nodes,FakeInput,url}=mockedDOM();nodes.push(new FakeInput('姓名'));
    const scan=inspectPage('scan');
    if(scenario==='hidden')document.visibilityState='hidden';
    if(scenario==='back'){
      document.visibilityState='hidden';document.dispatchEvent(new Event('visibilitychange'));
      document.visibilityState='visible';document.dispatchEvent(new Event('visibilitychange'));
    }
    if(scenario==='expired')globalThis.__jobWorkbenchFormPreviewV113.expires=0;
    if(scenario==='document')globalThis.document={...document};
    assert.match(inspectPage('fill',selectOne(scan),url.href,scan.session).error,/重新扫描/,scenario);
    assert.equal(nodes[0].value,'',scenario);
  }
});

test('serialized injection retains session only in its original isolated document world',()=>{
  const {nodes,FakeInput,url}=mockedDOM();nodes.push(new FakeInput('姓名'));
  const context=()=>vm.createContext({document,location,getComputedStyle,HTMLInputElement:FakeInput,HTMLTextAreaElement:FakeInput,MutationObserver,crypto,URL,Event,setTimeout,clearTimeout});
  const first=context(),second=context();
  const fn=vm.runInContext('('+inspectPage.toString()+')',first);
  const scan=fn('scan');
  const wrong=vm.runInContext('('+inspectPage.toString()+')',second);
  assert.match(wrong('fill',selectOne(scan),url.href,scan.session).error,/重新扫描/);
  assert.equal(nodes[0].value,'');
  assert.equal(fn('fill',selectOne(scan),url.href,scan.session).filled,1);
});
test('a new scan invalidates the old confirmation even when metadata is identical',()=>{
  const {nodes,FakeInput,url}=mockedDOM();nodes.push(new FakeInput('姓名'));
  const old=inspectPage('scan'),fresh=inspectPage('scan');
  assert.notEqual(old.session,fresh.session);
  assert.match(inspectPage('fill',selectOne(old),url.href,old.session).error,/重新扫描/);
  assert.equal(nodes[0].value,'');
});

test('focused scan can select one of two matching inputs but rejects focus changes', () => {
  const { nodes, FakeInput, url } = mockedDOM();
  const first = new FakeInput('姓名');
  const second = new FakeInput('姓名');
  nodes.push(first, second);
  assert.ok(makePlan(inspectPage('scan').fields, profile).every(row => !row.match));
  assert.match(inspectPage('scan-focused').error, /先点击/);
  document.activeElement = second;
  const old = inspectPage('scan-focused');
  assert.equal(old.fields.length, 1);
  assert.equal(makePlan(old.fields, profile)[0].key, 'full_name');
  assert.ok(nodes.every(node => !node.value));
  document.activeElement = first;
  assert.match(inspectPage('fill', selectOne(old), url.href, old.session).error, /重新扫描/);
  document.activeElement = second;
  const fresh = inspectPage('scan-focused');
  assert.equal(inspectPage('fill', selectOne(fresh), url.href, fresh.session).filled, 1);
  assert.equal(first.value, '');
  assert.equal(second.value, 'Fictional Candidate');
});

test('unbound adjacent label requires an isolated control and a valid preview', () => {
  const { nodes, FakeInput, url } = mockedDOM();
  const input = new FakeInput('', { type: 'email', name: 'email' });
  const label = new FakeInput('', { tagName: 'LABEL' });
  label.innerText = '电子邮箱地址';
  label.hasAttribute = () => false;
  input.previousElementSibling = label;
  nodes.push(input);
  const group = [input, new FakeInput('電話')];
  input.parentElement = { querySelectorAll: () => group };
  assert.equal(makePlan(inspectPage('scan').fields, profile)[0].match, false);
  group.pop();
  label.visible = false;
  assert.equal(makePlan(inspectPage('scan').fields, profile)[0].match, false);
  label.visible = true;
  const scan = inspectPage('scan');
  const [row] = makePlan(scan.fields, profile);
  assert.equal(row.key, 'email');
  assert.equal(row.confidence, '中');
  label.innerText = '确认电子邮箱';
  assert.match(inspectPage('fill', selectOne(scan, row.value), url.href, scan.session).error, /重新扫描/);
  assert.equal(input.value, '');
});

test('structured résumé data is matched by record number and protected fields stay out', () => {
  const demo = loadProfile(file('demo-profile.json'));
  const {nodes, FakeInput} = mockedDOM();
  const group = text => ({querySelector: () => ({innerText: text}), getAttribute: () => ''});
  const first = group('教育经历 第1条'), second = group('教育经历 第2条');
  const add = (container, label, options) => {
    const input = new FakeInput(label, options);
    input.closest = selector => selector.startsWith('fieldset') ? container : null;
    nodes.push(input);
    return input;
  };
  add(first, '学校');
  add(second, '学校');
  add(second, '毕业年月', {type:'month'});
  add(second, '专业', {value:'已有专业'});
  add(second, '工作许可', {attrs:{placeholder:'学校'}});
  const scan = inspectPage('scan');
  const plan = makePlan(scan.fields, demo);
  assert.deepEqual(plan.filter(row=>row.match).map(row=>[row.field.record.number,row.key,row.value]),[
    [1,'school','示例工学院'],[2,'school','示例工程大学'],[2,'end','2028-06'],
  ]);
  assert(plan.filter(row=>row.match).every(row=>row.confidence==='中'));
  assert.equal(nodes[0].value,'');
  assert.equal(nodes[3].value,'已有专业');
  assert.equal(nodes[4].value,'');
  assert(makePlan(scan.fields, {...demo,resume_details:{education:demo.resume_details.education.slice(0,1)}})
    .every(row=>!row.match));
  document.activeElement=nodes[0];
  assert(makePlan(inspectPage('scan-focused').fields, demo).every(row=>!row.match));
  [nodes[0],nodes[1]]=[nodes[1],nodes[0]];
  assert(makePlan(inspectPage('scan').fields, demo).every(row=>!row.match));
});

test('structured import keeps supported keys and leaves ambiguous dates and duplicate fields manual', () => {
  const demo = loadProfile({resume_details:{
    certificates:[{name:'演示证书',date:'2025-13',number:'private-marker'}],family_relations:[{name:'local-only'}],
  }});
  assert.deepEqual(demo,{resume_details:{certificates:[{name:'演示证书'}]}});
  const meta={kind:'certificates',number:1,count:1};
  assert(makePlan([field('证书名称',{record:meta}),field('证书名称',{record:meta}),field('取得年月',{type:'month',record:meta})],demo)
    .every(row=>!row.match));
});

test('work, campus, award and language records map independently by number', () => {
  const exported = file('demo-profile.json');
  exported.profile.resume_details.work_experience[0].reference_name = '本地证明人标记';
  exported.profile.resume_details.family_relations = [{name:'本地家属标记'}];
  exported.profile.id_card = '本地证件号标记';
  const demo = loadProfile(exported);
  const samples = [
    ['work_experience',1,2,'工作单位','示例能源装备厂'],
    ['work_experience',2,2,'工作单位','示例信息技术所'],
    ['campus_experience',1,1,'组织或活动','示例大学科技协会'],
    ['awards',1,2,'奖项名称','示例校园创新奖'],
    ['awards',2,2,'奖项名称','示例志愿服务表彰'],
    ['languages',1,2,'成绩','560'],
    ['languages',2,2,'成绩','135'],
  ];
  const plan = makePlan(samples.map(([kind,number,count,label])=>field(label,{record:{kind,number,count}})),demo);
  assert.deepEqual(plan.map(row=>row.value),samples.map(sample=>sample.at(-1)));
  assert(plan.every(row=>row.match && row.confidence==='中'));
  for (const marker of ['本地证明人标记','本地家属标记','本地证件号标记']) {
    assert(!JSON.stringify(demo).includes(marker));
  }
});

test('nested family fields and identity numbers cannot be mapped to personal contact data', () => {
  const {nodes, FakeInput} = mockedDOM();
  const outer = {querySelector:()=>null,getAttribute:key=>key==='aria-label'?'家庭情况':''};
  const inner = {querySelector:()=>({innerText:'第1条'}),getAttribute:()=>'',parentElement:{closest:()=>outer}};
  const name = new FakeInput('姓名');
  const phone = new FakeInput('联系电话',{type:'tel'});
  const identity = new FakeInput('身份证号',{attrs:{'aria-label':'姓名'}});
  for(const input of [name,phone])input.closest=selector=>selector.startsWith('fieldset')?inner:null;
  nodes.push(name,phone,identity);
  const plan=makePlan(inspectPage('scan').fields,profile);
  assert.equal(plan.length,3);
  assert(plan.every(row=>!row.match));
});
