// i18n 多语言工具 — ES5 风格
var zhLang = require('../i18n/zh');
var enLang = require('../i18n/en');
var jaLang = require('../i18n/ja');

var langs = { zh: zhLang, en: enLang, ja: jaLang };
var currentLang = wx.getStorageSync('tx_lang') || 'zh';

function t(key) {
  // 支持 'menu.add_to_cart' 点号分隔
  var parts = key.split('.');
  var result = langs[currentLang];
  for (var i = 0; i < parts.length; i++) {
    result = result && result[parts[i]];
  }
  return result || key; // 找不到返回 key 本身
}

function setLang(lang) {
  if (langs[lang]) {
    currentLang = lang;
    wx.setStorageSync('tx_lang', lang);
  }
}

function getLang() {
  return currentLang;
}

function getSupportedLangs() {
  return [
    { code: 'zh', label: '中文', labelNative: '中文' },
    { code: 'en', label: 'English', labelNative: 'English' },
    { code: 'ja', label: '日本語', labelNative: '日本語' }
  ];
}

module.exports = { t: t, setLang: setLang, getLang: getLang, getSupportedLangs: getSupportedLangs };
