/**
 * Energy Monitor — i18n engine
 * Čistě client-side, žádný kontakt s Flask/Jinja2.
 * Flash zprávy, Jinja2 proměnné a <pre>/<code> bloky se NIKDY nepřekládají.
 */

(function () {
  'use strict';

  const STORAGE_KEY = 'em-lang';
  const DEFAULT_LANG = 'cs';
  const SUPPORTED = ['cs', 'en'];

  // Překlady — načtou se lazy při prvním přepnutí na EN
  const _cache = { cs: null, en: null };

  function getLang() {
    try { return localStorage.getItem(STORAGE_KEY) || DEFAULT_LANG; } catch (e) { return DEFAULT_LANG; }
  }

  function setLang(lang) {
    if (!SUPPORTED.includes(lang)) return;
    try { localStorage.setItem(STORAGE_KEY, lang); } catch (e) {}
    applyLang(lang);
    updateSwitcher(lang);
    if (typeof window.onLangChange === 'function') { window.onLangChange(lang); }
  }

  // Získá hodnotu z JSON objektu podle tečkové cesty, např. "nav.dashboard"
  function resolve(obj, path) {
    return path.split('.').reduce(function (o, k) { return o && o[k] !== undefined ? o[k] : null; }, obj);
  }

  function applyTranslations(translations) {
    // Přelož všechny elementy s data-i18n atributem
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var key = el.getAttribute('data-i18n');
      var val = resolve(translations, key);
      if (val !== null) {
        // Bezpečně nastavíme pouze textContent — nikdy innerHTML
        // Pokud element obsahuje ikonu (bi), aktualizujeme jen textový uzel
        var iconEl = el.querySelector('i.bi');
        if (iconEl) {
          // Element má ikonu — najdeme textový uzel a aktualizujeme jen ten
          var textNodes = Array.from(el.childNodes).filter(function (n) {
            return n.nodeType === Node.TEXT_NODE;
          });
          if (textNodes.length > 0) {
            textNodes[textNodes.length - 1].textContent = ' ' + val;
          } else {
            el.appendChild(document.createTextNode(' ' + val));
          }
        } else {
          el.textContent = val;
        }
      }
    });

    // Přelož title atributy (tooltip)
    document.querySelectorAll('[data-i18n-title]').forEach(function (el) {
      var key = el.getAttribute('data-i18n-title');
      var val = resolve(translations, key);
      if (val !== null) el.setAttribute('title', val);
    });

    // Přelož placeholder atributy
    document.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
      var key = el.getAttribute('data-i18n-placeholder');
      var val = resolve(translations, key);
      if (val !== null) el.setAttribute('placeholder', val);
    });

    // Přelož innerHTML atributy (pro obsah s HTML tagy)
    document.querySelectorAll('[data-i18n-html]').forEach(function (el) {
      var key = el.getAttribute('data-i18n-html');
      var val = resolve(translations, key);
      if (val !== null) el.innerHTML = val;
    });
  }

  function applyLang(lang) {
    document.documentElement.setAttribute('lang', lang === 'cs' ? 'cs' : 'en');

    if (lang === 'cs' || lang === DEFAULT_LANG) {
      // Čeština — obnov originální texty ze data-i18n-cs atributů
      document.querySelectorAll('[data-i18n]').forEach(function (el) {
        var orig = el.getAttribute('data-i18n-cs');
        if (orig === null) return;
        var iconEl = el.querySelector('i.bi');
        if (iconEl) {
          var textNodes = Array.from(el.childNodes).filter(function (n) {
            return n.nodeType === Node.TEXT_NODE;
          });
          if (textNodes.length > 0) {
            textNodes[textNodes.length - 1].textContent = ' ' + orig;
          }
        } else {
          el.textContent = orig;
        }
      });
      // Obnov české placeholder hodnoty
      document.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
        var orig = el.getAttribute('data-i18n-placeholder-cs');
        if (orig !== null) el.setAttribute('placeholder', orig);
      });
      // Obnov české innerHTML (data-i18n-html)
      document.querySelectorAll('[data-i18n-html]').forEach(function (el) {
        var orig = el.getAttribute('data-i18n-html-cs');
        if (orig !== null) el.innerHTML = orig;
      });
      return;
    }

    // EN — načti JSON pokud není v cache
    if (_cache[lang]) {
      applyTranslations(_cache[lang]);
      return;
    }

    fetch('/static/lang/' + lang + '.json')
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        _cache[lang] = data;
        applyTranslations(data);
      })
      .catch(function (e) {
        console.warn('[i18n] Failed to load ' + lang + '.json:', e);
      });
  }

  function updateSwitcher(lang) {
    // Class-based approach (legacy)
    document.querySelectorAll('.lang-btn').forEach(function (btn) {
      btn.classList.toggle('lang-btn-active', btn.getAttribute('data-lang') === lang);
    });
    // ID-based approach (em-lang-cs / em-lang-en)
    ['cs', 'en'].forEach(function (l) {
      var el = document.getElementById('em-lang-' + l);
      if (!el) return;
      el.style.fontWeight     = (l === lang) ? '700' : '400';
      el.style.opacity        = (l === lang) ? '1'   : '0.5';
      el.style.textDecoration = (l === lang) ? 'underline' : 'none';
      el.style.color          = (l === lang) ? '#4f46e5' : '#6b7280';
    });
  }

  function init() {
    // Ulož originální české texty do data-i18n-cs atributů (jednou při inicializaci)
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      if (el.getAttribute('data-i18n-cs') !== null) return; // already saved
      var iconEl = el.querySelector('i.bi');
      if (iconEl) {
        var textNodes = Array.from(el.childNodes).filter(function (n) {
          return n.nodeType === Node.TEXT_NODE;
        });
        if (textNodes.length > 0) {
          el.setAttribute('data-i18n-cs', textNodes[textNodes.length - 1].textContent.trim());
        }
      } else {
        el.setAttribute('data-i18n-cs', el.textContent.trim());
      }
    });

    // Ulož originální české placeholder hodnoty
    document.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
      if (el.getAttribute('data-i18n-placeholder-cs') !== null) return;
      el.setAttribute('data-i18n-placeholder-cs', el.getAttribute('placeholder') || '');
    });
    // Ulož originální české innerHTML hodnoty (pro data-i18n-html)
    document.querySelectorAll('[data-i18n-html]').forEach(function (el) {
      if (el.getAttribute('data-i18n-html-cs') !== null) return;
      el.setAttribute('data-i18n-html-cs', el.innerHTML.trim());
    });

    var lang = getLang();
    updateSwitcher(lang);
    if (lang !== DEFAULT_LANG) {
      applyLang(lang);
    }
  }

  // Public API
  // JS i18n helper — use window._t('key') in scripts
  window._t = function(key) {
    var lang = getLang();
    if (lang === 'cs' || lang === DEFAULT_LANG) return null; // return null = use hardcoded CZ
    if (_cache[lang]) {
      var val = resolve(_cache[lang], key);
      return val !== null ? val : null;
    }
    return null; // not loaded yet
  };

  window.emI18n = {
    setLang: setLang,
    getLang: getLang
  };

  // Spusť po načtení DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
