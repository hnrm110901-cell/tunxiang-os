// TunxiangOS 微信小程序 — 顾客端
App({
  globalData: {
    apiBase: 'https://api.tunxiangos.com',  // 云端 Gateway
    tenantId: '',
    storeId: '',
    userInfo: null,
    openId: '',
  },

  onLaunch() {
    // 扫码进入时获取门店信息
    const scene = decodeURIComponent(this.globalData.scene || '');
    if (scene) {
      const params = new URLSearchParams(scene);
      this.globalData.storeId = params.get('store_id') || '';
      this.globalData.tenantId = params.get('tenant_id') || '';
    }
  },
});
