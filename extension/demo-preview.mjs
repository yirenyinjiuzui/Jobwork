import { inspectPage } from './page.mjs';
import { loadProfile, makePlan } from './matcher.mjs';
import { buildReviewCards } from './review-cards.mjs';

const kinds = new Set(['work_experience', 'campus_experience', 'awards', 'languages']);

async function showPreview(dropdowns) {
  const panel = document.getElementById('demo-review');
  const status = document.getElementById('demo-review-status');
  document.title = '分条填表预览 · 求职工作台';
  try {
    const response = await fetch('./demo-profile.json');
    if (!response.ok) throw new Error('暂时无法读取本地演示资料。');
    const profile = loadProfile(await response.json());
    const scan = inspectPage('scan');
    if (scan.error) throw new Error(scan.error);

    const plan = makePlan(scan.fields, profile);
    const rows = plan.filter(row => row.match && (dropdowns ? row.field.type==='select' : kinds.has(row.field.record?.kind)));
    const controls = Array.from(document.querySelectorAll('input,textarea,select'));
    const manual = plan.filter(row => ['identity_number', 'family_name', 'family_phone', 'award2_issuer', 'work_permit']
      .includes(row.field.name));
    if (rows.some(row => controls[row.field.index].value !== '') || manual.some(row => row.match)) {
      throw new Error('目标或手动字段已变更，请重新打开本地练习。');
    }
    if (dropdowns) {
      document.title='下拉选项预览 · 求职工作台';
      document.getElementById('demo-review-title').textContent='下拉选项预览';
      status.textContent=rows.length+' 项匹配 · 网页选项均待确认';
      document.getElementById('demo-review-manual').textContent='此页展示拟选值。填写前请在浏览器工具栏核对本次预览。';
    } else {
      const records = new Set(rows.map(({ field }) => field.record.kind + '/' + field.record.number));
      status.textContent = records.size + ' 条记录 · ' + rows.length + ' 个拟填字段';
    }
    document.getElementById('demo-review-cards').replaceChildren(buildReviewCards(document, rows));
    document.getElementById('demo-review-manual').hidden = !manual.length;
    document.getElementById('demo-practice').hidden = true;
  } catch (error) {
    status.textContent = error.message;
  }
  panel.hidden = false;
}

const preview=new URLSearchParams(location.search).get('preview');
if (preview==='1' || preview==='select') showPreview(preview==='select');
