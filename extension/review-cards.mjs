import { describeRecordKind } from './matcher.mjs';

export const reviewFieldLabel = field => field.label || field.aria || field.adjacent ||
  field.placeholder || field.name || field.id || '未标记字段';

export function buildReviewCards(document, rows, attachSelection) {
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  };
  const groups = new Map();
  for (const row of rows) {
    const { kind = 'basic', number = 0 } = row.field.record || {};
    if (!groups.has(kind)) groups.set(kind, new Map());
    const records = groups.get(kind);
    if (!records.has(number)) records.set(number, []);
    records.get(number).push(row);
  }

  const cards = element('div', 'review-cards');
  for (const [kind, records] of groups) {
    const group = element('section', 'review-group');
    const heading = element('div', 'review-group-heading');
    const count = [...records.values()].reduce((sum, fields) => sum + fields.length, 0);
    heading.append(element('h3', '', describeRecordKind(kind) || '常用资料'),
      element('span', 'review-count', (kind === 'basic' ? '' : records.size + ' 条 · ') + count + ' 项'));
    group.append(heading);

    for (const [number, fields] of records) {
      const record = element('div', 'review-record');
      if (number) {
        const title = element('h4', '', '第 ' + number + ' 条');
        const identifier = attachSelection && fields.find(row =>
          ['school', 'company', 'organization', 'name', 'language'].includes(row.key));
        if (identifier) title.append(element('span', 'review-record-name', identifier.value));
        record.append(title);
      }
      for (const row of fields) {
        const line = element(attachSelection ? 'label' : 'div', attachSelection ? 'review-field selectable' : 'review-field');
        if (attachSelection) {
          const check = element('input');
          check.type = 'checkbox';
          line.title = '匹配信心：' + row.confidence;
          attachSelection(row, check);
          line.append(check);
        }
        const value=element('strong', 'review-field-value', row.value);
        if (row.field.type==='select') value.className+=' review-option-value';
        line.append(element('span', 'review-field-label', reviewFieldLabel(row.field)), value);
        record.append(line);
      }
      group.append(record);
    }
    cards.append(group);
  }
  return cards;
}
