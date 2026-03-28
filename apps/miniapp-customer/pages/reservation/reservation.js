// 预订页 — 日期+时段+人数+包厢选择
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    activeTab: 'new',
    today: '',
    date: '',
    timeSlots: ['11:00-12:00', '12:00-13:00', '17:00-18:00', '18:00-19:00', '19:00-20:00'],
    selectedSlot: '',
    guests: 2,
    roomOptions: [
      { label: '不限', value: 'any' },
      { label: '大厅', value: 'hall' },
      { label: '小包间', value: 'small' },
      { label: '大包间', value: 'large' },
    ],
    selectedRoom: 'any',
    remark: '',
    submitting: false,
    bookings: [],
  },

  onLoad: function () {
    var now = new Date();
    var today = now.getFullYear() + '-' +
      String(now.getMonth() + 1).padStart(2, '0') + '-' +
      String(now.getDate()).padStart(2, '0');
    this.setData({ today: today });
  },

  onShow: function () {
    if (this.data.activeTab === 'list') {
      this.loadBookings();
    }
  },

  onShareAppMessage: function () {
    return { title: '屯象点餐 - 在线预订', path: '/pages/reservation/reservation' };
  },

  switchTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    this.setData({ activeTab: tab });
    if (tab === 'list') {
      this.loadBookings();
    }
  },

  onDateChange: function (e) {
    this.setData({ date: e.detail.value });
  },

  selectSlot: function (e) {
    this.setData({ selectedSlot: e.currentTarget.dataset.slot });
  },

  changeGuests: function (e) {
    var delta = Number(e.currentTarget.dataset.delta);
    var guests = Math.max(1, Math.min(30, this.data.guests + delta));
    this.setData({ guests: guests });
  },

  selectRoom: function (e) {
    this.setData({ selectedRoom: e.currentTarget.dataset.room });
  },

  onRemarkInput: function (e) {
    this.setData({ remark: e.detail.value });
  },

  submitBooking: function () {
    var self = this;
    var data = self.data;

    if (!data.date) { wx.showToast({ title: '请选择日期', icon: 'none' }); return; }
    if (!data.selectedSlot) { wx.showToast({ title: '请选择时段', icon: 'none' }); return; }

    self.setData({ submitting: true });

    api.createBooking({
      store_id: app.globalData.storeId,
      customer_id: wx.getStorageSync('tx_customer_id') || '',
      date: data.date,
      time_slot: data.selectedSlot,
      guests: data.guests,
      room_preference: data.selectedRoom,
      remark: data.remark,
    }).then(function () {
      wx.showToast({ title: '预订成功', icon: 'success' });
      self.setData({
        date: '',
        selectedSlot: '',
        guests: 2,
        selectedRoom: 'any',
        remark: '',
        submitting: false,
        activeTab: 'list',
      });
      self.loadBookings();
    }).catch(function (err) {
      wx.showToast({ title: err.message || '预订失败', icon: 'none' });
      self.setData({ submitting: false });
    });
  },

  loadBookings: function () {
    var self = this;
    api.fetchBookings()
      .then(function (data) {
        var statusMap = { confirmed: '已确认', pending: '待确认', cancelled: '已取消', completed: '已完成' };
        var roomMap = { any: '不限', hall: '大厅', small: '小包间', large: '大包间' };
        var bookings = (data.items || []).map(function (b) {
          return {
            id: b.id,
            date: b.date,
            timeSlot: b.time_slot,
            guests: b.guests,
            status: b.status,
            statusText: statusMap[b.status] || b.status,
            roomLabel: roomMap[b.room_preference] || b.room_preference,
            remark: b.remark || '',
          };
        });
        self.setData({ bookings: bookings });
      })
      .catch(function (err) {
        console.error('loadBookings failed', err);
      });
  },

  cancelBooking: function (e) {
    var self = this;
    var id = e.currentTarget.dataset.id;

    wx.showModal({
      title: '提示',
      content: '确定取消此预订？',
      success: function (res) {
        if (!res.confirm) return;
        api.cancelBooking(id)
          .then(function () {
            wx.showToast({ title: '已取消', icon: 'success' });
            self.loadBookings();
          })
          .catch(function (err) {
            wx.showToast({ title: '取消失败', icon: 'none' });
          });
      },
    });
  },
});
