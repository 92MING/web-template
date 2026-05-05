import { BuiltinBaseElement, html, css } from '../lit-base.js';

const jsonConverter = {
  fromAttribute(value) {
    if (!value) return undefined;
    try { return JSON.parse(value); } catch { return undefined; }
  },
  toAttribute(value) {
    return JSON.stringify(value);
  }
};

export class BuiltinMemberManagerDrawer extends BuiltinBaseElement {
  static properties = {
    open: { type: Boolean },
    placement: { type: String },
    size: { type: String },
    title: { type: String },
    searchPlaceholder: { type: String, attribute: 'search-placeholder' },
    currentTitle: { type: String, attribute: 'current-title' },
    candidateTitle: { type: String, attribute: 'candidate-title' },
    emptyMembers: { type: String, attribute: 'empty-members' },
    emptyCandidates: { type: String, attribute: 'empty-candidates' },
    showRemove: { type: Boolean, attribute: 'show-remove' },
    removeLabel: { type: String, attribute: 'remove-label' },
    addLabel: { type: String, attribute: 'add-label' },
    members: { type: Array, converter: jsonConverter },
    candidates: { type: Array, converter: jsonConverter },
    searchValue: { type: String, attribute: 'search-value' },
  };

  static styles = css`
    :host { display: block; }
    .trigger-card {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      width: 100%;
      min-height: 54px;
      padding: 10px 12px;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius-lg, 8px);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      cursor: pointer;
      font: inherit;
      text-align: left;
    }
    .trigger-card:hover { border-color: var(--builtin-primary, #2563eb); background: var(--builtin-row-hover-bg, #f9fafb); }
    .trigger-main { display: grid; gap: 2px; }
    .trigger-title { font-weight: 700; }
    .trigger-sub { color: var(--builtin-color-muted, #6b7280); font-size: 0.82rem; }
    .search-input {
      width: 100%;
      padding: 0.5rem 0.75rem;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-input-bg, #fff);
      color: inherit;
      font: inherit;
      margin-bottom: 0.75rem;
      box-sizing: border-box;
    }
    .section-title {
      font-weight: 600;
      margin: 0.5rem 0;
      font-size: 0.9rem;
    }
    .member-row,
    .candidate-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 0.75rem;
      padding: 0.6rem 0;
      border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb);
    }
    .candidate-info {
      min-width: 0;
      font-size: 0.875rem;
    }
    .candidate-name {
      color: var(--builtin-color-text, #111827);
      font-weight: 600;
    }
    .candidate-sub {
      font-size: 0.75rem;
      color: var(--builtin-color-muted, #6b7280);
      margin-top: 0.2rem;
    }
    .empty-tip {
      color: var(--builtin-color-muted, #6b7280);
      font-size: 0.85rem;
      padding: 0.5rem 0;
    }
    .btn-add {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.25rem;
      padding: 0.35rem 0.55rem;
      border: 1px solid var(--builtin-primary, #2563eb);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-primary, #2563eb);
      color: #fff;
      cursor: pointer;
      font: inherit;
    }
    .btn-remove {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.25rem;
      padding: 0.35rem 0.55rem;
      border: 1px solid var(--builtin-border, #d1d5db);
      border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-surface, #ffffff);
      color: var(--builtin-color-text, #111827);
      cursor: pointer;
      font: inherit;
    }
  `;

  constructor() {
    super();
    this.open = false;
    this.placement = 'right';
    this.size = '400px';
    this.title = '';
    this.searchPlaceholder = '';
    this.currentTitle = '';
    this.candidateTitle = '';
    this.emptyMembers = '';
    this.emptyCandidates = '';
    this.showRemove = false;
    this.removeLabel = '';
    this.addLabel = '';
    this.members = [];
    this.candidates = [];
    this.searchValue = '';
  }

  openDrawer() {
    this.open = true;
  }

  close() {
    this.open = false;
  }

  _emitClose() {
    this.open = false;
    this.dispatchEvent(new CustomEvent('builtin-close', { bubbles: true, composed: true }));
  }

  _emitSearch(e) {
    this.searchValue = e.target.value;
    this.dispatchEvent(new CustomEvent('builtin-member-search', {
      bubbles: true,
      composed: true,
      detail: { query: this.searchValue.trim() },
    }));
  }

  _emitAdd(candidate) {
    this.dispatchEvent(new CustomEvent('builtin-member-add', {
      bubbles: true,
      composed: true,
      detail: { candidate, userId: this._personId(candidate) },
    }));
  }

  _emitRemove(member) {
    this.dispatchEvent(new CustomEvent('builtin-member-remove', {
      bubbles: true,
      composed: true,
      detail: { member, userId: this._personId(member) },
    }));
  }

  _personId(person) {
    return person.user_id || person.id || person.email || person.name || person.nickname || '';
  }

  _personName(person) {
    return person.nickname || person.name || person.user_id || person.id || '-';
  }

  _personSub(person) {
    return [person.email || '', person.grade || person.role || person.title || ''].filter(Boolean).join(' · ');
  }

  _renderPersonRow(person, actions = null) {
    return html`
      <div class="candidate-info">
        <div class="candidate-name">${this._personName(person)}</div>
        <div class="candidate-sub">${this._personSub(person)}</div>
      </div>
      ${actions}
    `;
  }

  render() {
    return html`
      ${this.open ? '' : html`
        <button class="trigger-card" @click=${() => this.openDrawer()}>
          <span class="trigger-main">
            <span class="trigger-title">${this.title || '成员管理'}</span>
            <span class="trigger-sub">${this.members.length} members · ${this.candidates.length} candidates</span>
          </span>
          <builtin-icon name="right" size="18"></builtin-icon>
        </button>
      `}
      <builtin-drawer .open=${this.open} placement="${this.placement}" size="${this.size}" @builtin-close=${() => this._emitClose()}>
        <span slot="title">${this.title}</span>
        <input class="search-input" type="search" .value=${this.searchValue} placeholder="${this.searchPlaceholder}" @input=${(e) => this._emitSearch(e)}>
        <div class="section-title">${this.currentTitle || '当前成员'}</div>
        ${this.members.length ? this.members.map((member) => html`
          <div class="member-row">
            ${this._renderPersonRow(member, this.showRemove ? html`
              <button class="btn-remove" @click=${() => this._emitRemove(member)}>${this.removeLabel || '移除'}</button>
            ` : null)}
          </div>
        `) : html`<builtin-empty-state .heading=${this.emptyMembers || '暂无成员'}></builtin-empty-state>`}
        <div class="section-title">${this.candidateTitle || '可添加成员'}</div>
        ${this.candidates.length ? this.candidates.map((candidate) => html`
          <div class="candidate-row">
            ${this._renderPersonRow(candidate, html`
              <button class="btn-add" @click=${() => this._emitAdd(candidate)}>
                <builtin-icon name="plus" size="14"></builtin-icon>
                <span>${this.addLabel || ''}</span>
              </button>
            `)}
          </div>
        `) : html`<builtin-empty-state .heading=${this.emptyCandidates || '暂无候选人'}></builtin-empty-state>`}
      </builtin-drawer>
    `;
  }
}