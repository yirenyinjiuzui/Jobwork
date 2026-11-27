import assert from 'node:assert/strict';
import {test} from 'node:test';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {loadProfile,describeKey,describeRecord,makePlan,keptComparisons,textSuggestions} from '../extension/matcher.mjs';
import {inspectPage} from '../extension/page.mjs';
import {buildReviewCards,reviewFieldLabel} from '../extension/review-cards.mjs';
import {cleanDraft,inspectJobPage,makeCaptureLink} from '../extension/capture.mjs';

function harness(fields=[{index:0,type:'text',label:'姓名',token:'metadata-only',maxLength:-1}]){
  class El{
    constructor(){this.handlers={};this.children=[];this.checked=false;this.disabled=false;this.value='8765';this.validity={valid:true};this.classList={toggle(){}};}
    addEventListener(k,v){this.handlers[k]=v;}
    append(...c){this.children.push(...c);}
    replaceChildren(...c){this.children=c;}
    set textContent(v){this.text=String(v);}
    get textContent(){return this.text||'';}
  }
  const ids=new Map();const el=id=>{if(!ids.has(id))ids.set(id,new El());return ids.get(id);};
  let active={id:41,url:'http://localhost:8765/jobs/A'};
  const events={activated:[],updated:[]};const calls=[];
  let fillResult={filled:1,skipped:[]};let beforeQuery;
  const chrome={tabs:{query:async()=>{if(beforeQuery){const fn=beforeQuery;beforeQuery=undefined;fn();}return[active];},
    onActivated:{addListener:fn=>events.activated.push(fn)},onUpdated:{addListener:fn=>events.updated.push(fn)},create:async()=>{}},
    scripting:{executeScript:async args=>{calls.push(args);return[{result:args.args[0].startsWith('scan')?{
      url:active.url,host:'localhost:8765',session:'fictional-one-use-session',fields
    }:fillResult}];}}};
  const context={document:{getElementById:el,createElement:()=>new El()},chrome,URL,loadProfile,describeKey,describeRecord,makePlan,keptComparisons,textSuggestions,inspectPage,buildReviewCards,reviewFieldLabel,cleanDraft,inspectJobPage,makeCaptureLink};
  vm.createContext(context);
  vm.runInContext(readFileSync(new URL('../extension/popup.mjs',import.meta.url),'utf8').replace(/^import .*;\n/gm,''),context);
  const activate=id=>{active={...active,id};for(const fn of events.activated)fn({tabId:id});};
  return {el,calls,activate,events,setActive:x=>{active=x;},result:x=>{fillResult=x;},onNextQuery:fn=>{beforeQuery=fn;},
    async preview(scanId='scan',profile={full_name:'Fictional Candidate'}){const file={size:70,text:async()=>JSON.stringify(profile)};const target={files:[file]};await el('profile').handlers.change({target});await el(scanId).handlers.click();},
    confirm:()=>{el('confirm').checked=true;el('confirm').handlers.change();},
    fill:()=>el('fill').handlers.click()};
}
test('preview counts track selection and reset on a fresh scan', async () => {
  const h=harness();
  await h.preview();
  assert.equal(h.el('message').textContent,'已选 1 / 1 项');
  const review=h.el('plan').children.find(child=>child.className==='review-scroll');
  const [group]=review.children[0].children;
  const [,record]=group.children;
  const [check]=record.children[0].children;
  check.checked=false;
  check.handlers.change();
  assert.equal(h.el('message').textContent,'已选 0 / 1 项');
  await h.el('scan').handlers.click();
  assert.equal(h.el('message').textContent,'已选 1 / 1 项');
  assert.equal(h.el('confirm').checked,false);
  assert.equal(h.el('fill').disabled,true);
  assert.deepEqual(h.calls.map(call=>call.args[0]),['scan','scan']);
});
test('preview separates existing content from other skipped fields', async () => {
  const h=harness([{type:'text',label:'身份证号'},{type:'text',label:'姓名',hasValue:true}]);
  await h.preview();
  const groups=h.el('plan').children.filter(child=>child.className==='skipped-fields');
  assert.deepEqual(groups.map(group=>group.children[0].textContent),['保留网页已有内容（1 项）','其他跳过字段（1 项）']);
  assert.equal(groups[0].children[1].children[0].textContent,'姓名');
  assert.match(groups[1].children[1].children[0].textContent,/身份证号：.+/);
  assert.equal(h.el('actions').hidden,true);
  assert.equal(h.el('fill').disabled,true);
});
test('popup forwards document session with approved fields and clears confirmation',async()=>{
  const h=harness();await h.preview();h.confirm();await h.fill();
  assert.equal(h.calls.length,2);
  assert.equal(h.calls[1].target.tabId,41);
  assert.equal(h.calls[1].args[2],'http://localhost:8765/jobs/A');
  assert.equal(h.calls[1].args[3],'fictional-one-use-session');
  assert.equal(h.el('confirm').checked,false);assert.equal(h.el('fill').disabled,true);
});
test('select all only checks eligible rows and never grants fill consent', async () => {
  const fields=['工作单位','工作岗位','证明人'].map((label,index)=>({
    index,label,type:'text',token:String(index),record:{kind:'work_experience',number:1,count:1},
  }));
  const h=harness(fields);
  await h.preview('scan',{resume_details:{work_experience:[{company:'示例单位',role:'示例岗位'}]}});
  const all=h.el('selectAll');
  assert.equal(all.hidden,false);
  all.handlers.click();
  assert.equal(h.el('message').textContent,'已选 2 / 2 项');
  assert.equal(all.disabled,true);
  assert.equal(h.el('fill').disabled,true);
  h.confirm();
  const review=h.el('plan').children.find(child=>child.className==='review-scroll');
  const [group]=review.children[0].children;
  const [,record]=group.children;
  const check=record.children[1].children[0];
  check.checked=false;
  check.handlers.change();
  assert.equal(h.el('message').textContent,'已选 1 / 2 项');
  assert.equal(all.disabled,false);
  assert.equal(h.el('fill').disabled,true);
  h.confirm();
  all.handlers.click();
  assert.equal(h.el('confirm').checked,false);
  h.confirm();await h.fill();
  assert.deepEqual(Array.from(h.calls[1].args[1],row=>row.index),[0,1]);
});
test('grouped preview displays each work record and retains per-field confirmation',async()=>{
  const h=harness([1,2].map(number=>({
    index:number,type:'text',label:'工作单位',token:'work-'+number,record:{kind:'work_experience',number,count:2},
  })));
  await h.preview('scan',{resume_details:{work_experience:[{company:'示例单位甲'},{company:'示例单位乙'}]}});
  const group=h.el('plan').children.find(child=>child.className==='review-scroll').children[0].children[0];
  const [title,first,second]=group.children;
  assert.equal(title.children[0].textContent,'工作经历');
  assert.equal(first.children[0].textContent,'第 1 条');
  assert.equal(second.children[0].textContent,'第 2 条');
  assert.equal(first.children[1].children[2].textContent,'示例单位甲');
  assert.equal(second.children[1].children[2].textContent,'示例单位乙');
  h.confirm();await h.fill();
  assert.equal(h.calls.length,1);
  const check=second.children[1].children[0];
  check.checked=true;check.handlers.change();
  assert.equal(h.el('confirm').checked,false);
  h.confirm();await h.fill();
  assert.deepEqual(Array.from(h.calls[1].args[1],choice=>choice.value),['示例单位乙']);
});
test('focused scan requires a separate confirmation before forwarding one field', async () => {
  const h = harness();
  await h.preview('scanFocused');
  assert.deepEqual(Array.from(h.calls[0].args), ['scan-focused']);
  assert.equal(h.el('fill').disabled, true);
  await h.fill();
  assert.equal(h.calls.length, 1);
  h.confirm();
  await h.fill();
  assert.equal(h.calls[1].args[0], 'fill');
  assert.equal(h.calls[1].args[1].length, 1);
});
test('same-origin different URL or another active tab never receives fill injection',async()=>{
  for(const active of [{id:41,url:'http://localhost:8765/jobs/B'},{id:42,url:'http://localhost:8765/jobs/A'}]){
    const h=harness();await h.preview();h.confirm();h.setActive(active);await h.fill();
    assert.equal(h.calls.length,1);assert.match(h.el('message').textContent,/重新扫描/);
  }
});
test('switching away and back or same-URL reload invalidates retained popup preview',async()=>{
  for(const action of [h=>{h.activate(42);h.activate(41);},h=>h.events.updated.forEach(fn=>fn(41,{status:'loading'}))]){
    const h=harness();await h.preview();h.confirm();action(h);await h.fill();
    assert.equal(h.calls.length,1);assert.equal(h.el('fill').disabled,true);
  }
});
test('tab events while awaiting final query cannot revive a captured old plan',async()=>{
  const h=harness();await h.preview();h.confirm();h.onNextQuery(()=>{h.activate(42);h.activate(41);});await h.fill();
  assert.equal(h.calls.length,1);assert.match(h.el('message').textContent,/重新扫描/);
});
test('page rejection and partial stop require rescanning without silently retrying',async()=>{
  for(const result of [{error:'页面已变更，请重新扫描。'},{filled:1,skipped:[1],stopped:true}]){
    const h=harness();await h.preview();h.confirm();h.result(result);await h.fill();
    assert.match(h.el('message').textContent,/重新扫描/);assert.equal(h.el('confirm').checked,false);
    await h.fill();assert.equal(h.calls.length,2);
    if(result.stopped)assert.match(h.el('message').textContent,/已填入 1 项.*其余停填/);
  }
});
