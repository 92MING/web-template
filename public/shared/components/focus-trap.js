/**
 * @fileoverview Focus trap utilities for modals, drawers, and popovers.
 *
 * Exports:
 * - trapFocus(container, options?)
 * - releaseFocus()
 * - FocusTrapMixin(Base)
 */

const TABBABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'textarea:not([disabled])',
  'select:not([disabled])',
  'details',
  'summary',
  '[tabindex]:not([tabindex="-1"])',
].join(', ');

let _lastFocus = null;
let _container = null;
let _options = {};

function _getTabbable(container) {
  const list = Array.from(container.querySelectorAll(TABBABLE_SELECTOR)).filter((el) => {
    return el.offsetParent !== null && !el.closest('inert');
  });
  return list;
}

function _onKeyDown(e) {
  if (e.key !== 'Tab' || !_container) return;
  const tabbable = _getTabbable(_container);
  if (tabbable.length === 0) {
    e.preventDefault();
    return;
  }
  const first = tabbable[0];
  const last = tabbable[tabbable.length - 1];
  if (e.shiftKey) {
    if (document.activeElement === first || !_container.contains(document.activeElement)) {
      e.preventDefault();
      last.focus();
    }
  } else {
    if (document.activeElement === last || !_container.contains(document.activeElement)) {
      e.preventDefault();
      first.focus();
    }
  }
}

function _onEscape(e) {
  if (e.key === 'Escape' && _container && _options.escapeCloses !== false) {
    if (typeof _options.onEscape === 'function') {
      _options.onEscape(e);
    }
  }
}

/**
 * Trap focus inside a container.
 *
 * @param {HTMLElement} container
 * @param {{escapeCloses?: boolean, onEscape?: (e: KeyboardEvent) => void}} [options]
 */
export function trapFocus(container, options = {}) {
  if (!container) return;
  releaseFocus();
  _lastFocus = document.activeElement;
  _container = container;
  _options = options;
  document.addEventListener('keydown', _onKeyDown, true);
  if (options.escapeCloses !== false) {
    document.addEventListener('keydown', _onEscape, true);
  }
  const tabbable = _getTabbable(container);
  if (tabbable.length) {
    const toFocus = tabbable.find((el) => el.dataset.autofocus === 'true') || tabbable[0];
    toFocus.focus();
  }
}

/** Release the focus trap and restore previous focus. */
export function releaseFocus() {
  document.removeEventListener('keydown', _onKeyDown, true);
  document.removeEventListener('keydown', _onEscape, true);
  _container = null;
  _options = {};
  if (_lastFocus && _lastFocus.focus) {
    _lastFocus.focus();
    _lastFocus = null;
  }
}

/**
 * Mixin that adds focus-trap lifecycle methods to a LitElement.
 *
 * @param {typeof HTMLElement} Base
 * @returns {typeof HTMLElement}
 */
export const FocusTrapMixin = (Base) => class extends Base {
  /**
   * @param {HTMLElement} container
   * @param {{escapeCloses?: boolean, onEscape?: (e: KeyboardEvent) => void}} [options]
   */
  trapFocus(container, options = {}) {
    trapFocus(container, options);
  }

  releaseFocus() {
    releaseFocus();
  }
};
