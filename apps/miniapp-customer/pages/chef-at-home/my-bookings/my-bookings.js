// 我的预约列表页
// API: GET /api/v1/trade/chef-at-home/bookings?customer_id=
//      PUT /api/v1/trade/chef-at-home/bookings/{id}/cancel
var api = require('../../../utils/api.js');

// Mock 预约数据（4条，涵盖不同状态）
var MOCK_BOOKINGS = [
  {
    id: 'bk-mock-001-abcdef',
    chef_id: 'mock-chef-001',
    chef_name: '陈师傅',
    chef_title: '粤菜行政总厨',
    chef_phone: '13800138001',
    status: 'pending',
    status_label: '待确认',
    service_datetime: '2026-04-05T18:00:00',
    service_date_display: '04月05日 (周日) 晚上 17:00-21:00',
    address: '湖南省长沙市雨花区某小区1栋2单元301室',
    guest_count: 8,
    estimated_total_fen: 120000,
    deposit_fen: 24000,
  },
  {
    id: 'bk-mock-002-ghijkl',
    chef_id: 'mock-chef-002',
    chef_name: '张大厨',
    chef_title: '川菜技术总监',
    chef_phone: '13800138002',
    status: 'confirmed',
    status_label: '已确认',
    service_datetime: '2026-04-08T14:00:00',
    service_date_display: '04月08日 (周三) 下午 14:00-17:00',
    address: '长沙市芙蓉区某商务公寓',
    guest_count: 12,
    estimated_total_fen: 200000,
    deposit_fen: 40000,
  },
  {
    id: 'bk-mock-003-mnopqr',
    chef_id: 'mock-chef-001',
    chef_name: '陈师傅',
    chef_title: '粤菜行政总厨',
    chef_phone: '13800138001',
    status: 'completed',
    status_label: '已完成',
    service_datetime: '2026-03-25T18:00:00',
    service_date_display: '03月25日 (周三) 晚上 17:00-21:00',
    address: '长沙市天心区某别墅',
    guest_count: 6,
    estimated_total_fen: 95000,
    deposit_fen: 19000,
  },
  {
    id: 'bk-mock-004-stuvwx',
    chef_id: 'mock-chef-002',
    chef_name: '张大厨',
    chef_title: '川菜技术总监',
    chef_phone: '',
    status: 'cancelled',
    status_label: '已取消',
    service_datetime: '2026-03-20T10:00:00',
    service_date_display: '03月20日 (周五) 上午 10:00-12:00',
    address: '长沙市岳麓区某小区',
    guest_count: 4,
    estimated_total_fen: 50000,
    deposit_fen: 0,
  },
];

var STATUS_LABEL_MAP = {
  pending: '待确认',
  confirmed: '已确认',
  in_service: '服务中',
  completed: '已完成',
  cancelled: '已取消',
};

Page({
  data: {
    tabs: [
      { key: 'pending', label: '待确认' },
      { key: 'confirmed', label: '已确认' },
      { key: 'completed', label: '已完成' },
      { key: 'cancelled', label: '已取消' },
    ],
    activeTab: 'pending',
    currentTabLabel: '待确认',

    allBookings: [],
    filteredBookings: [],
    pendingCount: 0,

    loading: false,

    // 取消确认
    cancelConfirmId: '',
    cancelling: false,
  },

  onLoad: function () {
    this._loadBookings();
  },

  onShow: function () {
    // 每次显示页面时刷新（从预约成功返回时）
    this._loadBookings();
  },

  onShareAppMessage: function () {
    return { title: '大厨到家 — 我的预约', path: '/pages/chef-at-home/my-bookings/my-bookings' };
  },

  // ─── 加载预约列表 ───

  _loadBookings: function () {
    var self = this;
    var customerId = wx.getStorageSync('tx_customer_id') || '';
    self.setData({ loading: true });

    api.txRequest('/api/v1/trade/chef-at-home/bookings?customer_id=' + encodeURIComponent(customerId))
      .then(function (data) {
        var bookings = (data && Array.isArray(data)) ? data : (data && data.items ? data.items : []);
        bookings = bookings.map(function (b) { return self._normalizeBooking(b); });
        self._setBookings(bookings);
        self.setData({ loading: false });
      })
      .catch(function (err) {
        console.warn('[my-bookings] loadBookings failed, using mock', err);
        var mocked = MOCK_BOOKINGS.map(function (b) { return self._normalizeBooking(b); });
        self._setBookings(mocked);
        self.setData({ loading: false });
      });
  },

  _normalizeBooking: function (b) {
    return Object.assign({}, b, {
      status_label: b.status_label || STATUS_LABEL_MAP[b.status] || b.status,
      estimated_total_fen: b.estimated_total_fen || 0,
      deposit_fen: b.deposit_fen || 0,
    });
  },

  _setBookings: function (bookings) {
    var pending = bookings.filter(function (b) { return b.status === 'pending'; });
    this.setData({
      allBookings: bookings,
      pendingCount: pending.length,
    });
    this._filterByTab(this.data.activeTab);
  },

  _filterByTab: function (tab) {
    var all = this.data.allBookings;
    var filtered;
    if (tab === 'pending') {
      filtered = all.filter(function (b) { return b.status === 'pending'; });
    } else if (tab === 'confirmed') {
      filtered = all.filter(function (b) { return b.status === 'confirmed' || b.status === 'in_service'; });
    } else if (tab === 'completed') {
      filtered = all.filter(function (b) { return b.status === 'completed'; });
    } else {
      filtered = all.filter(function (b) { return b.status === 'cancelled'; });
    }
    var labelMap = { pending: '待确认', confirmed: '已确认', completed: '已完成', cancelled: '已取消' };
    this.setData({ filteredBookings: filtered, currentTabLabel: labelMap[tab] || tab });
  },

  // ─── Tab 切换 ───

  switchTab: function (e) {
    var key = e.currentTarget.dataset.key;
    this.setData({ activeTab: key, cancelConfirmId: '' });
    this._filterByTab(key);
  },

  // ─── 联系大厨 ───

  callChef: function (e) {
    var phone = e.currentTarget.dataset.phone;
    if (!phone) {
      wx.showToast({ title: '暂无联系电话', icon: 'none' }); return;
    }
    wx.makePhoneCall({
      phoneNumber: phone,
      fail: function () {
        wx.showToast({ title: '拨号失败', icon: 'none' });
      },
    });
  },

  // ─── 取消预约（Popconfirm） ───

  showCancelConfirm: function (e) {
    var id = e.currentTarget.dataset.id;
    this.setData({ cancelConfirmId: id });
  },

  hideCancelConfirm: function () {
    this.setData({ cancelConfirmId: '' });
  },

  confirmCancel: function (e) {
    var self = this;
    var id = e.currentTarget.dataset.id;
    if (self.data.cancelling) return;
    self.setData({ cancelling: true });

    api.txRequest('/api/v1/trade/chef-at-home/bookings/' + encodeURIComponent(id) + '/cancel', 'PUT')
      .then(function () {
        wx.showToast({ title: '已取消预约', icon: 'success' });
        self.setData({ cancelling: false, cancelConfirmId: '' });
        // 本地更新状态
        var updated = self.data.allBookings.map(function (b) {
          if (b.id === id) {
            return Object.assign({}, b, { status: 'cancelled', status_label: '已取消' });
          }
          return b;
        });
        var pending = updated.filter(function (b) { return b.status === 'pending'; });
        self.setData({ allBookings: updated, pendingCount: pending.length });
        self._filterByTab(self.data.activeTab);
      })
      .catch(function (err) {
        self.setData({ cancelling: false });
        var msg = (err && err.message) ? err.message : '取消失败，请重试';
        wx.showToast({ title: msg, icon: 'none', duration: 3000 });
      });
  },

  // ─── 前往大厨列表 ───

  goToChefList: function () {
    wx.navigateTo({ url: '/pages/chef-at-home/index' });
  },

  // ─── 前往订单跟踪 ───

  goToOrderTracking: function (e) {
    var id = e.currentTarget.dataset.id;
    wx.navigateTo({
      url: '/pages/chef-at-home/order-tracking?booking_id=' + encodeURIComponent(id),
    });
  },
});
