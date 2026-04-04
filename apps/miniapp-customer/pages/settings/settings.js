// 设置页 — 语言切换 / 清除缓存 / 关于我们
var i18n = require('../../utils/i18n.js');
var t = i18n.t;

Page({
  data: {
    langs: [],
    currentLang: '',
    version: '1.0.0',
    // i18n 文案
    txt: {}
  },

  onLoad: function () {
    this._refreshTexts();
  },

  _refreshTexts: function () {
    var lang = i18n.getLang();
    this.setData({
      langs: i18n.getSupportedLangs(),
      currentLang: lang,
      txt: {
        title: t('settings.title'),
        language: t('settings.language'),
        clear_cache: t('settings.clear_cache'),
        about: t('settings.about'),
        version: t('settings.version')
      }
    });
    wx.setNavigationBarTitle({ title: t('settings.title') });
  },

  onSelectLang: function (e) {
    var code = e.currentTarget.dataset.code;
    if (code === this.data.currentLang) return;

    var self = this;
    wx.showModal({
      title: t('common.confirm'),
      content: t('settings.switch_lang_confirm'),
      confirmText: t('common.confirm'),
      cancelText: t('common.cancel'),
      success: function (res) {
        if (res.confirm) {
          i18n.setLang(code);
          wx.reLaunch({ url: '/pages/index/index' });
        }
      }
    });
  },

  onClearCache: function () {
    wx.showModal({
      title: t('common.confirm'),
      content: t('settings.clear_cache_confirm'),
      confirmText: t('common.confirm'),
      cancelText: t('common.cancel'),
      success: function (res) {
        if (res.confirm) {
          var lang = wx.getStorageSync('tx_lang');
          wx.clearStorageSync();
          if (lang) {
            wx.setStorageSync('tx_lang', lang);
          }
          wx.showToast({ title: t('settings.clear_success'), icon: 'success' });
        }
      }
    });
  },

  onAbout: function () {
    wx.showModal({
      title: t('settings.about'),
      content: '屯象OS v' + this.data.version + '\n屯象科技（长沙）',
      showCancel: false,
      confirmText: t('common.confirm')
    });
  }
});
