(function(global) {
  'use strict';

  function toNumber(value, fallback) {
    const num = Number(value);
    return Number.isFinite(num) ? num : (fallback ?? 0);
  }

  function clampPercent(value) {
    return Math.max(0, Math.min(100, toNumber(value, 0)));
  }

  function formatPercent(value, digits) {
    const num = toNumber(value, 0);
    return `${num.toFixed(digits == null ? 1 : digits)}%`;
  }

  function percentTone(value) {
    const pct = clampPercent(value);
    return pct < 60 ? 'ok' : pct < 80 ? 'warn' : 'danger';
  }

  function percentToneClass(value) {
    const tone = percentTone(value);
    return tone === 'ok'
      ? 'monitor-meter-fill-ok'
      : tone === 'warn'
        ? 'monitor-meter-fill-warn'
        : 'monitor-meter-fill-danger';
  }

  function statusKindForPercent(value) {
    const tone = percentTone(value);
    return tone === 'ok' ? 'success' : tone === 'warn' ? 'warn' : 'error';
  }

  function formatHistoryLabel(value) {
    const date = value ? new Date(value) : new Date();
    if (Number.isNaN(date.getTime())) return String(value || '');
    return date.toLocaleTimeString('zh-CN', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  }

  global.ProjPanelMonitoring = {
    toNumber,
    clampPercent,
    formatPercent,
    percentTone,
    percentToneClass,
    statusKindForPercent,
    formatHistoryLabel,
  };
})(window);