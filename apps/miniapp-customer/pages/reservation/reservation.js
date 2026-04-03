// 预订页 — 日历日期+午市晚市+30分钟间隔+人数+包厢+备注
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    activeTab: 'new',
    today: '',
    maxDate: '',
    date: '',
    // 午市/晚市切换
    mealPeriod: '',
    mealPeriods: [
      { label: '午市', value: 'lunch', icon: '\u2600\ufe0f' },
      { label: '晚市', value: 'dinner', icon: '\ud83c\udf19' },
    ],
    // 时间段（30分钟间隔）
    lunchSlots: ['11:00', '11:30', '12:00', '12:30', '13:00', '13:30'],
    dinnerSlots: ['17:00', '17:30', '18:00', '18:30', '19:00', '19:30', '20:00', '20:30'],
    currentSlots: [],
    selectedSlot: '',
    // 人数
    guests: 2,
    // 包厢选择
    roomOptions: [
      { label: '不限', value: 'any', icon: '' },
      { label: '大厅', value: 'hall', icon: '\ud83c\udfe0' },
      { label: '小包间', value: 'small', icon: '\ud83d\udeaa' },
      { label: '大包间', value: 'large', icon: '\ud83c\udfe2' },
    ],
    selectedRoom: 'any',
    // 备注快捷标签
    remarkTags: ['生日聚会', '商务宴请', '家庭聚餐', '朋友聚会', '婚宴', '其他'],
    selectedRemarkTag: '',
    remark: '',
    submitting: false,
    // 我的预订
    bookings: [],
  },

  onLoad: function () {
    var now = new Date();
    var today = this._formatDate(now);
    // 最多预订30天
    var max = new Date(now.getTime() + 30 * 24 * 3600 * 1000);
    var maxDate = this._formatDate(max);
    this.setData({ today: today, maxDate: maxDate });
  },

  onShow: function () {
    if (this.data.activeTab === 'list') {
      this.loadBookings();
    }
  },

  onShareAppMessage: function () {
    return { title: '屯象点餐 - 在线预订', path: '/pages/reservation/reservation' };
  },

  _formatDate: function (d) {
    return d.getFullYear() + '-' +
      String(d.getMonth() + 1).padStart(2, '0') + '-' +
      String(d.getDate()).padStart(2, '0');
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

  selectMealPeriod: function (e) {
    var period = e.currentTarget.dataset.period;
    var slots = period === 'lunch' ? this.data.lunchSlots : this.data.dinnerSlots;
    this.setData({
      mealPeriod: period,
      currentSlots: slots,
      selectedSlot: '',
    });
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

  selectRemarkTag: function (e) {
    var tag = e.currentTarget.dataset.tag;
    if (this.data.selectedRemarkTag === tag) {
      this.setData({ selectedRemarkTag: '', remark: '' });
    } else {
      this.setData({ selectedRemarkTag: tag, remark: tag });
    }
  },

  onRemarkInput: function (e) {
    this.setData({ remark: e.detail.value, selectedRemarkTag: '' });
  },

  submitBooking: function () {
    var self = this;
    var data = self.data;

    if (!data.date) { wx.showToast({ title: '请选择日期', icon: 'none' }); return; }
    if (!data.mealPeriod) { wx.showToast({ title: '请选择午市/晚市', icon: 'none' }); return; }
    if (!data.selectedSlot) { wx.showToast({ title: '请选择时间段', icon: 'none' }); return; }

    self.setData({ submitting: true });

    var timeSlot = data.selectedSlot;
    // 构造时间段字符串（如 "18:00-18:30"）
    var slotIdx = data.currentSlots.indexOf(timeSlot);
    var endSlot = slotIdx < data.currentSlots.length - 1 ? data.currentSlots[slotIdx + 1] : '';
    var timeSlotStr = endSlot ? timeSlot + '-' + endSlot : timeSlot;

    api.createBooking({
      store_id: app.globalData.storeId,
      customer_id: wx.getStorageSync('tx_customer_id') || '',
      date: data.date,
      time_slot: timeSlotStr,
      meal_period: data.mealPeriod,
      guests: data.guests,
      room_preference: data.selectedRoom,
      remark: data.remark,
    }).then(function (result) {
      wx.showToast({ title: '预订已提交，等待确认', icon: 'success', duration: 2000 });
      self.setData({
        date: '',
        mealPeriod: '',
        currentSlots: [],
        selectedSlot: '',
        guests: 2,
        selectedRoom: 'any',
        selectedRemarkTag: '',
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
      confirmColor: '#FF6B2C',
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
