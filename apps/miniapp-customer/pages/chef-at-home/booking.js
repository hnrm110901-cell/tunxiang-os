// 大厨到家预约确认 — 选时间 + 填地址 + 选人数
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    // 从首页传入
    dishes: [],
    chefId: '',
    chefName: '',
    chefTitle: '',
    totalDishFen: 0,
    // 表单
    date: '',
    today: '',
    timeSlots: ['11:00', '12:00', '17:00', '18:00', '19:00'],
    selectedTime: '',
    guestCount: 4,
    address: '',
    contactName: '',
    contactPhone: '',
    remark: '',
    // 价格明细
    priceDetail: null,
    loadingPrice: false,
    // 提交
    submitting: false,
  },

  onLoad: function () {
    var draft = wx.getStorageSync('chef_at_home_draft');
    if (!draft || !draft.dishes || draft.dishes.length === 0) {
      wx.showToast({ title: '请先选菜', icon: 'none' });
      wx.navigateBack();
      return;
    }

    var now = new Date();
    var tomorrow = new Date(now.getTime() + 86400000);
    var today = tomorrow.getFullYear() + '-' +
      String(tomorrow.getMonth() + 1).padStart(2, '0') + '-' +
      String(tomorrow.getDate()).padStart(2, '0');

    this.setData({
      dishes: draft.dishes,
      chefId: draft.chef_id,
      chefName: draft.chef_name,
      chefTitle: draft.chef_title,
      totalDishFen: draft.total_dish_fen,
      today: today,
    });
  },

  onDateChange: function (e) {
    this.setData({ date: e.detail.value });
    this._recalcPrice();
  },

  selectTime: function (e) {
    this.setData({ selectedTime: e.currentTarget.dataset.time });
    this._recalcPrice();
  },

  changeGuests: function (e) {
    var delta = Number(e.currentTarget.dataset.delta);
    var count = Math.max(1, Math.min(30, this.data.guestCount + delta));
    this.setData({ guestCount: count });
    this._recalcPrice();
  },

  onAddressInput: function (e) {
    this.setData({ address: e.detail.value });
  },

  onContactNameInput: function (e) {
    this.setData({ contactName: e.detail.value });
  },

  onContactPhoneInput: function (e) {
    this.setData({ contactPhone: e.detail.value });
  },

  onRemarkInput: function (e) {
    this.setData({ remark: e.detail.value });
  },

  chooseLocation: function () {
    var self = this;
    wx.chooseLocation({
      success: function (res) {
        self.setData({ address: res.address + (res.name ? ' ' + res.name : '') });
      },
    });
  },

  _recalcPrice: function () {
    var self = this;
    if (self.data.dishes.length === 0) return;

    self.setData({ loadingPrice: true });
    api.txRequest('/api/v1/chef-at-home/calculate-price', 'POST', {
      dishes: self.data.dishes,
      guest_count: self.data.guestCount,
      distance_km: 10,
    }).then(function (data) {
      self.setData({ priceDetail: data, loadingPrice: false });
    }).catch(function (err) {
      console.error('calcPrice failed', err);
      self.setData({ loadingPrice: false });
    });
  },

  submitBooking: function () {
    var self = this;
    var d = self.data;

    if (!d.date) { wx.showToast({ title: '请选择日期', icon: 'none' }); return; }
    if (!d.selectedTime) { wx.showToast({ title: '请选择时间', icon: 'none' }); return; }
    if (!d.address) { wx.showToast({ title: '请填写地址', icon: 'none' }); return; }
    if (!d.contactName) { wx.showToast({ title: '请填写联系人', icon: 'none' }); return; }
    if (!d.contactPhone) { wx.showToast({ title: '请填写联系电话', icon: 'none' }); return; }

    self.setData({ submitting: true });

    var serviceDatetime = d.date + 'T' + d.selectedTime + ':00';

    api.txRequest('/api/v1/chef-at-home/bookings', 'POST', {
      customer_id: wx.getStorageSync('tx_customer_id') || '',
      dishes: d.dishes,
      chef_id: d.chefId,
      service_datetime: serviceDatetime,
      address: d.address,
      guest_count: d.guestCount,
    }).then(function (booking) {
      wx.removeStorageSync('chef_at_home_draft');
      wx.showToast({ title: '预约成功', icon: 'success' });
      // 跳转到订单跟踪
      wx.redirectTo({
        url: '/pages/chef-at-home/order-tracking?booking_id=' + booking.id,
      });
    }).catch(function (err) {
      wx.showToast({ title: err.message || '预约失败', icon: 'none' });
      self.setData({ submitting: false });
    });
  },

  onShareAppMessage: function () {
    return { title: '徐记海鲜 · 大厨到家', path: '/pages/chef-at-home/index' };
  },
});
