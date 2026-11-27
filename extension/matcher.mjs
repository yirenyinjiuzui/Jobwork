const FIELDS = {
  full_name: { zh: '姓名', patterns: [/^(full( legal)? name|legal name|applicant name|candidate name|name|姓名|本人姓名|申请人姓名|应聘人姓名|应聘者姓名|中文姓名|法定姓名)$/u] },
  preferred_name: { zh: '常用名', patterns: [/^(preferred name|display name|chosen name|nickname|常用名|昵称|称呼|英文名)$/u] },
  email: { zh: '邮箱', patterns: [/^(e ?mail( address)?|contact e ?mail|邮箱地址|电子邮箱(地址)?|电子邮件地址|电子邮件|联系邮箱|常用邮箱|邮箱)$/u] },
  phone: { zh: '电话', patterns: [/^(phone( number)?|mobile( phone| number)?|cell( phone| number)?|telephone( number)?|contact number|联系电话|联系号码|手机号|手机号码|手机|电话号码|电话)$/u] },
  city: { zh: '所在城市', patterns: [/^(city|current city|city of residence|所在城市|当前城市|现居城市|居住城市)$/u] },
  school: { zh: '学校', patterns: [/^(school( name)?|university( name)?|college( name)?|institution( name)?|educational institution|学校|学校名称|大学|大学名称|就读院校|院校|院校名称|毕业院校)$/u] },
  degree: { zh: '学位', patterns: [/^(degree|degree level|education level|highest degree|highest education level|学位|学历|最高学历|最高学位)$/u] },
  major: { zh: '专业', patterns: [/^(major|field of study|academic major|study major|专业|所学专业|主修|主修专业)$/u] },
  linkedin: { zh: 'LinkedIn', patterns: [/^linkedin( profile)?( url| link)?$/u] },
  github: { zh: 'GitHub', patterns: [/^git ?hub( profile)?( url| link)?$/u] },
  portfolio: { zh: '作品集', patterns: [/^(portfolio( website| url| link)?|personal website|个人网站|个人主页|作品集(链接|网址)?)$/u] },
  project_summary: { zh: '项目简介', patterns: [/^(project summary|project overview|project description|项目简介|项目概述|项目描述)$/u] },
};
const RECORD_NAMES = {
  education: '教育经历', internships: '实习经历', work_experience: '工作经历', projects: '项目经历',
  campus_experience: '校园经历', awards: '获奖经历', certificates: '资格证书', languages: '外语能力',
};
const RECORD_FIELDS = {
  education: {
    school: ['学校', '学校名称', '院校', '就读院校', '毕业院校'], department: ['院系', '学院'],
    major: ['专业', '所学专业'], degree: ['学历或学位', '学历', '学位'],
    start: ['入学年月', '入学时间', '开始年月', '开始时间'], end: ['毕业年月', '毕业时间', '结束年月', '结束时间'],
    grade: ['绩点或排名', '绩点', '专业排名'], description: ['课程与研究方向', '教育经历描述'],
  },
  internships: {
    company: ['实习单位', '实习公司', '单位', '公司名称'], department: ['实习部门', '部门'],
    role: ['实习岗位', '实习职位', '岗位', '职位'], start: ['开始年月', '开始时间', '实习开始时间'],
    end: ['结束年月', '结束时间', '实习结束时间'], description: ['职责与成果', '实习描述', '实习内容'],
  },
  work_experience: {
    company: ['工作单位', '任职单位', '单位名称', '公司名称', '单位', '公司'], department: ['工作部门', '所属部门', '部门'],
    role: ['工作岗位', '工作职位', '岗位', '职位', '职务'], start: ['开始年月', '开始时间', '工作开始时间'],
    end: ['结束年月', '结束时间', '工作结束时间'], description: ['职责与成果', '工作内容', '工作描述', '工作职责'],
  },
  projects: {
    name: ['项目名称'], role: ['担任角色', '项目角色', '项目职务'], start: ['开始年月', '开始时间', '项目开始时间'],
    end: ['结束年月', '结束时间', '项目结束时间'], description: ['项目内容与个人成果', '项目描述', '项目职责'],
  },
  campus_experience: {
    organization: ['组织或活动', '组织名称', '活动名称', '社团名称'],
    role: ['担任职务', '担任角色', '职务', '职位'], start: ['开始年月', '开始时间'],
    end: ['结束年月', '结束时间'], description: ['职责与成果', '活动描述', '本人职责', '实践内容'],
  },
  awards: {
    name: ['奖项名称', '获奖名称', '荣誉名称'], issuer: ['颁发单位', '颁发机构', '授奖单位'],
    date: ['获奖年月', '获奖时间', '获奖日期'], level: ['奖项级别或等次', '奖项级别', '获奖等级', '奖励等级'],
  },
  certificates: {
    name: ['证书名称', '资格证书名称', '资质证书名称'], issuer: ['颁发单位', '发证机构'],
    date: ['取得年月', '取得时间', '获证时间', '发证日期'], level: ['等级或类别', '证书等级', '证书类别'],
  },
  languages: {
    language: ['语种', '语言种类', '外语语种'], qualification: ['考试或证书', '考试名称', '证书名称', '外语考试'],
    score: ['成绩或水平', '成绩', '考试成绩', '外语水平', '掌握程度'],
    date: ['取得年月', '获得年月', '获得时间', '考试年月'],
  },
};
const RECORD_MONTHS = new Set(['start', 'end', 'date']);
const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/u;

const MANUAL = /password|passcode|captcha|verification code|one time|mfa|2fa|social security|national id|taxpayer|passport|drivers? licen[cs]e|work authori[sz]ation|right to work|work permit|eligib|visa|sponsor|salary|compensation|birth|gender|race|ethnicity|disabilit|health|reference|referee|bank |card |start date|availability|citizenship|nationality|signature|consent|agree|acknowledg|terms|privacy|confirm|first name|last name|given name|surname|legal sex|former name|other name|emergency|home address|street address|postal code|zip code|country code|dial code|ethnic|boolean|证件|身份证|护照|签证|签注|工签|工作许可|国籍|户籍|验证码|密码|薪[酬资]|工资|生日|出生|性别|民族|残疾|健康|推荐人|紧急联系|银行卡|可到岗|入职日期|入职时间|到岗时间|确认|同意|条款|隐私|姓氏|曾用名|区号|住址|常住地址|详细地址/u;
const EXCLUDED_CONTEXT = /login|log in|sign in|sign up|register|reset|checkout|payment|billing|unsubscribe|external form action|认证|登录|注册|支付|验证|注销|付款/u;
const EMAIL_RE = /^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/u;
const PHONE_RE = /^[+0-9 ()\-.]{5,36}$/u;

export function normalize(s = '') {
  return String(s).normalize('NFKC').replace(/([a-z])([A-Z])/gu, '$1 $2').toLowerCase()
    .replace(/[_./-]+/gu, ' ').replace(/(?:\(required\)|\(必填\)|\[必填\]|（必填）)/gu, ' ')
    .replace(/[:：*＊]+/gu, ' ').trim().replace(/\s+/gu, ' ');
}

const DATA_LIMIT = { project_summary: 5000, description: 2800 };
function sanitizeValue(key, value) {
  if (typeof value !== 'string') return '';
  value = value.trim();
  if (!value || value.length > (DATA_LIMIT[key] || 500) || /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/u.test(value)) return '';
  if (!['project_summary', 'description'].includes(key) && /[\r\n]/u.test(value)) return '';
  if (key === 'email' && !EMAIL_RE.test(value)) return '';
  if (key === 'phone' && !PHONE_RE.test(value)) return '';
  if (['linkedin', 'github', 'portfolio'].includes(key)) {
    try {
      const url = new URL(value);
      if (url.protocol !== 'https:' || url.username || url.password) return '';
      if (key === 'github' && !['github.com', 'www.github.com'].includes(url.hostname)) return '';
      if (key === 'linkedin' && url.hostname !== 'linkedin.com' && !url.hostname.endsWith('.linkedin.com')) return '';
    } catch { return ''; }
  }
  return value;
}

export function loadProfile(data) {
  const p = data?.profile || data;
  if (!p || typeof p !== 'object' || Array.isArray(p)) throw new Error('不是有效的工作台资料 JSON。');
  const entries = Object.keys(FIELDS).map(key => [key, sanitizeValue(key, p[key])]).filter(([, v]) => !!v);
  for (const key of ['gender', 'political_status']) {
    const value = sanitizeValue(key, p.resume_details?.[key] ?? p[key]);
    if (value) entries.push([key, value]);
  }
  const records = {};
  for (const [kind, fields] of Object.entries(RECORD_FIELDS)) {
    const rows = p.resume_details?.[kind];
    if (!Array.isArray(rows) || !rows.length) continue;
    if (rows.length > 20) throw new Error('每类简历资料最多导入 20 条。');
    const cleaned = rows.map(row => Object.fromEntries(Object.keys(fields).flatMap(key => {
      const value = sanitizeValue(key, row?.[key]);
      return value && (!RECORD_MONTHS.has(key) || MONTH_RE.test(value)) ? [[key, value]] : [];
    })));
    if (cleaned.some(row => Object.keys(row).length)) records[kind] = cleaned;
  }
  const profile = Object.fromEntries(entries);
  if (Object.keys(records).length) profile.resume_details = records;
  return profile;
}

export function describeKey(key, kind) { return RECORD_FIELDS[kind]?.[key]?.[0] || FIELDS[key]?.zh || key; }
export function describeRecordKind(kind) { return RECORD_NAMES[kind]; }
export function describeRecord(record) { return describeRecordKind(record.kind) + '第 ' + record.number + ' 条'; }

function lockedReason(field) {
  if (field.disabled || field.readonly) return '网页锁定';
  if (field.hasValue) return '已有内容，不覆盖';
  if (field.auth || EXCLUDED_CONTEXT.test(normalize(field.context))) return '登录、付款或其他非求职表单';
  return '';
}
const VERIFICATION = /required\s*(?:\||\/)|verify|verify again|re enter|重新输入|再次输入|政治面貌|证书编号|证书号码|学号|家庭资料|家庭成员|家庭情况|家庭信息|家庭关系|家属|亲属资料|亲属信息|亲属关系|父亲|母亲|配偶|监护人|证明人/u;
const GRADUATION = /graduation|graduat(?:e|ion).{0,15}date|毕业年|毕业日期|毕业时间/u;
const SELECT_LABELS = {
  gender: ['性别', '本人性别', 'gender'],
  degree: ['学历', '最高学历', '学历层次', 'education level', 'highest education level'],
  political_status: ['政治面貌', '本人政治面貌', 'political status'],
};
const DEGREE_NAMES = [['本科','大学本科'], ['大专','专科','大学专科'], ['硕士','硕士研究生'], ['博士','博士研究生']];
function matchSelect(field, profile, recordDegree=false) {
  const visible = [field.label, field.aria, field.adjacent].map(normalize).filter(Boolean);
  const key = Object.keys(SELECT_LABELS).find(k => visible.length && visible.every(label => SELECT_LABELS[k].includes(label)));
  const manual = reason => ({match:false, reason});
  if (!key || (recordDegree && key !== 'degree')) return manual('此下拉字段留待手动选择');
  const allowed = SELECT_LABELS[key];
  const metadata = [field.name, field.id, field.placeholder, field.autocomplete, field.context].map(normalize).filter(Boolean);
  if (metadata.some(clue => !allowed.includes(clue) && (MANUAL.test(allowed.reduce((s,label)=>s.replace(label,''),clue)) ||
      VERIFICATION.test(allowed.reduce((s,label)=>s.replace(label,''),clue)) || /family|guardian|father|mother|spouse|reference|relative/u.test(clue) ||
      GRADUATION.test(clue) || Object.entries(SELECT_LABELS).some(([other,labels])=>other!==key && labels.includes(clue)) ||
      Object.entries(FIELDS).some(([other,def])=>other!==key && def.patterns.some(pattern=>pattern.test(clue)))))) {
    return manual('字段线索不一致或需人工核验');
  }
  const value = profile?.[key];
  if (!value) return manual('资料库中没有该项');
  const names = key === 'degree' ? DEGREE_NAMES.find(group => group.includes(value)) || [value] : [value];
  const matches = (field.options || []).filter(option => names.some(name=>normalize(name)===normalize(option.label)));
  if (matches.length !== 1) return manual(matches.length ? '有多个对应选项，请手动选择' : '没有唯一对应的可用选项');
  return { match:true, key, value:matches[0].label, optionIndex:matches[0].index, confidence:'中' };
}
export function matchField(field, profile) {
  const sources = [
    [field.label, 3], [field.aria, 3], [field.adjacent, 2], [field.placeholder, 2],
    [field.name, 1], [field.id, 1], [field.autocomplete, 2],
  ];
  const clues = [...sources.map(([text]) => text), field.context].map(normalize).filter(Boolean);
  const manual = reason => ({ match: false, reason });
  const blocked = lockedReason(field);
  if (blocked) return manual(blocked);
  if (field.type === 'select') return matchSelect(field, profile);
  if (!['text', 'email', 'tel', 'url', 'textarea'].includes(field.type)) return manual('不支持该控件');
  if (!clues.length || clues.some(x => MANUAL.test(x) || GRADUATION.test(x))) return manual('未标注或需手动确认');
  if (clues.some(x => VERIFICATION.test(x))) return manual('请手动填写核验字段');

  const hits = new Map();
  sources.forEach(([clue, priority], i) => {
    const n = normalize(clue);
    if (!n) return;
    for (const [key, { patterns }] of Object.entries(FIELDS)) {
      if (patterns.some(p => p.test(n)) || (i === sources.length - 1 && ((n === 'tel' && key === 'phone') || (n === 'address level2' && key === 'city')))) {
        hits.set(key, Math.max(hits.get(key) || 0, priority));
      }
    }
  });
  if (hits.size !== 1) return manual(hits.size ? '标签提供了冲突的线索' : '无法可靠匹配资料');
  const [key, priority] = [...hits][0];
  if (field.type === 'email' && key !== 'email' || field.type === 'tel' && key !== 'phone' ||
      field.type === 'url' && !['github', 'linkedin', 'portfolio'].includes(key) ||
      field.type === 'textarea' && key !== 'project_summary') return manual('控件类型和字段不一致');
  if (['country', 'national', 'local', 'extension', 'regional', 'area', 'phone number type', 'international code', 'country area'].some(t => clues.some(x => x === t || x.startsWith(t + ' ')))) return manual('可能是国际区号或其他地区字段');
  const value = profile[key];
  if (!value) return manual('资料库中没有该项');
  if (field.maxLength > 0 && String(value).length > field.maxLength) return manual('资料超出网页长度限制');
  if (priority <= 1) return manual('只有字段名称线索，请手动填写');
  return { key, value, match: true, confidence: priority === 3 ? '高' : '中' };
}

function matchRecordField(field, profile) {
  const manual = reason => ({ match: false, reason });
  const blocked = lockedReason(field);
  if (blocked) return manual(blocked);
  const { kind, number, count, uncertain } = field.record;
  if (uncertain) return manual('经历分组不明确，请扫描整页或手动填写');
  const rows = profile.resume_details?.[kind];
  if (!rows?.length) return manual('导入资料没有这一类记录');
  if (rows.length !== count) return manual('网页有 ' + count + ' 条，资料有 ' + rows.length + ' 条，请先核对条数');
  if (field.type === 'select') return kind === 'education' ? matchSelect(field, rows[number-1], true) : manual('此类经历的下拉字段请手动选择');
  const labels = [field.label, field.aria, field.adjacent].map(normalize).filter(Boolean);
  const keys = Object.entries(RECORD_FIELDS[kind]).filter(([, aliases]) => labels.some(label => aliases.includes(label)));
  if (keys.length !== 1) return manual('无法可靠识别这条经历的字段');
  const [[key]] = keys;
  const clues = [...labels, ...[field.placeholder, field.name, field.id, field.autocomplete, field.context].map(normalize)];
  const educationEnd = kind === 'education' && key === 'end';
  if (clues.some(clue => VERIFICATION.test(clue) || MANUAL.test(clue) || (!educationEnd && GRADUATION.test(clue)))) {
    return manual('需手动填写或核验');
  }
  const type = RECORD_MONTHS.has(key) ? 'month' : key === 'description' ? 'textarea' : 'text';
  if (field.type !== type) {
    return manual('控件类型和资料格式不一致');
  }
  const value = rows[number - 1]?.[key];
  if (!value) return manual('这条资料没有该项');
  if (field.maxLength > 0 && value.length > field.maxLength) return manual('资料超出网页长度限制');
  return { key, value, match: true, confidence: '中' };
}

export function makePlan(fields, profile) {
  const plan = fields.map(field => ({
    field, ...(field.record ? matchRecordField(field, profile) : matchField(field, profile)),
  }));
  const identity = ({ field, key }) => field.record ? [field.record.kind, field.record.number, key].join('/') : key;
  const counts = new Map();
  for (const row of plan) if (row.match) counts.set(identity(row), (counts.get(identity(row)) || 0) + 1);
  return plan.map(row => row.match && counts.get(identity(row)) > 1
    ? { field: row.field, match: false, reason: '多个输入框似乎对应同一项，留给你确认' } : row);
}

// Resolve kept record fields with the same record counts, aliases and duplicate
// checks as an empty field. The actual fill plan still sees them as occupied.
export function keptComparisons(fields, profile) {
  const candidates = fields.map(field => {
    if (!field.hasValue || !field.record || !['text', 'textarea', 'month'].includes(field.type)) return field;
    return { ...field, hasValue: false };
  });
  if (!candidates.some((field, i) => field !== fields[i])) return [];
  return makePlan(candidates, profile).flatMap(({field, match, key, value}, i) => {
    if (!match || field === fields[i]) return [];
    const labels = [field.label, field.aria, field.adjacent].map(normalize).filter(Boolean);
    const aliases = RECORD_FIELDS[field.record.kind][key];
    if (!labels.every(label => aliases.includes(label)) ||
        MANUAL.test(normalize(field.autocomplete)) || VERIFICATION.test(normalize(field.autocomplete))) return [];
    return [{ index: field.index, token: field.token, value }];
  });
}

export function textSuggestions(text, profile) {
  return String(text).split(/\r?\n/u).map(x => x.trim()).filter(Boolean).slice(0, 50)
    .map(label => ({ label, ...matchField({ label, type: 'text' }, profile) }));
}
