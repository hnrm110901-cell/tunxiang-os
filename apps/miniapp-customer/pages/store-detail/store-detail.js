// 门店详情页
// API:
//   GET /api/v1/customer/stores/{store_id}  门店详情（营业时间/地址/电话/公告）
//   GET /api/v1/queue/summary?store_id=     排队情况
//   GET /api/v1/trade/booking/available-slots?store_id=&date=  今日预约时段

var app = getApp();
var api = require('../../utils/api.js');

// Mock 数据（API 失败时降级）
var MOCK_STORE = {
  id: 'demo-store',
  name: '屯象湘菜 · 五一广场旗舰店',
  logo: '',
  coverImage: '',
  phone: '0731-88888888',
  address: '湖南省长沙市芙蓉区五一大道123号',
  city: '长沙',
  latitude: 28.1941,
  longitude: 112.9836,
  rating: 4.8,
  reviewCount: 2356,
  monthlyOrders: 8800,
  distance: '0.8km',
  isOpen: true,
  businessHours: [
    { days: '周一至周五', hours: '11:00 - 21:30' },
    { days: '周六至周日', hours: '10:30 - 22:00' },
  ],
  tags: ['湘菜', '正餐', '停车场', 'WiFi', '刷卡'],
  notice: '节假日营业时间以门店公告为准，如有疑问请致电门店确认。',
  images: [],
  facilities: [
    { icon: 'car', label: '停车场' },
    { icon: 'wifi', label: 'WiFi' },
    { icon: 'card', label: '刷卡' },
    { icon: 'invoice', label: '可开发票' },
  ],
};

Page({
  data: {
    storeId: '',
    store: null,
    loading: true,

    // 排队状态
    queueSummary: null,

    // 今日预约剩余
    availableSlots: 0,

    // 图片预览索引
    currentImageIndex: 0,

    // 导航方式选择
    showNavPopup: false,
  },

  onLoad: function (options) {
    var storeId = options.store_id || options.id || app.globalData.storeId || '';
    this.setData({ storeId: storeId });
    this._loadStore(storeId);
    this._loadQueue(storeId);
    this._loadSlots(storeId);
  },

  onShow: function () {
    var storeId = this.data.storeId;
    if (storeId) {
      this._loadQueue(storeId);
    }
  },

  onPullDownRefresh: function () {
    var self = this;
    var storeId = self.data.storeId;
    Promise.all([
      self._loadStore(storeId),
      self._loadQueue(storeId),
      self._loadSlots(storeId),
    ]).then(function () {
      wx.stopPullDownRefresh();
    }).catch(function () {
      wx.stopPullDownRefresh();
    });
  },

  onShareAppMessage: function () {
    var store = this.data.store || {};
    return {
      title: store.name || '门店详情 - 屯象点餐',
      path: '/pages/store-detail/store-detail?store_id=' + this.data.storeId,
    };
  },

  // ─── 数据加载 ───

  _loadStore: function (storeId) {
    var self = this;
    if (!storeId) {
      self.setData({ store: MOCK_STORE, loading: false });
      return Promise.resolve();
    }

    return api.fetchStoreDetail(storeId)
      .then(function (data) {
        var store = self._formatStore(data);
        self.setData({ store: store, loading: false });
        // 更新页面标题
        wx.setNavigationBarTitle({ title: store.name });
      })
      .catch(function () {
        self.setData({ store: MOCK_STORE, loading: false });
      });
  },

  _formatStore: function (data) {
    var hours = data.business_hours || data.businessHours || [];
    // 如果 business_hours 是字符串数组，转换为对象
    if (hours.length > 0 && typeof hours[0] === 'string') {
      hours = [{ days: '营业时间', hours: hours.join(' / ') }];
    }

    var tags = data.tags || data.features || [];
    if (typeof tags === 'string') {
      tags = tags.split(',').map(function (t) { return t.trim(); });
    }

    var images = data.images || data.image_urls || [];
    if (images.length === 0 && data.cover_image) {
      images = [data.cover_image];
    }

    return {
      id: data.id || data.store_id || storeId,
      name: data.name || data.store_name || '',
      logo: data.logo_url || data.logo || '',
      coverImage: data.cover_image || (images[0] || ''),
      phone: data.phone || data.contact_phone || '',
      address: data.address || data.full_address || '',
      city: data.city || '',
      latitude: data.latitude || data.lat || 0,
      longitude: data.longitude || data.lng || 0,
      rating: data.rating || 4.8,
      reviewCount: data.review_count || 0,
      monthlyOrders: data.monthly_orders || 0,
      distance: data.distance ? (data.distance >= 1000 ? (data.distance / 1000).toFixed(1) + 'km' : data.distance + 'm') : '',
      isOpen: data.is_open !== false,
      businessHours: hours.length > 0 ? hours : MOCK_STORE.businessHours,
      tags: tags.length > 0 ? tags : MOCK_STORE.tags,
      notice: data.notice || data.announcement || '',
      images: images,
      facilities: data.facilities || MOCK_STORE.facilities,
    };
  },

  _loadQueue: function (storeId) {
    var self = this;
    if (!storeId) return Promise.resolve();

    return api.fetchQueueSummary(storeId)
      .then(function (data) {
        if (data && (data.waiting_count !== undefined || data.estimated_wait !== undefined)) {
          self.setData({
            queueSummary: {
              waitingCount: data.waiting_count || 0,
              estimatedWait: data.estimated_wait || 0,
              isOpen: data.is_open !== false,
            },
          });
        }
      })
      .catch(function () {
        // 排队信息不可用时静默失败
      });
  },

  _loadSlots: function (storeId) {
    var self = this;
    if (!storeId) return Promise.resolve();

    var today = new Date();
    var dateStr = today.getFullYear() + '-' +
      ('0' + (today.getMonth() + 1)).slice(-2) + '-' +
      ('0' + today.getDate()).slice(-2);

    return api.fetchAvailableSlots(storeId, dateStr)
      .then(function (data) {
        var slots = data.slots || data || [];
        var available = slots.filter(function (s) {
          return s.available_count > 0 || s.status === 'available';
        }).length;
        self.setData({ availableSlots: available });
      })
      .catch(function () {
        // 预约信息不可用时静默失败
      });
  },

  // ─── 操作 ───

  // 拨打电话
  callPhone: function () {
    var phone = this.data.store && this.data.store.phone;
    if (!phone) {
      wx.showToast({ title: '暂无电话信息', icon: 'none' });
      return;
    }
    wx.makePhoneCall({ phoneNumber: phone });
  },

  // 导航弹窗
  openNavPopup: function () {
    this.setData({ showNavPopup: true });
  },

  closeNavPopup: function () {
    this.setData({ showNavPopup: false });
  },

  // 打开地图导航
  openMap: function () {
    var store = this.data.store;
    if (!store || (!store.latitude && !store.longitude)) {
      wx.showToast({ title: '暂无位置信息', icon: 'none' });
      return;
    }
    this.setData({ showNavPopup: false });
    wx.openLocation({
      latitude: store.latitude,
      longitude: store.longitude,
      name: store.name,
      address: store.address,
    });
  },

  // 复制地址
  copyAddress: function () {
    var address = this.data.store && this.data.store.address;
    if (!address) return;
    wx.setClipboardData({
      data: address,
      success: function () {
        wx.showToast({ title: '地址已复制', icon: 'success' });
      },
    });
  },

  // 查看图片
  previewImage: function (e) {
    var index = e.currentTarget.dataset.index || 0;
    var images = (this.data.store && this.data.store.images) || [];
    if (images.length === 0) return;
    wx.previewImage({
      current: images[index],
      urls: images,
    });
  },

  // 去点餐
  goToMenu: function () {
    var storeId = this.data.storeId;
    if (storeId) {
      app.globalData.storeId = storeId;
    }
    wx.switchTab({ url: '/pages/menu/menu' });
  },

  // 去排队
  goToQueue: function () {
    wx.navigateTo({ url: '/pages/queue/queue?store_id=' + this.data.storeId });
  },

  // 去预约
  goToReservation: function () {
    wx.navigateTo({ url: '/pages/reservation/reservation?store_id=' + this.data.storeId });
  },

  // 查看评价
  goToReviews: function () {
    wx.navigateTo({ url: '/pages/reviews-list/reviews-list?store_id=' + this.data.storeId });
  },
});
