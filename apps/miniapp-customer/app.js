// TunxiangOS 微信小程序 — 顾客端 v1
//
// ⚠️ DEPRECATED (2026-05-06, sprint-0-dedup R7)
// 本项目已被 apps/miniapp-customer-v2 (Taro + TypeScript) 取代。
// 维护策略：仅安全补丁 + 已合作客户 bug 修复。新功能请去 v2。
// 详见 ./README.md
var auth = require('./utils/auth.js');
var config = require('./utils/config.js');

App({
  globalData: {
    apiBase: config.apiBase,
    tenantId: '',
    storeId: '',
    userInfo: null,
    openId: '',
    customerId: '',
    token: '',
    scene: '',
  },

  onLaunch(options) {
    // 恢复缓存的登录态
    this.globalData.token = auth.getToken();
    this.globalData.customerId = auth.getCustomerId();
    this.globalData.openId = wx.getStorageSync('tx_open_id') || '';

    // 扫码进入时获取门店信息
    if (options && options.query && options.query.scene) {
      this.globalData.scene = decodeURIComponent(options.query.scene);
    }
    var scene = this.globalData.scene || '';
    if (scene) {
      this._parseScene(scene);
    }

    // 静默登录
    if (!auth.isLoggedIn()) {
      auth.silentLogin().catch(function (err) {
        console.warn('静默登录失败', err);
      });
    }
  },

  /**
   * 解析扫码场景参数
   * 支持格式: store_id=xxx&tenant_id=yyy&table=zzz
   */
  _parseScene: function (scene) {
    try {
      var pairs = scene.split('&');
      var params = {};
      for (var i = 0; i < pairs.length; i++) {
        var kv = pairs[i].split('=');
        if (kv.length === 2) {
          params[kv[0]] = kv[1];
        }
      }
      if (params.store_id) this.globalData.storeId = params.store_id;
      if (params.tenant_id) this.globalData.tenantId = params.tenant_id;
    } catch (e) {
      console.error('解析场景参数失败', e);
    }
  },
});
