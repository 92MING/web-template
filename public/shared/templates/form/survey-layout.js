/**
 * @fileoverview BuiltinTplFormSurvey - Survey / questionnaire page template (Lit).
 *
 * Attributes:
 *   - questions: JSON array of question objects { id, text, type, options[], placeholder }
 *   - mode: 'single' | 'all'
 *   - labels: JSON object for i18n overrides
 *
 * Events:
 *   - builtin-answer: Answer changed. Detail: { questionId, value }.
 *   - builtin-survey-submit: Survey submitted. Detail: { answers }.
 */

import { BuiltinBaseElement, html, css, classMap, styleMap, repeat } from "../../components/lit-base.js";

export class BuiltinTplFormSurvey extends BuiltinBaseElement {
  static get properties() {
    return {
            questions: {
        converter: {
          fromAttribute: (v) => {
            try { return JSON.parse(v || "[]"); } catch { return []; }
          },
        },
      },
      mode: { type: String },
      labels: {
        converter: {
          fromAttribute: (v) => {
            try { return JSON.parse(v || "{}"); } catch { return {}; }
          },
        },
      },
    };
  }

  constructor() {
    super();
    this.questions = [];
    this.mode = "single";
    this.labels = {};
    this._current = 0;
    this._answers = {};
    this._completed = false;
  }

  _t(key, values) {
    if (this.labels && this.labels[key] !== undefined) {
      let text = String(this.labels[key]);
      if (values && typeof values === "object") {
        text = text.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name) =>
          Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match
        );
      }
      return text;
    }
    return super._t(key, values);
  }

  willUpdate(changedProperties) {
    if (!this.questions || this.questions.length === 0) {
      this.questions = this._defaultQuestions();
    }
    super.willUpdate(changedProperties);
  }

  _defaultQuestions() {
    return [
      { id: "satisfaction", text: "How satisfied are you with our service?", type: "rating" },
      { id: "feature", text: "Which feature do you use the most?", type: "select", options: [{ value: "chat", label: "Chat" }, { value: "files", label: "File sharing" }, { value: "calls", label: "Video calls" }] },
      { id: "feedback", text: "Any additional feedback?", type: "textarea", placeholder: "Share your thoughts..." },
    ];
  }

  _progressPercent() {
    if (!this.questions.length) return 0;
    const answered = Object.keys(this._answers).filter(
      (k) => this._answers[k] !== undefined && this._answers[k] !== ""
    ).length;
    return Math.round((answered / this.questions.length) * 100);
  }

  _onPrev() {
    if (this._current > 0) {
      this._current -= 1;
    }
  }

  _onNext() {
    if (this._current < this.questions.length - 1) {
      this._current += 1;
    }
  }

  _onSubmit() {
    this._completed = true;
    this.dispatchEvent(
      new CustomEvent("builtin-survey-submit", {
        bubbles: true,
        composed: true,
        detail: { answers: { ...this._answers } },
      })
    );
  }

  _emitAnswer(questionId, value) {
    this.dispatchEvent(
      new CustomEvent("builtin-answer", {
        bubbles: true,
        composed: true,
        detail: { questionId, value },
      })
    );
  }

  _onChange(e) {
    const el = e.target.closest("[data-question]");
    if (!el) return;
    const qid = el.dataset.question;
    let value;
    if (e.target.type === "checkbox") {
      const cbs = this.renderRoot.querySelectorAll(
        `[data-question="${CSS.escape(qid)}"] input[type="checkbox"]`
      );
      value = Array.from(cbs)
        .filter((cb) => cb.checked)
        .map((cb) => cb.value);
    } else if (e.target.type === "radio") {
      value = e.target.value;
    } else if (e.target.tagName === "SELECT") {
      value = e.target.value;
    }
    this._answers[qid] = value;
    this._emitAnswer(qid, value);
  }

  _onInput(e) {
    const el = e.target.closest("[data-question]");
    if (!el) return;
    const qid = el.dataset.question;
    if (e.target.tagName === "TEXTAREA" || e.target.type === "text") {
      this._answers[qid] = e.target.value;
      this._emitAnswer(qid, e.target.value);
    }
  }

  _onRatingClick(qid, rating) {
    this._answers[qid] = rating;
    this._emitAnswer(qid, rating);
    this.requestUpdate();
  }

  _renderStars(current) {
    const r = Math.max(0, Math.min(5, Number(current) || 0));
    return html`
      ${[1, 2, 3, 4, 5].map(
        (i) => html`
          <builtin-icon
            class="star ${classMap({ filled: i <= r })}"
            name="star"
            size="24"
            variant="outlined"
          ></builtin-icon>
        `
      )}
    `;
  }

  _renderQuestionInput(q, idx) {
    const qid = q.id || `q-${idx}`;
    const type = q.type || "text";
    const answer = this._answers[qid] || "";

    if (type === "text" || type === "number" || type === "email") {
      return html`
        <input
          type="${type}"
          class="survey-input"
          data-question="${qid}"
          .value=${answer}
          placeholder="${q.placeholder || ""}"
          @input=${this._onInput}
        />
      `;
    }
    if (type === "textarea") {
      return html`
        <textarea
          class="survey-input"
          data-question="${qid}"
          placeholder="${q.placeholder || ""}"
          @input=${this._onInput}
        >
${answer}</textarea
        >
      `;
    }
    if (type === "select") {
      return html`
        <select class="survey-input" data-question="${qid}" @change=${this._onChange}>
          ${repeat(
            q.options || [],
            (opt) => opt.value,
            (opt) => html`
              <option value="${opt.value}" ?selected=${opt.value === answer}>
                ${opt.label}
              </option>
            `
          )}
        </select>
      `;
    }
    if (type === "radio" || type === "checkbox") {
      return html`
        ${repeat(
          q.options || [],
          (opt) => opt.value,
          (opt) => {
            const checked =
              type === "checkbox"
                ? Array.isArray(answer) && answer.includes(opt.value)
                : String(answer) === String(opt.value);
            return html`
              <label class="touch-label">
                <input
                  type="${type}"
                  name="${qid}"
                  value="${opt.value}"
                  ?checked=${checked}
                  data-question="${qid}"
                  @change=${this._onChange}
                />
                <span>${opt.label}</span>
              </label>
            `;
          }
        )}
      `;
    }
    if (type === "rating") {
      return html`
        <div class="rating-row" data-question="${qid}">
          ${[1, 2, 3, 4, 5].map(
            (i) => html`
              <button
                type="button"
                class="rating-btn ${classMap({ filled: i <= (answer || 0) })}"
                @click=${() => this._onRatingClick(qid, i)}
                aria-label="${i} stars"
              >
                <builtin-icon name="star" size="24" variant="outlined"></builtin-icon>
              </button>
            `
          )}
        </div>
      `;
    }
    return "";
  }

  _renderQuestionCard(q, idx) {
    const qid = q.id || `q-${idx}`;
    return html`
      <div class="question-card" data-question="${qid}">
        <div class="question-header">
          <span class="question-number">${idx + 1}</span>
          <span class="question-text">${q.text || ""}</span>
        </div>
        <div class="question-body">${this._renderQuestionInput(q, idx)}</div>
      </div>
    `;
  }

  _renderSingle() {
    const q = this.questions[this._current];
    if (!q) return "";
    const isFirst = this._current === 0;
    const isLast = this._current === this.questions.length - 1;
    return html`
      <div class="survey-body">
        ${this._renderQuestionCard(q, this._current)}
        <div class="survey-actions">
          <button
            type="button"
            class="btn btn-secondary"
            ?disabled=${isFirst}
            @click=${this._onPrev}
          >
            ${this._t("survey.prev")}
          </button>
          ${isLast
            ? html`
                <button
                  type="button"
                  class="btn btn-primary"
                  @click=${this._onSubmit}
                >
                  ${this._t("survey.submit")}
                </button>
              `
            : html`
                <button
                  type="button"
                  class="btn btn-primary"
                  @click=${this._onNext}
                >
                  ${this._t("survey.next")}
                </button>
              `}
        </div>
      </div>
    `;
  }

  _renderAll() {
    return html`
      <div class="survey-body">
        ${repeat(
          this.questions,
          (q, i) => q.id || `q-${i}`,
          (q, i) => this._renderQuestionCard(q, i)
        )}
        <div class="survey-actions">
          <button type="button" class="btn btn-primary" @click=${this._onSubmit}>
            ${this._t("survey.submit")}
          </button>
        </div>
      </div>
    `;
  }

  _renderThanks() {
    return html`
      <div class="thanks-card">
        <div class="thanks-icon">
          <builtin-icon name="check" size="48" variant="outlined"></builtin-icon>
        </div>
        <h2 class="thanks-title">${this._t("survey.thanksTitle")}</h2>
        <p class="thanks-text">${this._t("survey.thanksText")}</p>
      </div>
    `;
  }

  render() {
    const pct = this._progressPercent();
    const body = this._completed
      ? this._renderThanks()
      : this.mode === "all"
      ? this._renderAll()
      : this._renderSingle();

    return html`
      <div class="survey-container">
        ${!this._completed
          ? html`
              <div class="progress-wrap">
                <div class="progress-track">
                  <div class="progress-fill" style="width: ${pct}%;"></div>
                </div>
                <span class="progress-text">${pct}%</span>
              </div>
            `
          : ""}
        ${body}
      </div>
    `;
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      .survey-container {
        max-width: 720px;
        margin: 0 auto;
        padding: 16px;
      }
      .progress-wrap {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 20px;
      }
      .progress-track {
        flex: 1;
        height: 8px;
        background: var(--builtin-border-soft);
        border-radius: 4px;
        overflow: hidden;
      }
      .progress-fill {
        height: 100%;
        background: var(--builtin-primary);
        transition: width 0.25s ease;
      }
      .progress-text {
        font-size: 12px;
        color: var(--builtin-color-muted);
        min-width: 36px;
        text-align: right;
      }
      .survey-body {
        display: flex;
        flex-direction: column;
        gap: 16px;
      }
      .question-card {
        background: var(--builtin-surface);
        border: 1px solid var(--builtin-border-soft);
        border-radius: var(--builtin-radius-lg, 8px);
        padding: 20px;
      }
      .question-header {
        display: flex;
        gap: 10px;
        align-items: flex-start;
        margin-bottom: 14px;
      }
      .question-number {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 26px;
        height: 26px;
        border-radius: 50%;
        background: var(--builtin-primary);
        color: #fff;
        font-size: 12px;
        font-weight: 700;
        flex-shrink: 0;
      }
      .question-text {
        font-size: 16px;
        line-height: 1.4;
        font-weight: 500;
      }
      .question-body {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .survey-input {
        width: 100%;
        padding: 12px 14px;
        border: 1px solid var(--builtin-border);
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-header-bg);
        color: var(--builtin-color-text);
        font-size: 15px;
        box-sizing: border-box;
      }
      .survey-input:focus {
        outline: 2px solid var(--builtin-primary);
        border-color: var(--builtin-primary);
      }
      textarea.survey-input {
        min-height: 100px;
        resize: vertical;
      }
      .touch-label {
        display: flex;
        align-items: center;
        gap: 12px;
        font-size: 15px;
        padding: 10px 0;
        color: var(--builtin-color-text);
        cursor: pointer;
      }
      .touch-label input[type="radio"],
      .touch-label input[type="checkbox"] {
        width: 22px;
        height: 22px;
        accent-color: var(--builtin-primary);
        flex-shrink: 0;
      }
      .rating-row {
        display: flex;
        gap: 6px;
      }
      .rating-btn {
        border: none;
        background: transparent;
        padding: 4px;
        cursor: pointer;
        color: var(--builtin-border);
      }
      .rating-btn.filled {
        color: #f59e0b;
      }
      .survey-actions {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        margin-top: 8px;
      }
      .btn {
        padding: 10px 18px;
        border: 1px solid var(--builtin-border);
        border-radius: var(--builtin-radius, 6px);
        background: var(--builtin-button-bg);
        color: var(--builtin-color-text);
        font-size: 14px;
        cursor: pointer;
      }
      .btn:hover:not(:disabled) {
        background: var(--builtin-button-hover-bg);
      }
      .btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }
      .btn-primary {
        background: var(--builtin-primary);
        color: #fff;
        border-color: transparent;
      }
      .btn-primary:hover:not(:disabled) {
        filter: brightness(1.1);
      }
      .thanks-card {
        text-align: center;
        background: var(--builtin-surface);
        border: 1px solid var(--builtin-border-soft);
        border-radius: var(--builtin-radius-lg, 8px);
        padding: 40px 24px;
      }
      .thanks-icon {
        font-size: 48px;
        color: var(--builtin-primary);
        margin-bottom: 12px;
        display: inline-flex;
      }
      .thanks-title {
        margin: 0 0 8px;
        font-size: 22px;
        color: var(--builtin-color-text);
      }
      .thanks-text {
        margin: 0;
        color: var(--builtin-color-muted);
        font-size: 15px;
      }
      @media (max-width: 720px) {
        .survey-container {
          padding: 12px;
        }
        .survey-actions {
          flex-direction: column;
        }
        .survey-actions .btn {
          width: 100%;
        }
        .question-card {
          padding: 16px;
          border-radius: var(--builtin-radius, 6px);
        }
        .touch-label {
          padding: 12px 0;
        }
        .touch-label input[type="radio"],
        .touch-label input[type="checkbox"] {
          width: 26px;
          height: 26px;
        }
      }
    `;
  }
}