(function(global) {
  'use strict';

  function createRenderer(deps) {
    const state = deps.state;

    function sectionToneFor(path) {
      const topLevelPath = String(path || '').split('.')[0].replace(/\[\]/g, '');
      const toneMap = {
        server_config: 'cyan',
        core_config: 'amber',
        log_config: 'rose',
      };
      return toneMap[topLevelPath] || 'indigo';
    }

    function textFor(key, fallback) {
      if (!key) return fallback || '';
      return (state.translations && state.translations[key]) || fallback || key;
    }

    function createRequiredBadge(field) {
      if (!field.required) return null;
      const badge = document.createElement('span');
      badge.className = 'required-badge';
      badge.textContent = textFor('backend.settings.required', 'Required');
      return badge;
    }

    function buildHelperText(field) {
      if (field.kind === 'enum-array') return textFor('backend.settings.helper.enum_array', '枚举数组使用标签切换。');
      if (field.kind === 'json') return textFor('backend.settings.helper.json', '复杂值使用 JSON 编辑。');
      if (field.kind === 'list') return textFor('backend.settings.helper.list', '每行一个值。');
      if (field.kind === 'boolean') return textFor('backend.settings.helper.boolean', '布尔值使用开关。');
      return field.nullable ? textFor('backend.settings.nullable', '可为空') : '';
    }

    function createChipGroup(field, value, setValue) {
      const wrap = document.createElement('div');
      wrap.className = 'chip-group';
      const multi = field.kind === 'enum-array';
      const selectedValues = multi ? new Set(Array.isArray(value) ? value : []) : new Set([value]);
      (field.options || []).forEach((option) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'chip';
        btn.dataset.option = option;
        btn.textContent = textFor(option, option);
        btn.disabled = !state.editing;
        const sync = () => btn.classList.toggle('active', selectedValues.has(option));
        sync();
        btn.addEventListener('click', () => {
          if (!state.editing) return;
          if (multi) {
            if (selectedValues.has(option)) selectedValues.delete(option);
            else selectedValues.add(option);
            setValue(Array.from(selectedValues));
          } else {
            selectedValues.clear();
            selectedValues.add(option);
            setValue(option);
          }
          wrap.querySelectorAll('.chip').forEach((chip) => chip.classList.remove('active'));
          wrap.querySelectorAll('.chip').forEach((chip) => {
            if (selectedValues.has(chip.dataset.option || '')) chip.classList.add('active');
          });
        });
        wrap.appendChild(btn);
      });
      return wrap;
    }

    function createBooleanControl(path, value) {
      const wrap = document.createElement('label');
      wrap.className = 'switch-row';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.className = 'field-switch-input';
      input.checked = !!value;
      input.disabled = !state.editing;
      const slider = document.createElement('span');
      slider.className = 'field-switch-slider';
      const text = document.createElement('span');
      text.className = 'field-switch-text';
      const sync = () => {
        text.textContent = input.checked
          ? textFor('backend.settings.boolean.true', 'On')
          : textFor('backend.settings.boolean.false', 'Off');
      };
      input.addEventListener('change', () => {
        deps.setByPath(state.config, path, input.checked);
        sync();
      });
      sync();
      wrap.append(input, slider, text);
      return wrap;
    }

    function createDictControl(field, value, assignValue) {
      const pairs = Object.entries(value && typeof value === 'object' ? value : {});
      const container = document.createElement('div');
      container.style.cssText = 'display:grid;gap:6px;';

      function sync() {
        const obj = {};
        container.querySelectorAll('.dict-row').forEach((row) => {
          const keyInput = row.querySelector('.dict-key');
          const valueInput = row.querySelector('.dict-val');
          const key = keyInput.value.trim();
          const rawValue = valueInput.value;
          if (!key) return;
          if (field.value_kind === 'integer') obj[key] = Number.parseInt(rawValue, 10) || 0;
          else if (field.value_kind === 'number') obj[key] = Number(rawValue) || 0;
          else if (field.value_kind === 'boolean') obj[key] = rawValue === 'true';
          else obj[key] = rawValue;
        });
        assignValue(obj);
      }

      function addRow(key = '', fieldValue = '') {
        const row = document.createElement('div');
        row.className = 'dict-row';
        row.style.cssText = 'display:grid;grid-template-columns:minmax(80px,1fr) minmax(80px,1.5fr) 28px;gap:6px;align-items:center;';
        const keyInput = document.createElement('input');
        keyInput.className = 'field-input dict-key';
        keyInput.placeholder = 'key';
        keyInput.value = key;
        keyInput.disabled = !state.editing;
        keyInput.addEventListener('input', sync);
        const valueInput = document.createElement('input');
        valueInput.className = 'field-input dict-val';
        valueInput.placeholder = 'value';
        valueInput.type = field.value_kind === 'integer' || field.value_kind === 'number' ? 'number' : 'text';
        valueInput.value = String(fieldValue ?? '');
        valueInput.disabled = !state.editing;
        valueInput.addEventListener('input', sync);
        const del = document.createElement('button');
        del.type = 'button';
        del.innerHTML = '<i class="proj-icon proj-icon-x"></i>';
        del.setAttribute('aria-label', textFor('backend.settings.item.remove', '删除'));
        del.style.cssText = 'width:28px;height:28px;border:none;border-radius:6px;background:rgba(239,68,68,.12);color:#dc2626;cursor:pointer;font-size:12px;';
        del.disabled = !state.editing;
        del.addEventListener('click', () => {
          row.remove();
          sync();
        });
        row.append(keyInput, valueInput, del);
        container.insertBefore(row, addBtn);
      }

      const addBtn = document.createElement('button');
      addBtn.type = 'button';
      addBtn.className = 'btn';
      addBtn.style.cssText = 'justify-self:start;min-height:28px;padding:0 10px;border-radius:8px;border:1px solid var(--proj-page-border);background:var(--proj-page-surface-strong);color:var(--proj-page-text);font-size:12px;font-weight:700;cursor:pointer;';
      addBtn.textContent = textFor('backend.settings.item.add', '+ 添加');
      addBtn.disabled = !state.editing;
      addBtn.addEventListener('click', () => addRow());
      container.appendChild(addBtn);

      pairs.forEach(([key, pairValue]) => addRow(key, pairValue));
      return container;
    }

    function normalizeListValue(field, value) {
      if (Array.isArray(value)) return value.map((item) => String(item));
      if (typeof value === 'string') return deps.parsePrimitiveList(value, field.item_kind).map((item) => String(item));
      return [];
    }

    function coerceListItem(rawValue, itemKind) {
      const text = String(rawValue || '').trim();
      if (itemKind === 'integer') return Number.parseInt(text, 10);
      if (itemKind === 'number') return Number(text);
      if (itemKind === 'boolean') return ['1', 'true', 'yes', 'on'].includes(text.toLowerCase());
      return text;
    }

    function createListControl(field, value, assignValue) {
      const container = document.createElement('div');
      container.className = 'field-list-editor';
      const inputRow = document.createElement('div');
      inputRow.className = 'field-list-input-row';
      const input = document.createElement('input');
      input.className = 'field-input field-list-input';
      input.type = field.item_kind === 'integer' || field.item_kind === 'number' ? 'number' : 'text';
      input.disabled = !state.editing;
      input.placeholder = textFor('backend.settings.item.add', '+ 添加').replace(/^\+\s*/, '');
      const addButton = document.createElement('button');
      addButton.type = 'button';
      addButton.className = 'panel-btn field-list-add-btn';
      addButton.textContent = '+';
      addButton.setAttribute('aria-label', textFor('backend.settings.item.add', '+ 添加'));
      addButton.disabled = !state.editing;
      const list = document.createElement('div');
      list.className = 'field-list-scroll';
      let items = normalizeListValue(field, value);

      function commit() {
        assignValue(items.map((item) => coerceListItem(item, field.item_kind)));
      }

      function renderItems() {
        list.innerHTML = '';
        if (!items.length) {
          const empty = document.createElement('div');
          empty.className = 'field-list-empty';
          empty.textContent = '—';
          list.appendChild(empty);
          return;
        }
        items.forEach((item, index) => {
          const row = document.createElement('div');
          row.className = 'field-list-item';
          const valueText = document.createElement('span');
          valueText.className = 'field-list-value';
          valueText.textContent = item;
          const removeButton = document.createElement('button');
          removeButton.type = 'button';
          removeButton.className = 'field-list-remove';
          removeButton.innerHTML = '<i class="proj-icon proj-icon-x"></i>';
          removeButton.setAttribute('aria-label', textFor('backend.settings.item.remove', '删除'));
          removeButton.disabled = !state.editing;
          removeButton.addEventListener('click', () => {
            if (!state.editing) return;
            items.splice(index, 1);
            commit();
            renderItems();
          });
          row.append(valueText, removeButton);
          list.appendChild(row);
        });
      }

      function addItem() {
        if (!state.editing) return;
        const nextItem = input.value.trim();
        if (!nextItem) return;
        if ((field.item_kind === 'integer' || field.item_kind === 'number') && Number.isNaN(Number(nextItem))) {
          deps.markFieldValidity(input, field.path, false);
          return;
        }
        deps.markFieldValidity(input, field.path, true);
        items.push(nextItem);
        input.value = '';
        commit();
        renderItems();
      }

      addButton.addEventListener('click', addItem);
      input.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        addItem();
      });
      inputRow.append(input, addButton);
      container.append(inputRow, list);
      renderItems();
      return container;
    }

    function createFieldControl(field, value) {
      const path = field.path;
      const assignValue = (nextValue) => deps.setByPath(state.config, path, nextValue);

      if (field.kind === 'enum' || field.kind === 'enum-array') {
        return createChipGroup(field, value, assignValue);
      }

      if (field.kind === 'boolean') {
        return createBooleanControl(path, !!value);
      }

      if (field.kind === 'dict') {
        return createDictControl(field, value, assignValue);
      }

      if (field.kind === 'string' || field.kind === 'integer' || field.kind === 'number') {
        const input = document.createElement('input');
        input.className = 'field-input';
        input.type = field.kind === 'string' ? 'text' : 'number';
        if (field.kind === 'integer') input.step = '1';
        if (field.kind === 'number') input.step = 'any';
        input.value = value == null ? '' : String(value);
        input.disabled = !state.editing;
        input.addEventListener('input', () => {
          const raw = input.value;
          if (!raw && field.nullable) {
            assignValue(null);
            return;
          }
          if (field.kind === 'integer') {
            assignValue(raw === '' ? 0 : Number.parseInt(raw, 10));
            return;
          }
          if (field.kind === 'number') {
            assignValue(raw === '' ? 0 : Number(raw));
            return;
          }
          assignValue(raw);
        });
        return input;
      }

      if (field.kind === 'list') {
        return createListControl(field, value, assignValue);
      }

      const textarea = document.createElement('textarea');
      textarea.className = 'field-textarea';
      textarea.value = deps.humanizeJson(value);
      textarea.disabled = !state.editing;
      textarea.addEventListener('input', () => {
        const raw = textarea.value.trim();
        if (!raw && field.nullable) {
          assignValue(null);
          deps.markFieldValidity(textarea, path, true);
          return;
        }
        try {
          assignValue(JSON.parse(raw || 'null'));
          deps.markFieldValidity(textarea, path, true);
        } catch {
          deps.markFieldValidity(textarea, path, false);
        }
      });
      return textarea;
    }

    function renderField(field, value, depth) {
      const currentDepth = depth || 0;
      if (field.kind === 'object') {
        const section = document.createElement('details');
        section.className = 'section';
        section.open = currentDepth === 0 ? field.path !== 'storage_config' : false;
        section.dataset.depth = String(currentDepth);
        section.dataset.fieldPath = field.path;
        section.dataset.sectionTone = sectionToneFor(field.path);
        const summary = document.createElement('summary');
        summary.innerHTML = `
          <div>
            <div class="section-title">${textFor(field.label_key, field.label)}</div>
            <div class="field-desc">${textFor(field.description_key, field.description || '')}</div>
          </div>
          <div class="field-path">${field.path}</div>
        `;
        section.appendChild(summary);
        const body = document.createElement('div');
        body.className = 'section-body';
        (field.children || []).forEach((child) => {
          body.appendChild(renderField(child, deps.getByPath(state.config, child.path), currentDepth + 1));
        });
        section.appendChild(body);
        return section;
      }

      if (field.kind === 'list-object') {
        const section = document.createElement('details');
        section.className = 'section';
        section.open = currentDepth === 0;
        section.dataset.depth = String(currentDepth);
        section.dataset.fieldPath = field.path;
        section.dataset.sectionTone = sectionToneFor(field.path);
        const summary = document.createElement('summary');
        summary.innerHTML = `
          <div>
            <div class="section-title">${textFor(field.label_key, field.label)}</div>
            <div class="field-desc">${textFor(field.description_key, field.description || '')}</div>
          </div>
          <div class="field-path">${field.path}</div>
        `;
        section.appendChild(summary);
        const body = document.createElement('div');
        body.className = 'section-body';

        function cloneChildForIdx(child, idx) {
          const mapped = { ...child, path: child.path.replace('[]', '.' + idx) };
          if (mapped.children) mapped.children = mapped.children.map((sub) => cloneChildForIdx(sub, idx));
          return mapped;
        }

        function rebuildListItems() {
          body.innerHTML = '';
          const items = deps.getByPath(state.config, field.path) || [];
          items.forEach((item, idx) => {
            const itemSec = document.createElement('details');
            itemSec.className = 'section';
            itemSec.style.marginTop = '8px';
            itemSec.open = true;
            const itemSum = document.createElement('summary');
            const titleDiv = document.createElement('div');
            titleDiv.className = 'section-title';
            titleDiv.textContent = '#' + (idx + 1);
            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'btn';
            removeBtn.textContent = textFor('backend.settings.item.remove', '删除');
            removeBtn.style.cssText = 'min-height:24px;padding:0 8px;font-size:11px;background:rgba(239,68,68,.12);color:#dc2626;border-color:rgba(239,68,68,.25);';
            removeBtn.disabled = !state.editing;
            removeBtn.addEventListener('click', (event) => {
              event.preventDefault();
              const arr = deps.getByPath(state.config, field.path) || [];
              arr.splice(idx, 1);
              deps.setByPath(state.config, field.path, arr);
              rebuildListItems();
            });
            itemSum.appendChild(titleDiv);
            itemSum.appendChild(removeBtn);
            itemSec.appendChild(itemSum);
            const itemBody = document.createElement('div');
            itemBody.className = 'section-body';
            (field.children || []).forEach((child) => {
              const mapped = cloneChildForIdx(child, idx);
              itemBody.appendChild(renderField(mapped, deps.getByPath(state.config, mapped.path), currentDepth + 1));
            });
            itemSec.appendChild(itemBody);
            body.appendChild(itemSec);
          });
          const addBtn = document.createElement('button');
          addBtn.type = 'button';
          addBtn.className = 'btn';
          addBtn.style.marginTop = '8px';
          addBtn.textContent = textFor('backend.settings.item.add', '+ 添加');
          addBtn.disabled = !state.editing;
          addBtn.addEventListener('click', () => {
            const arr = deps.getByPath(state.config, field.path) || [];
            arr.push({});
            deps.setByPath(state.config, field.path, arr);
            rebuildListItems();
          });
          body.appendChild(addBtn);
        }

        rebuildListItems();
        section.appendChild(body);
        return section;
      }

      const row = document.createElement('div');
      row.className = 'field-row';

      const meta = document.createElement('div');
      const name = document.createElement('div');
      name.className = 'field-name';
      name.textContent = textFor(field.label_key, field.label);
      meta.appendChild(name);
      const badge = createRequiredBadge(field);
      if (badge) meta.appendChild(badge);
      const path = document.createElement('div');
      path.className = 'field-path';
      path.textContent = field.path;
      meta.appendChild(path);
      if (field.description) {
        const desc = document.createElement('div');
        desc.className = 'field-desc';
        desc.textContent = textFor(field.description_key, field.description);
        meta.appendChild(desc);
      }
      row.appendChild(meta);

      const controlWrap = document.createElement('div');
      controlWrap.appendChild(createFieldControl(field, value));
      const helper = document.createElement('div');
      helper.className = 'helper';
      helper.textContent = buildHelperText(field);
      controlWrap.appendChild(helper);
      row.appendChild(controlWrap);
      return row;
    }

    return {
      createFieldControl,
      renderField,
    };
  }

  global.ProjBackendSettingsRenderer = {
    createRenderer,
  };
})(window);
