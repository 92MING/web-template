(function(global) {
  'use strict';

  const ui = global.StorageUI;
  if (!ui) throw new Error('StorageUI is required before storage-orm-base.js');

  function parseConditionValue(operator, raw) {
    const text = String(raw ?? '').trim();
    if (operator === 'exists') return !(text === 'false' || text === '0');
    if (!text) return null;
    if (['in', 'nin', 'all'].includes(operator)) {
      const parsed = ui.safeJsonParse(text, null);
      if (Array.isArray(parsed)) return parsed;
      return text.split(',').map((item) => item.trim()).filter(Boolean);
    }
    if (operator === 'regex') return text;
    const parsed = ui.safeJsonParse(text, undefined);
    if (parsed !== undefined) return parsed;
    if (/^-?\d+(\.\d+)?$/.test(text)) return Number(text);
    if (text === 'true') return true;
    if (text === 'false') return false;
    if (text === 'null') return null;
    return text;
  }

  function buildVisualQuery(conditions, joinMode) {
    const parts = [];
    (conditions || []).forEach((condition) => {
      const field = String(condition?.field || '').trim();
      const operator = String(condition?.operator || 'eq');
      if (!field) return;
      const value = parseConditionValue(operator, condition?.value);
      let payload;
      switch (operator) {
        case 'eq': payload = { [field]: value }; break;
        case 'ne': payload = { [field]: { $ne: value } }; break;
        case 'gt': payload = { [field]: { $gt: value } }; break;
        case 'gte': payload = { [field]: { $gte: value } }; break;
        case 'lt': payload = { [field]: { $lt: value } }; break;
        case 'lte': payload = { [field]: { $lte: value } }; break;
        case 'in': payload = { [field]: { $in: Array.isArray(value) ? value : [value] } }; break;
        case 'nin': payload = { [field]: { $nin: Array.isArray(value) ? value : [value] } }; break;
        case 'exists': payload = { [field]: { $exists: !!value } }; break;
        case 'regex': payload = { [field]: { $regex: String(value || '') } }; break;
        case 'contains': payload = { [field]: { $regex: String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&') } }; break;
        case 'prefix': payload = { [field]: { $regex: '^' + String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&') } }; break;
        default: payload = { [field]: value };
      }
      parts.push(payload);
    });
    if (!parts.length) return {};
    if (parts.length === 1) return parts[0];
    return { [(joinMode || 'and') === 'or' ? '$or' : '$and']: parts };
  }

  function summarizeDocument(doc) {
    const payload = doc && doc.document ? doc.document : (doc && doc.payload ? doc.payload : doc);
    const json = JSON.stringify(payload ?? {});
    return json.length > 140 ? json.slice(0, 137) + '…' : json;
  }

  function summarizeExamples(examples) {
    const items = Array.isArray(examples) ? examples : [];
    if (!items.length) return '—';
    const preview = JSON.stringify(items.slice(0, 2));
    const compact = preview.length > 220 ? preview.slice(0, 217) + '…' : preview;
    return items.length > 2 ? `${compact} (+${items.length - 2})` : compact;
  }

  function renderFieldLists(target, declaredFields, sampleFields) {
    if (!target) return;
    const declared = (declaredFields || []).map((field) => `
      <tr>
        <td class="orm-schema-cell-name">${ui.escapeHtml(field.name)}</td>
        <td>${ui.escapeHtml(field.declared_type || '—')}</td>
        <td>${field.required ? '是' : '否'}</td>
        <td>${ui.escapeHtml(field.description || '')}</td>
      </tr>`).join('') || '<tr class="orm-schema-empty-row"><td colspan="4">无声明字段</td></tr>';
    const samples = (sampleFields || []).map((field) => `
      <tr>
        <td class="orm-schema-cell-name">${ui.escapeHtml(field.name)}</td>
        <td class="orm-schema-cell-code">${ui.escapeHtml((field.sample_types || []).join(', ') || '—')}</td>
        <td class="orm-schema-cell-code">${ui.escapeHtml(summarizeExamples(field.examples || []))}</td>
      </tr>`).join('') || '<tr class="orm-schema-empty-row"><td colspan="3">无采样字段</td></tr>';
    target.innerHTML = `
      <div class="orm-schema-field-grid">
        <div class="orm-schema-table-card">
          <div class="orm-schema-table-title">声明字段</div>
          <div class="orm-schema-table-wrap"><table class="orm-schema-table"><thead><tr><th>字段</th><th>类型</th><th>必填</th><th>说明</th></tr></thead><tbody>${declared}</tbody></table></div>
        </div>
        <div class="orm-schema-table-card">
          <div class="orm-schema-table-title">采样字段</div>
          <div class="orm-schema-table-wrap"><table class="orm-schema-table"><thead><tr><th>字段</th><th>样本类型</th><th>示例</th></tr></thead><tbody>${samples}</tbody></table></div>
        </div>
      </div>`;
  }

  function normalizeCollectionMeta(items) {
    return [...(items || [])].sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')));
  }

  global.StorageOrmBase = {
    buildVisualQuery,
    parseConditionValue,
    summarizeDocument,
    renderFieldLists,
    normalizeCollectionMeta,
  };
})(window);
