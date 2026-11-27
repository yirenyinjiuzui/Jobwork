// Pure boundary for data transferred from the preview to the local app.
const JOB_KEYS = ['company', 'title', 'requisition', 'location', 'career_type', 'deadline', 'url', 'eligibility', 'start', 'description'];
const TYPES = ['intern','graduate','other'];
const LIMITS = { description: 600, company: 130, title: 160, requisition: 100, location: 160, eligibility: 400, start: 120, url: 600, deadline: 40 };
const strip = (v, n) => typeof v === 'string' ? v.replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/gu,' ').trim().replace(/\s+/gu,' ').slice(0,n) : '';
const sensitivePath = /(?:^|[/_-])(?:log-?in|sign-?in|sign-?up|auth|register|candidate-portal|profile|my-application[s]?|application[s]?|dashboard|privacy|password|captcha|payment|token|invite|reset|verify|checkout)(?:$|[/_?.-])/iu;
export function sanitizeJobUrl(raw, retainPublicId = false) {
  if (typeof raw !== 'string' || raw.length > 2000) return '';
  try {
    const url = new URL(raw);
    const path = decodeURIComponent(url.pathname);
    if (url.protocol !== 'https:' || url.username || url.password || sensitivePath.test(path) || path.includes('@') || path.length > 450) return '';
    const ghId = url.searchParams.get('gh_jid');
    url.search = '';
    url.hash = '';
    // Greenhouse embeds its public numeric job ID in employer career-page links.
    // Keep this one public ID only when it matched JobPosting metadata on this very page.
    if (retainPublicId && /^\d{4,12}$/u.test(ghId || '') && /\/careers?\/?$/iu.test(path)) url.searchParams.set('gh_jid', ghId);
    return url.href.length <= 600 ? url.href : '';
  } catch { return ''; }
}
export function cleanDraft(draft, retainPublicId = false) {
  if (!draft || typeof draft !== 'object') return null;
  const cleaned = Object.fromEntries(JOB_KEYS.map(key => [key, strip(draft[key], LIMITS[key] || 25)]));
  cleaned.url = sanitizeJobUrl(draft.url, retainPublicId);
  if (!cleaned.url || !cleaned.title) return null;
  cleaned.career_type = TYPES.includes(cleaned.career_type) ? cleaned.career_type : 'other';
  const d = cleaned.deadline;
  cleaned.deadline = '';
  if (/^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?(?:Z|[+-]\d{2}:\d{2})?)?$/u.test(d)) {
    const date = new Date(d.slice(0,10) + 'T00:00:00Z');
    if (Number.isFinite(date.getTime()) && date.toISOString().slice(0,10) === d.slice(0,10) && Number.isFinite(new Date(d).getTime())) cleaned.deadline = d.includes('T') && !/(?:Z|[+-]\d{2}:\d{2})$/u.test(d) ? d.slice(0,10) : d;
  }
  return cleaned;
}
export function makeCaptureLink(port, draft, retainPublicId = false) {
  const p = typeof port === 'number' || typeof port === 'string' ? String(port) : '';
  if (!/^\d{1,5}$/u.test(p) || +p < 1024 || +p > 65535) throw new Error('请输入 1024–65535 的本地工作台端口。');
  const cleaned = cleanDraft(draft, retainPublicId);
  if (!cleaned) throw new Error('没有可转交的岗位标题或公开链接。');
  return 'http://127.0.0.1:' + String(Number(p)) + '/#discovery?capture=' + encodeURIComponent(JSON.stringify(cleaned));
}

// Runs in the selected tab's isolated world. Do not use anything outside this function.
export function inspectJobPage() {
  const bounded = (v, n = 180) => typeof v === 'string' ? v.replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/gu,' ').trim().replace(/\s+/gu,' ').slice(0,n) : '';
  if (location.protocol !== 'https:' ||
      /(?:^|[/_-])(?:log-?in|sign-?in|sign-?up|auth|register|candidate-portal|profile|my-application[s]?|application[s]?|dashboard|privacy|password|captcha|payment|token|invite|reset|verify|checkout)(?:$|[/_?.-])/iu.test(location.pathname) ||
      document.querySelector('input[type="password"]:not([hidden])')) {
    return { error: '请在招聘网站的公开岗位详情页使用，不扫描登录或个人申请页。' };
  }

  const visible = element => !!element && element.getClientRects().length > 0 &&
    !element.closest('[hidden],[aria-hidden="true"],[inert]') &&
    getComputedStyle(element).visibility === 'visible';
  const read = selector => {
    const node = document.querySelector(selector);
    if (!node) return '';
    if (node.tagName === 'META') return bounded(node.getAttribute('content'));
    return visible(node) ? bounded(node.innerText || node.textContent) : '';
  };
  const isPosting = data => {
    const types = Array.isArray(data?.['@type']) ? data['@type'] : [data?.['@type']];
    return types.some(x => typeof x === 'string' && /(?:^|schema\.org\/)JobPosting$/iu.test(x));
  };
  const titleOf = data => bounded(data?.title || data?.name, 160);
  const identifierOf = data => {
    const v = data?.identifier;
    const raw = typeof v === 'string' || typeof v === 'number' ? v : v?.value;
    return typeof raw === 'number' && Number.isSafeInteger(raw) ? String(raw) : bounded(raw,100);
  };
  const jobs = [];
  let inspected = 0;
  const traverse = (value, level = 0) => {
    if (!value || typeof value !== 'object' || level > 4 || ++inspected > 180) return;
    if (Array.isArray(value)) { value.slice(0,45).forEach(v => traverse(v, level + 1)); return; }
    if (isPosting(value) && titleOf(value)) jobs.push(value);
    for (const key of ['@graph','mainEntity','itemListElement','item']) if (key in value) traverse(value[key],level+1);
  };
  for (const script of [...document.querySelectorAll('script[type="application/ld+json"]')].slice(0,24)) {
    const raw = script.textContent || '';
    if (!raw || raw.length > 125000) continue;
    try { traverse(JSON.parse(raw)); } catch { /* Invalid schema never blocks visible fallback. */ }
  }
  const visibleTitle = read('main h1') || read('[role="main"] h1') || read('h1');
  const same = (a,b) => bounded(a).normalize('NFKC').toLowerCase() === bounded(b).normalize('NFKC').toLowerCase();
  const unique = new Map();
  for (const job of jobs) {
    const key = identifierOf(job) || titleOf(job).toLowerCase() + '|' + bounded(job.hiringOrganization?.name).toLowerCase();
    if (!unique.has(key)) unique.set(key, job);
  }
  const values = [...unique.values()];
  let selected;
  if (values.length === 1) selected = values[0];
  else if (values.length > 1) {
    const exact = values.filter(v => same(titleOf(v), visibleTitle));
    if (exact.length !== 1) return { error: '此页有多个岗位，无法唯一识别。请先打开单个岗位详情。' };
    [selected] = exact;
  }

  // When structured metadata is absent, only use a visible heading on a detail-looking page.
  const detailLike = /\/(?:jobs?|vacanc(?:y|ies)|positions?|job[-_]detail|careers?|zhiwei)\/[^/]+/iu.test(location.pathname) ||
    /(?:^|\.)jobs\.lever\.co$/iu.test(location.hostname) && location.pathname.split('/').filter(Boolean).length >= 2;
  const genericHeading = /^(jobs|careers|vacancies|open positions|join us|招聘|岗位列表|全部岗位|加入我们|职位搜索|在招职位)$/iu;
  if (!selected && (!detailLike || !visibleTitle || genericHeading.test(visibleTitle))) {
    return { error: '没有找到可核对的单个岗位，请打开岗位详情，或在工作台手动录入。' };
  }

  const tag = selected?.employmentType;
  const title = titleOf(selected) || bounded(visibleTitle,160);
  const desc = ((Array.isArray(tag) ? tag.slice(0,10).map(s=>bounded(s,50)).join(' ') : bounded(tag,100)) + ' ' + title).toLowerCase();
  const career_type = /\bintern(?:s|ship|ships)?\b|实习|實習/u.test(desc) ? 'intern' : /\b(?:new grad(?:uate)?|graduates?)\b|校招|校園招聘|校园招聘|应届|應屆/u.test(desc) ? 'graduate' : 'other';
  const locs = Array.isArray(selected?.jobLocation) ? selected.jobLocation.slice(0,5) : [selected?.jobLocation];
  const locationText = locs.map(entry => {
    const address = entry?.address;
    if (typeof address === 'string') return bounded(address,95);
    const parts = [address?.addressLocality,address?.addressRegion,address?.addressCountry?.name || address?.addressCountry];
    return [...new Set(parts.map(v=>bounded(v,60)).filter(Boolean))].join(' · ') || bounded(entry?.name,95);
  }).filter(Boolean).join(' / ') || (/^TELECOMMUTE$/iu.test(selected?.jobLocationType || '') ? '远程' : read('[itemprop="jobLocation"]'));
  // Transfer only a few relevant sentences, never a whole page or HTML.
  const evidence = [];
  let incomplete = false;
  const addEvidence = (raw, source) => {
    if (typeof raw !== 'string') return;
    if (raw.length > 16000) incomplete = true;
    const text = raw.slice(0,16000).replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/giu,' ')
      .replace(/<[^>]*>/gu,' ').replace(/&nbsp;|&#160;/giu,' ').replace(/&amp;/giu,'&')
      .replace(/(?:https?:\/\/|www\.)[^\s<>]+/giu,'[链接省略]')
      .replace(/\b(?:utm_\w+|token|gclid|fbclid)=[^\s<>]+/giu,'[跟踪参数省略]');
    for (const rawLine of text.split(/(?<=[。；;.!])\s*|\n/u)) {
      const line = bounded(rawLine,1000);
      if (!/hong\s*kong|\bhk\b|香港|实习.{0,30}(?:地点|在|位于)|實習.{0,30}(?:地點|在)|internship.{0,50}(?:based|located|in |at )|training|rotation|培训|培訓|轮岗|輪崗|headquarters|总部|總部/iu.test(line)) continue;
      if (evidence.some(x=>x.endsWith(line))) continue;
      if (evidence.length >= 3) { incomplete = true; continue; }
      evidence.push('[正文:'+source+'] '+line.slice(0,150)+(line.length>150?'…':''));
    }
  };
  addEvidence(selected?.description,'元数据');
  const body = document.querySelector('[itemprop="description"]') || document.querySelector('[data-job-description]') || document.querySelector('.job-description');
  if (visible(body)) addEvidence(body.innerText || body.textContent,'可见');
  const description = evidence.join(' ') + (incomplete?' [摘录不完整]':'');
  const explicitReq = identifierOf(selected);
  const path = location.pathname.replace(/\/$/u,'');
  const atsReq = /^(?:job-boards(?:\.eu)?|boards)\.greenhouse\.io$/iu.test(location.hostname)
    ? /\/jobs\/(\d{4,12})$/u.exec(path)?.[1]
    : /^jobs\.lever\.co$/iu.test(location.hostname)
      ? /^\/[^/]+\/([a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})$/iu.exec(path)?.[1] : '';
  const requisition = explicitReq || atsReq || '';
  const activeId = new URL(location.href).searchParams.get('gh_jid') || '';
  const retainPublicId = Boolean(selected && /^\d{4,12}$/u.test(activeId) && explicitReq === activeId && /\/careers?\/?$/iu.test(location.pathname));
  const company = bounded(selected?.hiringOrganization?.name || selected?.hiringOrganization,130) ||
    read('[itemprop="hiringOrganization"] [itemprop="name"]') || read('[itemprop="hiringOrganization"]') ||
    read('meta[property="og:site_name"]');
  return {
    source: selected ? '网页岗位元数据' : '网页标题（请补充未识别字段）',
    retainPublicId,
    draft: {
      title, company, requisition, career_type, location: locationText, description,
      deadline: bounded(selected?.validThrough || read('meta[itemprop="validThrough"]'),40),
      eligibility: bounded(selected?.eligibilityToWorkRequirement,400),
      start: bounded(selected?.jobStartDate,120),
      url: retainPublicId ? location.origin + location.pathname + '?gh_jid=' + activeId : location.origin + location.pathname,
    },
  };
}
