import assert from 'node:assert/strict';
import { test } from 'node:test';
import { cleanDraft, inspectJobPage, makeCaptureLink, sanitizeJobUrl } from '../extension/capture.mjs';

const posting = {
  '@type': ['Thing','JobPosting'],
  title: 'AI Engineer Intern',
  hiringOrganization: { name: '测试公司' },
  identifier: { name: 'Requisition ID', value: '123456' },
  jobLocation: [
    { address: { addressLocality: '香港', addressRegion: '香港', addressCountry: {name:'HK'} } },
    { name: '深圳' }
  ],
  employmentType: ['INTERN'],
  validThrough: '2026-12-26T23:59:00+08:00',
  jobStartDate: '预计明年春季',
  eligibilityToWorkRequirement: '需要在读身份',
  description: '不得收入脱敏稿的薪资和私人账号',
};
const fakeElement = (value, { meta = false, hidden = false } = {}) => ({
  tagName: meta ? 'META' : 'DIV', textContent: value, innerText: value,
  getAttribute: key => key === 'content' && meta ? value : null,
  getClientRects: () => hidden ? [] : [{}], closest: () => null,
});
function fixture(url, { json = [], heading = '', selectors = {}, pass = false } = {}) {
  globalThis.location = new URL(url);
  globalThis.getComputedStyle = () => ({visibility:'visible'});
  globalThis.document = {
    querySelectorAll: selector => {
      assert.equal(selector, 'script[type="application/ld+json"]');
      return json.map(o=>({textContent:typeof o==='string' ? o : JSON.stringify(o)}));
    },
    querySelector: selector => selector === 'input[type="password"]:not([hidden])' ? pass
      : selector === 'main h1' && heading ? fakeElement(heading)
      : selectors[selector] || null,
  };
}
test('extracts bounded JobPosting fields; excludes raw URL tokens and unrelated description', () => {
  fixture('https://example.com/jobs/123456?session=private&name=personal#form',
    {json:['bad json', {'@graph':[{'@type':'Organization'}, posting]}]});
  const result = inspectJobPage();
  assert.equal(result.source, '网页岗位元数据');
  assert.deepEqual(result.draft, {
    title: 'AI Engineer Intern', company: '测试公司', requisition: '123456',
    location: '香港 · HK / 深圳', description:'', career_type: 'intern', deadline: '2026-12-26T23:59:00+08:00',
    start: '预计明年春季', eligibility: '需要在读身份', url: 'https://example.com/jobs/123456'
  });
  assert.ok(!JSON.stringify(result).includes('session'));
  assert.ok(!JSON.stringify(result).includes('私人账号'));
});
test('preserves only a verified public Greenhouse job key, never referrer secrets', () => {
  fixture('https://example.com/careers?gh_jid=123456&token=private', {json:[posting]});
  const result=inspectJobPage();
  assert.equal(result.retainPublicId,true);
  assert.equal(cleanDraft(result.draft, true).url, 'https://example.com/careers?gh_jid=123456');
  fixture('https://example.com/careers?gh_jid=999999&token=private', {json:[posting]});
  assert.equal(inspectJobPage().retainPublicId,false);
  assert.equal(sanitizeJobUrl('https://example.com/careers?gh_jid=123456', false), 'https://example.com/careers');
});
test('does not capture a list of multiple listings unless its visible primary title chooses exactly one', () => {
  const other = {...posting, title:'Graduate Analyst', employmentType:'FULL_TIME', identifier:'908765'};
  fixture('https://example.com/jobs', {json:[[posting,other]], heading:'Open Positions'});
  assert.match(inspectJobPage().error, /多个/);
  fixture('https://example.com/jobs/908765', {json:[[posting,other]], heading:'Graduate Analyst'});
  assert.equal(inspectJobPage().draft.career_type,'graduate');
});
test('fallback needs visible job detail title and does not misread International as Intern', () => {
  fixture('https://example.com/jobs/now', {heading:'International Engineering',selectors:{'meta[property="og:site_name"]':fakeElement('Example',{meta:true})}});
  assert.equal(inspectJobPage().draft.career_type,'other');
  assert.equal(inspectJobPage().draft.company,'Example');
  fixture('https://example.com/', {heading:'Private name that should not be returned'});
  assert.match(inspectJobPage().error,/岗位/);
});
test('authentication, unsafe schemes and private paths remain manual', () => {
  fixture('https://example.com/jobs/123456', {json:[posting], pass:true});
  assert.match(inspectJobPage().error,/公开/);
  for (const url of [
    'http://example.com/jobs/123',
    'https://example.com/login',
    'https://example.com/verify/secret',
    'https://person@example.com/jobs/123',
    'https://example.com/jobs/personal%40example.com'
  ]) assert.equal(sanitizeJobUrl(url), '', url);
});
test('explicit handoff carries a local encoded JSON with only supported keys', () => {
  const d={company:'示例 & 公司',title:'AI / 云原生 #岗位',url:'https://example.com/jobs/123?session=X#hide',deadline:'2026-02-30',private:'dont forward'};
  const href = new URL(makeCaptureLink('8765',d));
  assert.equal(href.origin,'http://127.0.0.1:8765');
  assert.equal(href.search,'');
  assert.equal(href.hash.split('?')[0],'#discovery');
  const json = JSON.parse(new URLSearchParams(href.hash.split('?')[1]).get('capture'));
  assert.equal(json.company,d.company);
  assert.equal(json.title,d.title);
  assert.equal(json.url,'https://example.com/jobs/123');
  assert.equal(json.deadline,'');
  assert.equal(cleanDraft({...d,deadline:'2026-12-26T23:59:00'}).deadline,'2026-12-26');
  assert.equal(json.private,undefined);
  for (const port of [0,65536,'abc','8765/path','8765@evil.example']) assert.throws(() => makeCaptureLink(port,d));
});

test('bounded location evidence reaches clean draft and handoff without full description or links',()=>{
  const body='Private unrelated salary sentence. The internship is based in Singapore. After graduation the permanent role is in Hong Kong. https://example.invalid/?token=secret';
  fixture('https://example.invalid/jobs/A',{json:[{...posting,jobLocation:{address:{addressLocality:'Hong Kong'}},description:body}]});
  const result=inspectJobPage();
  assert.equal(result.draft.location,'Hong Kong');
  assert.match(result.draft.description,/\[正文:元数据\].*internship is based in Singapore/);
  assert.match(result.draft.description,/After graduation/);
  assert(!result.draft.description.includes('Private unrelated'));assert(!result.draft.description.includes('secret'));
  const forwarded=JSON.parse(new URLSearchParams(new URL(makeCaptureLink(8765,result.draft)).hash.split('?')[1]).get('capture'));
  assert.equal(forwarded.description,result.draft.description);
  assert(forwarded.description.length<=600);
});
test('visible scoped description provides a separately labelled contradiction',()=>{
  fixture('https://example.invalid/jobs/A',{json:[{...posting,description:'The internship is based in Hong Kong.'}],selectors:{'[itemprop="description"]':fakeElement('The internship is based in Singapore. After graduation the permanent role is in Hong Kong.')}});
  const d=inspectJobPage().draft;
  assert.match(d.description,/\[正文:元数据\]/);assert.match(d.description,/\[正文:可见\]/);
  assert.match(d.description,/Singapore/);
});
test('HTML description remains inert, with bounded excerpts and explicit incomplete signal',()=>{
  fixture('https://example.invalid/jobs/A',{json:[{...posting,description:'<script>token=secret</script><img src="https://example.invalid/pixel"><p>The internship is based in Hong Kong.</p><p>Mandatory training in Singapore is required.</p><p>Rotation in Shenzhen.</p><p>Hong Kong recruiting office.</p>'}]});
  const d=inspectJobPage().draft;
  assert(!d.description.includes('secret'));assert(!d.description.includes('<img'));
  assert.match(d.description,/摘录不完整/);assert(d.description.length<=600);
});
