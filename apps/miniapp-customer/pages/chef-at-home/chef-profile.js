// 厨师详情 + 预约表单（日历选日期 + 人数 + 地址 + 备注 + 确认预约）
var api = require('../../utils/api.js');

Page({
  data: {
    chefId: '',
    chef: null,
    loading: true,
    activeTab: 'intro', // intro / portfolio / booking / ratings

    // 日历相关
    weekdayHeaders: ['日', '一', '二', '三', '四', '五', '六'],
    currentYear: 0,
    currentMonth: 0,
    currentMonthLabel: '',
    calendarDays: [],
    availableDates: [],  // 从排期API获取的可预约日期列表
    loadingSchedule: false,

    // 预约表单
    bookingDate: '',
    bookingTime: '',
    timeSlots: ['10:00', '11:00', '12:00', '17:00', '18:00', '19:00'],
    guestCount: 2,
    serviceAddress: '',
    remark: '',
    submitting: false,
  },

  onLoad: function (options) {
    var now = new Date();
    this.setData({
      currentYear: now.getFullYear(),
      currentMonth: now.getMonth() + 1,
    });

    // 预填日期（来自首页筛选）
    if (options.date) {
      this.setData({ bookingDate: options.date });
    }

    // 预填地址
    var savedAddr = wx.getStorageSync('chef_service_address');
    if (savedAddr) {
      this.setData({ serviceAddress: savedAddr });
    }

    if (options.chef_id) {
      this.setData({ chefId: options.chef_id });
      this._loadChefProfile(options.chef_id);
    }
  },

  onShareAppMessage: function () {
    var chef = this.data.chef;
    var title = chef ? chef.name + ' · 大厨到家' : '大厨到家';
    return { title: title, path: '/pages/chef-at-home/chef-profile?chef_id=' + this.data.chefId };
  },

  // ─── 加载厨师详情 ───

  _loadChefProfile: function (chefId) {
    var self = this;
    self.setData({ loading: true });
    api.txRequest('/api/v1/chef-at-home/chefs/' + encodeURIComponent(chefId))
      .then(function (data) {
        self.setData({ chef: data, loading: false });
        // 加载当月排期
        self._loadSchedule(self.data.currentYear, self.data.currentMonth);
      })
      .catch(function (err) {
        console.error('loadChefProfile failed', err);
        wx.showToast({ title: '加载失败', icon: 'none' });
        self.setData({ loading: false });
      });
  },

  // ─── 加载厨师排期 ───

  _loadSchedule: function (year, month) {
    var self = this;
    var monthStr = year + '-' + String(month).padStart(2, '0');
    self.setData({ loadingSchedule: true });

    self._updateMonthLabel(year, month);

    api.txRequest('/api/v1/chef-at-home/chefs/' + encodeURIComponent(self.data.chefId) +
      '/schedule?month=' + encodeURIComponent(monthStr))
      .then(function (data) {
        var available = (data && data.available_dates) ? data.available_dates : [];
        self.setData({ availableDates: available, loadingSchedule: false });
        self._buildCalendar(year, month, available);
      })
      .catch(function (err) {
        console.error('loadSchedule failed', err);
        // 降级：展示空日历
        self.setData({ availableDates: [], loadingSchedule: false });
        self._buildCalendar(year, month, []);
      });
  },

  _updateMonthLabel: function (year, month) {
    this.setData({ currentMonthLabel: year + '年' + month + '月' });
  },

  _buildCalendar: function (year, month, availableDates) {
    // 获取当月第一天是周几
    var firstDay = new Date(year, month - 1, 1).getDay();
    var daysInMonth = new Date(year, month, 0).getDate();
    var today = new Date();
    var todayStr = today.getFullYear() + '-' +
      String(today.getMonth() + 1).padStart(2, '0') + '-' +
      String(today.getDate()).padStart(2, '0');

    var cells = [];
    // 填充前置空格
    for (var i = 0; i < firstDay; i++) {
      cells.push({ empty: true, date: '', dayNum: '', available: false });
    }
    // 填充日期
    for (var d = 1; d <= daysInMonth; d++) {
      var dateStr = year + '-' +
        String(month).padStart(2, '0') + '-' +
        String(d).padStart(2, '0');
      var isPast = dateStr <= todayStr;
      var isAvailable = !isPast && availableDates.indexOf(dateStr) >= 0;
      cells.push({
        empty: false,
        date: dateStr,
        dayNum: String(d),
        available: isAvailable,
      });
    }

    this.setData({
      currentYear: year,
      currentMonth: month,
      calendarDays: cells,
    });
  },

  // ─── 日历导航 ───

  prevMonth: function () {
    var year = this.data.currentYear;
    var month = this.data.currentMonth - 1;
    if (month < 1) { month = 12; year -= 1; }
    this._loadSchedule(year, month);
  },

  nextMonth: function () {
    var year = this.data.currentYear;
    var month = this.data.currentMonth + 1;
    if (month > 12) { month = 1; year += 1; }
    this._loadSchedule(year, month);
  },

  // ─── 日期选择 ───

  selectBookingDate: function (e) {
    var date = e.currentTarget.dataset.date;
    var available = e.currentTarget.dataset.available;
    if (!available || !date) {
      if (date) wx.showToast({ title: '该日期不可预约', icon: 'none' });
      return;
    }
    this.setData({ bookingDate: date });
  },

  // ─── 时间选择 ───

  selectBookingTime: function (e) {
    this.setData({ bookingTime: e.currentTarget.dataset.time });
  },

  // ─── 人数步进 ───

  changeGuests: function (e) {
    var delta = Number(e.currentTarget.dataset.delta);
    var count = Math.max(2, Math.min(30, this.data.guestCount + delta));
    this.setData({ guestCount: count });
  },

  // ─── 地址 ───

  onAddressInput: function (e) {
    this.setData({ serviceAddress: e.detail.value });
  },

  chooseLocation: function () {
    var self = this;
    wx.chooseLocation({
      success: function (res) {
        var addr = (res.address || '') + (res.name ? ' ' + res.name : '');
        self.setData({ serviceAddress: addr });
        wx.setStorageSync('chef_service_address', addr);
      },
    });
  },

  // ─── 备注 ───

  onRemarkInput: function (e) {
    this.setData({ remark: e.detail.value });
  },

  // ─── Tab 切换 ───

  switchTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    this.setData({ activeTab: tab });
    // 切换到预约Tab时加载排期
    if (tab === 'booking') {
      this._loadSchedule(this.data.currentYear, this.data.currentMonth);
    }
  },

  // ─── 图片预览 ───

  previewImage: function (e) {
    var url = e.currentTarget.dataset.url;
    var urls = (this.data.chef && this.data.chef.portfolio)
      ? this.data.chef.portfolio.map(function (p) { return p.image; })
      : [url];
    wx.previewImage({ current: url, urls: urls });
  },

  // ─── 确认预约 → 写入草稿 → 跳转booking页支付 ───

  confirmBooking: function () {
    var self = this;
    var d = self.data;

    if (!d.bookingDate) {
      wx.showToast({ title: '请选择服务日期', icon: 'none' }); return;
    }
    if (!d.bookingTime) {
      wx.showToast({ title: '请选择上门时间', icon: 'none' }); return;
    }
    if (!d.serviceAddress) {
      wx.showToast({ title: '请填写上门地址', icon: 'none' }); return;
    }

    // 草稿存缓存，booking页读取
    var draft = wx.getStorageSync('chef_at_home_draft') || {};
    draft.chef_id = d.chef.id;
    draft.chef_name = d.chef.name;
    draft.chef_title = d.chef.title;
    draft.service_date = d.bookingDate;
    draft.service_time = d.bookingTime;
    draft.service_datetime = d.bookingDate + 'T' + d.bookingTime + ':00';
    draft.guest_count = d.guestCount;
    draft.address = d.serviceAddress;
    draft.remark = d.remark;
    draft.base_fee_fen = d.chef.base_fee_fen || 0;
    wx.setStorageSync('chef_at_home_draft', draft);

    wx.navigateTo({ url: '/pages/chef-at-home/booking' });
  },
});
