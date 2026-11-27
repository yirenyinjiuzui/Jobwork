import { loadProfile, describeKey, describeRecord, makePlan, textSuggestions } from './matcher.mjs';
import { inspectPage } from './page.mjs';
import { buildReviewCards, reviewFieldLabel } from './review-cards.mjs';
import { cleanDraft, inspectJobPage, makeCaptureLink } from './capture.mjs';

const $ = x => document.getElementById(x);
let profile = Object.create(null);
let preview;
let busy = false;

function notify(el, text = '', error = false) {
  el.textContent = text;
  el.classList.toggle('error', error);
}
function clearPlan() {
  preview = undefined;
  $('previewTarget').textContent = '';
  $('plan').replaceChildren();
  $('confirm').checked = false;
  $('actions').hidden = true;
  $('fill').disabled = true;
}
function update() {
  const ready = Object.keys(profile).length > 0 && !busy;
  $('scan').disabled = !ready;
  $('scanFocused').disabled = !ready;
  $('suggest').disabled = !ready;
  $('fill').disabled = busy || !preview || !$('confirm').checked || !preview.rows.some(x => x.check.checked);
}
function elem(tag, text, className) {
  const el = document.createElement(tag);
  if (text) el.textContent = text;
  if (className) el.className = className;
  return el;
}
const fieldLabel = f => (f.record ? describeRecord(f.record) + ' · ' : '') +
  reviewFieldLabel(f);
function showSelectionCount() {
  const selected = preview.rows.filter(row => row.check.checked).length;
  notify($('message'), '已选 ' + selected + ' / ' + preview.rows.length + ' 项');
}
function drawPlan(plan) {
  const container = $('plan');
  $('previewTarget').textContent = '目标网页：' + preview.host + new URL(preview.url).pathname;
  const matches = plan.filter(row => row.match);
  const skipped = plan.filter(row => !row.match);
  if (matches.length) {
    const cards = buildReviewCards(document, matches, (m, check) => {
      check.checked = m.confidence === '高';
      check.addEventListener('change', () => {
        $('confirm').checked = false;
        showSelectionCount();
        update();
      });
      preview.rows.push({ check, m });
    });
    const review = elem('div', '', 'review-scroll');
    review.append(cards);
    container.append(review);
    $('actions').hidden = false;
  } else {
    container.append(elem('p', '没有可以安全填写的字段。你可以在下方尝试文字建议，或返回网页手填。'));
  }
  const kept = skipped.filter(row => row.field.hasValue);
  const other = skipped.filter(row => !row.field.hasValue);
  const otherTitle = kept.length ? '其他跳过字段' : '跳过的字段';
  for (const [title, rows] of [['保留网页已有内容', kept], [otherTitle, other]]) {
    if (!rows.length) continue;
    const extra = elem('details');
    extra.className = 'skipped-fields';
    extra.append(elem('summary', title + '（' + rows.length + ' 项）'));
    const details = elem('div', '', 'rows');
    for (const { field, reason } of rows) {
      const text = reason === '已有内容，不覆盖' ? fieldLabel(field) : fieldLabel(field) + '：' + reason;
      details.append(elem('div', text, 'manual'));
    }
    extra.append(details);
    container.append(extra);
  }
}

$('profile').addEventListener('change', async event => {
  const file = event.target.files?.[0];
  clearPlan();
  notify($('message'));
  $('suggestions').replaceChildren();
  profile = Object.create(null);
  update();
  if (!file) return;
  try {
    if (file.size > 1_000_000) throw new Error('资料文件不能超过 1 MB。');
    const next = loadProfile(JSON.parse(await file.text()));
    if (event.target.files?.[0] !== file) return;
    profile = next;
    const { resume_details, ...basic } = profile;
    const count = Object.values(resume_details || {}).reduce((sum, rows) => sum + rows.length, 0);
    const keys = Object.keys(basic);
    if (!keys.length && !count) throw new Error('未发现可填字段，请从工作台导出或检查资料内容。');
    notify($('profileStatus'), '已载入 ' + keys.length + ' 项常用资料和 ' + count + ' 条经历或证书。');
  } catch (e) { if (event.target.files?.[0] === file) notify($('profileStatus'), e.name === 'SyntaxError' ? '无法读取此 JSON 文件。' : e.message, true); }
  finally { update(); }
});

async function runOnTab(tabId, args) {
  const result = await chrome.scripting.executeScript({
    target: { tabId, allFrames: false }, func: inspectPage, args,
  });
  const payload = result[0]?.result;
  if (!payload) throw new Error('此网页没有返回表单信息。请在可信的招聘网页打开扩展。');
  if (payload.error) throw new Error(payload.error);
  return payload;
}
async function scan(mode) {
  if (busy || !Object.keys(profile).length) return;
  clearPlan(); busy = true; update();
  notify($('message'), '正在检查当前网页…');
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || typeof tab.id !== 'number') throw new Error('未找到浏览器标签页。');
    const payload = await runOnTab(tab.id, [mode]);
    preview = { tabId: tab.id, url: payload.url, host: payload.host, session: payload.session, rows: [] };
    drawPlan(makePlan(payload.fields, profile));
    if (preview.rows.length) showSelectionCount();
    else notify($('message'));
  } catch (e) { notify($('message'), '未扫描：' + e.message, true); }
  finally { busy = false; update(); }
}
$('scan').addEventListener('click', () => scan('scan'));
$('scanFocused').addEventListener('click', () => scan('scan-focused'));
function invalidatePreview() {
  if (!preview) return;
  clearPlan();
  notify($('message'), '标签页或网页已改变，请重新扫描。', true);
  update();
}
chrome.tabs.onActivated.addListener(({tabId}) => { if (preview && preview.tabId !== tabId) invalidatePreview(); });
chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (preview?.tabId === tabId && (change.status === 'loading' || change.url && change.url !== preview.url)) invalidatePreview();
});
$('confirm').addEventListener('change', update);
$('fill').addEventListener('click', async () => {
  const p = preview;
  if (!p || !$('confirm').checked || busy) return;
  const choices = p.rows.filter(x => x.check.checked).map(({ m }) =>
    ({ index: m.field.index, token: m.field.token, value: m.value, ...(m.optionIndex!==undefined && {optionIndex:m.optionIndex}) }));
  if (!choices.length) return;
  busy = true; update();
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (preview !== p || tab?.id !== p.tabId || tab.url !== p.url) throw new Error('当前网页已改变，请重新扫描。');
    const result = await runOnTab(p.tabId, ['fill', choices, p.url, p.session]);
    notify($('message'), '已填入 ' + result.filled + ' 项。' +
      (result.stopped ? '页面或表单已改变，其余停填。请重新扫描；已填内容请先核对。' : result.skipped.length ? '另有 ' + result.skipped.length + ' 项未写入，请重新扫描。' : '') +
      ' 请回到网页核对后自行提交。');
  } catch (e) { notify($('message'), '填写未确认：' + e.message + '。请检查网页实际内容。', true); }
  finally { clearPlan(); busy = false; update(); }
});
$('suggest').addEventListener('click', () => {
  const container = $('suggestions');
  container.replaceChildren();
  const rows = textSuggestions($('fallback').value.slice(0, 5000), profile);
  if (!rows.length) container.append(elem('p', '请先粘贴字段文本。'));
  for (const r of rows) {
    container.append(elem('div', r.label + '：' + (r.match ? describeKey(r.key) + ' → ' + r.value : '手动核对（' + r.reason + '）'), 'manual'));
  }
});

let capture;
let captureBusy = false;
const jobLabels = {
  company: '公司', title: '岗位', requisition: '岗位编号', location: '地点',
  description: '地点原文摘录（请核对）', career_type: '类型', deadline: '截止', url: '来源地址', eligibility: '资格要求', start: '到岗时间',
};
const jobTypes = {intern:'实习',graduate:'校招 / 应届',other:'其他 / 待确认'};
function updateCapture() {
  $('captureScan').disabled = captureBusy;
  $('captureOpen').disabled = captureBusy || !capture || !$('capturePort').validity.valid ||
    !/^\d{4,5}$/u.test($('capturePort').value);
}
$('capturePort').addEventListener('input', updateCapture);
$('captureScan').addEventListener('click', async () => {
  capture = undefined;
  captureBusy = true;
  $('capturePreview').replaceChildren();
  $('captureActions').hidden = true;
  notify($('captureStatus'), '正在识别公开岗位字段…');
  updateCapture();
  try {
    const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (typeof active?.id !== 'number') throw new Error('未找到当前标签页。');
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: active.id, allFrames: false }, func: inspectJobPage,
    });
    const value = result?.result;
    if (!value || value.error) throw new Error(value?.error || '没有可读取的岗位。');
    const data = cleanDraft(value.draft, value.retainPublicId);
    if (!data) throw new Error('没有通过校验的公开岗位链接或标题。');
    capture = { data, retainPublicId: value.retainPublicId };
    const dl = elem('dl', '', 'capture-rows');
    for (const [key, label] of Object.entries(jobLabels)) {
      dl.append(elem('dt', label), elem('dd', key==='career_type' ? jobTypes[data[key]] : (data[key] || '待补充')));
    }
    $('capturePreview').append(dl);
    $('captureActions').hidden = false;
    notify($('captureStatus'), '来源：' + value.source + '。只会把上述内容送入本机待核对表单。');
  } catch (e) { notify($('captureStatus'), '未识别：' + e.message, true); }
  finally { captureBusy = false; updateCapture(); }
});
$('captureOpen').addEventListener('click', async () => {
  if (!capture || captureBusy) return;
  captureBusy = true;
  updateCapture();
  try {
    const url = makeCaptureLink($('capturePort').value, capture.data, capture.retainPublicId);
    await chrome.tabs.create({ url, active: true });
  } catch (e) { notify($('captureStatus'), '未打开：' + e.message, true); }
  finally { captureBusy = false; updateCapture(); }
});
