// This function is serialized by chrome.scripting.executeScript. Keep it self-contained.
export function inspectPage(mode, approved = [], expectedUrl = '', expectedSession = '') {
  // This global belongs to this extension's ISOLATED world, not the website.
  // Retain only node references and metadata; never profile values or value hashes.
  const slot = '__jobWorkbenchFormPreviewV113';
  const discard = () => {
    const old = globalThis[slot];
    old?.observer.disconnect();
    if (old) old.document.removeEventListener('visibilitychange', old.onVisibility);
    clearTimeout(old?.timer);
    delete globalThis[slot];
  };
  const reject = message => { discard(); return { error: message }; };
  const scanning = mode === 'scan' || mode === 'scan-focused';
  if (scanning) discard();

  if (!/^https?:$/u.test(location.protocol) ||
      (location.protocol === 'http:' && !['localhost', '127.0.0.1'].includes(location.hostname))) {
    return reject('仅支持 HTTPS 网页和本地练习表单。');
  }
  // Stop on authentication and payment paths. Only name/label metadata is read on ordinary forms.
  if (/(?:^|[/_-])(?:log-?in|sign-?in|sign-?up|register|identity|captcha|reset-password|checkout|payment)(?:$|[/_?.-])/iu.test(location.pathname)) {
    return reject('登录、认证和支付页面不支持辅助填表。');
  }
  if (expectedUrl && location.href !== expectedUrl) return reject('网页已变更，请重新扫描。');
  const session = globalThis[slot];
  const changed = () => !session || session.document !== document || session.url !== location.href ||
    (session.focused && document.activeElement !== session.focused) ||
    document.visibilityState === 'hidden' || session.invalid || Date.now() > session.expires || session.observer.takeRecords().length > 0;
  if (mode === 'fill' && (!expectedSession || session?.id !== expectedSession || changed())) {
    return reject('页面、岗位或预览已变更／失效，请重新扫描。');
  }
  const typeSet = new Set(['text', 'email', 'tel', 'url', 'textarea']);
  const plain = (s, max = 130) => String(s || '').trim().replace(/\s+/gu, ' ').slice(0, max);
  const byRef = node => plain((node.getAttribute('aria-labelledby') || '').split(/\s+/u).filter(Boolean)
    .map(id => document.getElementById(id)?.textContent || '').join(' '));
  const labelsOf = node => plain(Array.from(node.labels || []).map(label => {
    if (node.tagName !== 'SELECT' || !label.contains?.(node)) return label.innerText || label.textContent || '';
    const copy = label.cloneNode(true);
    copy.querySelectorAll('select').forEach(child => child.remove());
    return copy.textContent;
  }).join(' '));
  const authContexts = new Set([...document.querySelectorAll('input[type="password"], input[autocomplete="one-time-code"], input[autocomplete="current-password"], input[autocomplete="new-password"]')]
    .filter(n => n.getClientRects().length > 0).map(n => n.form || document.body));
  if (authContexts.has(document.body)) return reject('网页显示登录或验证控件，请手动处理。');
  const isVisible = node => {
    if (!node.getClientRects().length || node.closest('[aria-hidden="true"], [hidden], [inert]')) return false;
    const s = getComputedStyle(node);
    return s.visibility === 'visible' && s.display !== 'none' && s.opacity !== '0' && node.offsetWidth > 0 && node.offsetHeight > 0;
  };
  const adjacentLabel = node => {
    const label = node.previousElementSibling;
    // Some layouts render an unbound label beside a single control.
    if (label?.tagName !== 'LABEL' || label.hasAttribute('for') || !isVisible(label) ||
        node.parentElement.querySelectorAll('input:not([type="hidden"]),textarea,select,[contenteditable]').length !== 1) return '';
    return plain(label.innerText);
  };
  const hints = node => {
    const label = labelsOf(node);
    const aria = plain(node.getAttribute('aria-label')) || byRef(node);
    return { label, aria, adjacent: label || aria ? '' : adjacentLabel(node) };
  };
  const recordSelector = 'fieldset,[role="group"],section[aria-label],section[aria-labelledby]';
  function* groupsOf(node) {
    for (let group = node.closest(recordSelector); group; group = group.parentElement?.closest(recordSelector)) yield group;
  }
  const groupTitle = group => plain(group.querySelector(':scope > legend')?.innerText ||
    group.getAttribute('aria-label') || byRef(group)).normalize('NFKC');
  const contextOf = node => {
    const form = node.form;
    let context = '';
    if (form) {
      const action = form.getAttribute('action');
      let actionHint = '';
      try {
        if (action) {
          const target = new URL(action, location.href);
          actionHint = target.origin === location.origin ? target.pathname : 'external form action';
        }
      } catch { actionHint = 'external form action'; }
      context = plain([
        actionHint, form.getAttribute('name'), form.id, form.getAttribute('aria-label'), byRef(form)
      ].filter(Boolean).join(' '), 200);
    }
    const titles = Array.from(groupsOf(node), groupTitle);
    if (titles[0]) context += ' ' + titles[0];
    if (titles.some(title => /家庭(?:情况|成员|资料|信息|关系)|家属|亲属(?:资料|信息|关系)|父亲|母亲|配偶|监护人/u.test(title))) {
      context += ' 家庭资料';
    }
    return context;
  };
  const recordNames = {
    教育经历: 'education', 教育背景: 'education', 教育信息: 'education',
    实习经历: 'internships', 实习信息: 'internships',
    工作经历: 'work_experience', 工作经验: 'work_experience', 工作信息: 'work_experience',
    项目经历: 'projects', 项目信息: 'projects',
    校园经历: 'campus_experience', 校园与学生干部经历: 'campus_experience',
    校园实践: 'campus_experience', 校内实践经历: 'campus_experience', 学生干部经历: 'campus_experience',
    获奖经历: 'awards', 获奖与荣誉: 'awards', 获奖情况: 'awards', 荣誉奖励: 'awards', 获奖记录: 'awards',
    资格证书: 'certificates', 证书: 'certificates', 证书信息: 'certificates',
    外语能力: 'languages', 外语水平: 'languages', 外语经历: 'languages', 语言能力: 'languages',
  };
  const recordOf = node => {
    let numberedRow;
    for (const group of groupsOf(node)) {
      const title = groupTitle(group);
      const numbered = title.match(/^(.*?)\s*[(（]?(?:第\s*)?(\d{1,2})\s*(?:条|段)?[)）]?$/u);
      const base = numbered ? numbered[1].trim() : title;
      if (Object.hasOwn(recordNames, base)) {
        return { kind: recordNames[base], ...(numberedRow || { element: group, position: numbered ? Number(numbered[2]) : null }) };
      }
      if (numbered && (!base || base === '记录') && !numberedRow) numberedRow = { element: group, position: Number(numbered[2]) };
    }
  };
  const focused = mode === 'scan-focused' ? document.activeElement : session?.focused;
  const dropdown = node => node?.tagName === 'SELECT' && !node.multiple && node.size <= 1;
  const placeholder = option => !option || /^(?:[-—\s]*请(?:选择|选取)(?:性别|学历|政治面貌)?[-—\s]*|[-—\s]*(?:please select|select an option)[-—\s]*)$/iu.test(option.label.trim()) || (!option.value && !option.label.trim());
  const available = option => !placeholder(option) && option.value !== '' && !option.disabled && !option.hidden &&
    !option.closest('optgroup[disabled], optgroup[hidden], [aria-hidden="true"], [aria-disabled="true"]') &&
    getComputedStyle(option).display !== 'none';
  if (mode === 'scan-focused' && (!focused || !(dropdown(focused) ||
      (typeSet.has(focused.type) && ['INPUT', 'TEXTAREA'].includes(focused.tagName))) || !isVisible(focused))) {
    return reject('请先点击要识别的输入框或下拉框，再打开扩展。');
  }
  const candidates = focused ? [focused] : document.querySelectorAll('input,textarea,select');
  const nodes = Array.from(candidates).slice(0, 600);
  const fieldMap = new Map();
  const records = new Map();
  for (const [index, node] of nodes.entries()) {
    if (!isVisible(node)) continue;
    const type = node.tagName === 'TEXTAREA' ? 'textarea' : node.tagName === 'SELECT' ? 'select' : node.type;
    if (type === 'hidden' || type === 'password') continue;
    const form = node.form;
    const context = contextOf(node);
    const record = recordOf(node);
    if (record) {
      if (!records.has(record.kind)) records.set(record.kind, { rows: new Map(), forms: new Set() });
      const group = records.get(record.kind);
      group.rows.set(record.element, record.position);
      group.forms.add(form);
    }
    const labels = hints(node);
    const field = {
      index, type, ...labels,
      placeholder: plain(node.getAttribute('placeholder')), name: plain(node.name), id: plain(node.id),
      autocomplete: plain(node.getAttribute('autocomplete')), context,
      disabled: node.matches(':disabled') || node.getAttribute('aria-disabled')==='true',
      readonly: node.readOnly || node.getAttribute('aria-readonly')==='true',
      hasValue: type==='select' ? !placeholder(node.options[node.selectedIndex]) : !!node.value && (typeSet.has(type) || type === 'month'),
      maxLength: node.maxLength || 0, auth: authContexts.has(form),
    };
    if (dropdown(node) && node.options.length<=200 && !field.hasValue && !field.auth &&
        !/家庭|家属|亲属|证明人|监护人|父亲|母亲|配偶|family|guardian|reference/iu.test(context) &&
        Object.values(labels).some(s=>/^(本人性别|性别|gender|(?:本人)?政治面貌|political status|(?:最高)?学历|学历层次|(?:highest )?education level)$/iu.test(
          s.normalize('NFKC').replace(/[:：*＊]|\(必填\)|\(required\)/giu,'').trim()))) {
      const options=Array.from(node.options);
      const values=new Set(), duplicates=new Set();
      for (const option of options) {
        if (values.has(option.value)) duplicates.add(option.value);
        values.add(option.value);
      }
      field.options=options.flatMap((option,index)=>
        !duplicates.has(option.value) && available(option) && option.label.length<=100 ? [{index,label:option.label.trim()}] : []);
    }
    fieldMap.set(index, { field, node, record });
  }
  const groupOrder = new Map([...records].map(([kind, { rows, forms }]) => [kind, {
    numbers: new Map([...rows.keys()].map((row, index) => [row, index + 1])),
    uncertain: forms.size > 1 || [...rows.values()].some((position, index) => position !== null && position !== index + 1),
  }]));
  for (const { field, record } of fieldMap.values()) {
    if (record) {
      const { numbers, uncertain } = groupOrder.get(record.kind);
      field.record = {
        kind: record.kind, number: numbers.get(record.element), count: numbers.size,
        uncertain: !!focused || candidates.length > 600 || fieldMap.size > 120 || uncertain,
      };
    }
    // Reject form filling if these facts differ between preview and insertion.
    field.token = JSON.stringify([
      field.index, field.type, field.label, field.aria, field.adjacent, field.placeholder, field.name, field.id,
      field.autocomplete, field.context, field.maxLength, !!field.auth, field.record, field.options,
    ]);
  }

  if (scanning) {
    const state = { id: crypto.randomUUID(), document, url: location.href, invalid: false, focused,
      expires: Date.now() + 120000,
      bindings: new Map([...fieldMap].map(([index, row]) => [index, {
        node: row.node, form: row.node.form, token: row.field.token, ...(row.record && { record: row.record.element }),
        ...(row.field.options && { options:new Map(row.field.options.map(({index})=>{
          const option=row.node.options[index];return [index,{option,value:option.value}];
        })) }),
      }])) };
    if (document.visibilityState === 'hidden') return reject('当前标签页不可见，请回到原页面重新扫描。');
    state.onVisibility = () => { if (document.visibilityState === 'hidden') state.invalid = true; };
    document.addEventListener('visibilitychange', state.onVisibility);
    state.observer = new MutationObserver(() => { state.invalid = true; });
    // No page snapshot or text is collected. Any DOM mutation invalidates the
    // preview conservatively, including same-URL SPA job/form replacements.
    state.observer.observe(document.documentElement, { subtree: true, childList: true, characterData: true, attributes: true });
    state.timer = setTimeout(() => { if (globalThis[slot] === state) discard(); }, 120000);
    state.timer?.unref?.(); // Node test runner only; browser timers are numbers.
    globalThis[slot] = state;
    return { fields: Array.from(fieldMap.values(), row => row.field).slice(0, 120), url: location.href, host: location.host, session: state.id };
  }
  if (mode !== 'fill') return reject('未知操作。');
  const choices = approved.slice(0, 120);
  const valid = choice => {
    const row = fieldMap.get(choice.index), field = row?.field, node = row?.node;
    const bound = session.bindings.get(choice.index);
    if (!field || bound?.node !== node || bound.form !== node.form || bound.token !== choice.token) return false;
    const current = hints(node);
    const month = field.type === 'month' && !!field.record && /^\d{4}-(0[1-9]|1[0-2])$/u.test(choice.value);
    const select = dropdown(node);
    const previous = bound.options?.get(choice.optionIndex);
    const option = select && node.options[choice.optionIndex];
    if (select && (!previous || previous.option!==option || option.value!==previous.value ||
        option.label.trim()!==choice.value || !available(option))) return false;
    return (
      field.token === choice.token && !field.record?.uncertain && bound.record === recordOf(node)?.element &&
      !field.auth && (typeSet.has(field.type) || month || select) && node.isConnected && isVisible(node) &&
      (select ? placeholder(node.options[node.selectedIndex]) : !node.value) && !field.disabled && !field.readonly && !node.matches(':disabled') && !node.readOnly &&
      current.label === field.label && current.aria === field.aria && current.adjacent === field.adjacent &&
      node.type === (select ? 'select-one' : field.type) &&
      plain(node.getAttribute('placeholder')) === field.placeholder && plain(node.name) === field.name &&
      plain(node.id) === field.id && contextOf(node) === field.context &&
      plain(node.getAttribute('autocomplete')) === field.autocomplete &&
      typeof choice.value === 'string' && choice.value.length <= 5000 &&
      !(node.maxLength > 0 && choice.value.length > node.maxLength)
    );
  };
  // Validate the whole selection before writing anything. Keep the same node
  // references through insertion; never re-query a replacement form to fill it.
  if (changed() || !choices.every(valid)) return reject('目标字段或表单已变更，请重新扫描。');
  delete globalThis[slot]; // Confirmation is one-use, even if a listener changes the page.
  clearTimeout(session.timer);
  let filled = 0;
  const skipped = [];
  try {
    for (const [offset, choice] of choices.entries()) {
      const { field, node } = fieldMap.get(choice.index);
      if (changed() || !valid(choice)) {
        return { filled, skipped: choices.slice(offset).map(x => x.index), stopped: true };
      }
      if (field.type==='select') {
        const option=node.options[choice.optionIndex];
        node.selectedIndex=choice.optionIndex;
        node.dispatchEvent(new Event('input', {bubbles:true, composed:true}));
        if (node.isConnected && node.selectedOptions[0]===option && !changed()) node.dispatchEvent(new Event('change', {bubbles:true}));
        if (node.isConnected && node.selectedOptions[0]===option) filled++; else skipped.push(choice.index);
        continue;
      }
      const proto = field.type === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const set = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
      if (!set) { skipped.push(choice.index); continue; }
      set.call(node, choice.value);
      node.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
      if (node.value === choice.value) filled++; else skipped.push(choice.index);
    }
    return { filled, skipped, ...(changed() ? { stopped: true } : {}) };
  } finally {
    session.observer.disconnect();
    document.removeEventListener('visibilitychange', session.onVisibility);
  }
}
