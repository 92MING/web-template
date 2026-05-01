import { BuiltinBaseElement, html, css, classMap, styleMap, repeat, nothing } from "../../components/lit-base.js";

const jsonConverter = {
  fromAttribute(value) { if (!value) return undefined; try { return JSON.parse(value); } catch { return undefined; } },
  toAttribute(value) { return JSON.stringify(value); }
};

/**
 * @fileoverview BuiltinTplContactUs - Contact page with info, form, map, FAQ.
 *
 * @attr {string} address - Physical address.
 * @attr {string} phone - Phone number.
 * @attr {string} email - Email address.
 * @attr {string} hours - Business hours.
 * @attr {string} contactInfo - JSON object with {address, phone, email, hours}.
 * @attr {string} mapEmbedUrl - URL for embedded map iframe.
 * @attr {string} faq - JSON array of {question, answer}.
 * @attr {string} labels - JSON i18n overrides.
 */
export class BuiltinTplContactUs extends BuiltinBaseElement {
  static properties = {
    address: { type: String },
    phone: { type: String },
    email: { type: String },
    hours: { type: String },
    contactInfo: { type: Object, converter: jsonConverter },
    mapEmbedUrl: { type: String },
    faq: { type: Array },
    labels: { type: Object, converter: jsonConverter },
      };

  static styles = css`
    :host { display: block; }
    .hero { padding: 60px 20px; text-align: center; background: var(--builtin-header-bg, #f9fafb); border-bottom: 1px solid var(--builtin-border-soft, #e5e7eb); }
    .hero h1 { font-size: clamp(26px, 4vw, 38px); font-weight: 800; margin: 0 0 10px; color: var(--builtin-color-text, #111827); }
    .hero p { color: var(--builtin-color-muted, #6b7280); margin: 0; }
    .container { max-width: 1100px; margin: 0 auto; padding: 40px 20px; }
    .layout { display: grid; grid-template-columns: 1fr 1.2fr; gap: 32px; }
    .info-card {
      display: flex; flex-direction: column; gap: 18px;
      border: 1px solid var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius-lg, 8px); padding: 24px;
      background: var(--builtin-surface, #ffffff); height: fit-content;
    }
    .info-row { display: flex; align-items: flex-start; gap: 12px; }
    .info-row builtin-icon { color: var(--builtin-primary, #2563eb); margin-top: 2px; }
    .info-row .t { font-weight: 650; font-size: 14px; color: var(--builtin-color-text, #111827); }
    .info-row .d { font-size: 13px; color: var(--builtin-color-muted, #6b7280); margin-top: 2px; }
    .map { height: 200px; border: 2px dashed var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius, 6px); display: flex; align-items: center; justify-content: center; color: var(--builtin-color-muted, #6b7280); font-size: 13px; overflow: hidden; }
    .map iframe { width: 100%; height: 100%; border: 0; border-radius: var(--builtin-radius, 6px); }
    .map-placeholder { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; }
    .form-wrap { border: 1px solid var(--builtin-border-soft, #e5e7eb); border-radius: var(--builtin-radius-lg, 8px); padding: 24px; background: var(--builtin-surface, #ffffff); }
    .field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
    .field label { font-size: 13px; font-weight: 600; color: var(--builtin-color-text, #111827); }
    .field input, .field textarea {
      padding: 10px 12px; border: 1px solid var(--builtin-border, #d1d5db); border-radius: var(--builtin-radius, 6px);
      background: var(--builtin-input-bg, #ffffff); color: var(--builtin-color-text, #111827); font: inherit;
    }
    .faq { margin-top: 40px; }
    .faq h2 { font-size: 20px; font-weight: 700; margin-bottom: 16px; color: var(--builtin-color-text, #111827); }
    @media (max-width: 720px) {
      .layout { grid-template-columns: 1fr; }
    }
  `;

  _defaultContactInfo() {
    return {
      address: "123 Innovation Drive, Tech City, TC 12345",
      phone: "+1 (555) 123-4567",
      email: "hello@example.com",
      hours: "Mon-Fri 9:00-18:00",
    };
  }

  _getContactInfo() {
    if (this.contactInfo) return this.contactInfo;
    return this._defaultContactInfo();
    return {
      address: this.address || "",
      phone: this.phone || "",
      email: this.email || "",
      hours: this.hours || "",
    };
  }

  _on_submit = (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const data = {
      name: fd.get("name") || "",
      email: fd.get("email") || "",
      subject: fd.get("subject") || "",
      message: fd.get("message") || "",
    };
    this.dispatchEvent(new CustomEvent("builtin-contact-submit", { bubbles: true, composed: true, detail: data }));
  }

  render() {
    const info = this._getContactInfo();
    const faqItems = this.faq || [];
    return html`
      <builtin-navbar items='[]'></builtin-navbar>
      <section class="hero">
        <h1>${this._l("contact.title", "Contact Us")}</h1>
        <p>${this._l("contact.subtitle", "We'd love to hear from you. Send us a message and we'll respond as soon as possible.")}</p>
      </section>
      <div class="container">
        <div class="layout">
          <div class="info-card">
            <div class="info-row">
              <builtin-icon name="environment" size="20" variant="outlined"></builtin-icon>
              <div><div class="t">${this._l("contact.address", "Address")}</div><div class="d">${info.address || ""}</div></div>
            </div>
            <div class="info-row">
              <builtin-icon name="phone" size="20" variant="outlined"></builtin-icon>
              <div><div class="t">${this._l("contact.phone", "Phone")}</div><div class="d">${info.phone || ""}</div></div>
            </div>
            <div class="info-row">
              <builtin-icon name="mail" size="20" variant="outlined"></builtin-icon>
              <div><div class="t">${this._l("contact.email", "Email")}</div><div class="d">${info.email || ""}</div></div>
            </div>
            <div class="info-row">
              <builtin-icon name="clock-circle" size="20" variant="outlined"></builtin-icon>
              <div><div class="t">${this._l("contact.hours", "Business Hours")}</div><div class="d">${info.hours || ""}</div></div>
            </div>
            <div class="map">
              ${this.mapEmbedUrl
                ? html`<iframe src="${this.mapEmbedUrl}" allowfullscreen="" loading="lazy" referrerpolicy="no-referrer-when-downgrade"></iframe>`
                : html`<slot name="map"><div class="map-placeholder">${this._l("contact.mapPlaceholder", "Map Placeholder")}</div></slot>`
              }
            </div>
          </div>
          <form class="form-wrap" @submit="${this._on_submit}">
            <div class="field">
              <label>${this._l("contact.name", "Name")}</label>
              <input name="name" type="text" placeholder="${this._l("contact.placeholderName", "Your name")}" required />
            </div>
            <div class="field">
              <label>${this._l("contact.email", "Email")}</label>
              <input name="email" type="email" placeholder="${this._l("contact.placeholderEmail", "you@example.com")}" required />
            </div>
            <div class="field">
              <label>${this._l("contact.subject", "Subject")}</label>
              <input name="subject" type="text" placeholder="${this._l("contact.placeholderSubject", "How can we help?")}" />
            </div>
            <div class="field">
              <label>${this._l("contact.message", "Message")}</label>
              <textarea name="message" rows="5" placeholder="${this._l("contact.placeholderMessage", "Your message...")}" required></textarea>
            </div>
            <button type="submit" class="builtin-primary">${this._l("contact.send", "Send Message")}</button>
          </form>
        </div>
        ${faqItems.length > 0 ? html`
          <div class="faq">
            <h2>${this._l("contact.faq", "Frequently Asked Questions")}</h2>
            <builtin-accordion items='${JSON.stringify(faqItems.map((f) => ({ title: f.question, content: f.answer })))}'></builtin-accordion>
          </div>
        ` : nothing}
      </div>
      <builtin-footer></builtin-footer>
    `;
  }
}