// 签到打卡页 — 每日签到得5积分，连续签到有额外奖励
var app = getApp();
var api = require('../../utils/api.js');

var REWARD_MILESTONES = [
  { days: 3,  icon: '🎁', desc: '积分×1.5' },
  { days: 7,  icon: '🎀', desc: '额外+30分' },
  { days: 15, icon: '🏅', desc: '额外+80分' },
  { days: 30, icon: '🏆', desc: '额外+200分' },
];

var WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

Page({
  data: {
    checkedToday: false,
    streakDays: 0,
    todayPoints: 0,
    rewardMilestones: REWARD_MILESTONES,
    weekdays: WEEKDAYS,
    calendarTitle: '',
    calendarDays: [],
    monthStartOffset: 0,
    monthCheckinCount: 0,
  },

  onLoad: function() {
    this._initCalendar();
    this._loadCheckinData();
  },

  onShow: function() {
    // 重新读取签到数据，确保签到后返回时状态正确
    this._loadCheckinData();
  },

  // 初始化日历（当月）
  _initCalendar: function() {
    var now = new Date();
    var year = now.getFullYear();
    var month = now.getMonth();
    var today = now.getDate();

    var title = year + '年' + (month + 1) + '月签到记录';

    // 当月第一天是星期几（0=日 6=六）
    var firstDay = new Date(year, month, 1).getDay();
    // 当月总天数
    var daysInMonth = new Date(year, month + 1, 0).getDate();

    var days = [];
    for (var d = 1; d <= daysInMonth; d++) {
      days.push({
        day: d,
        checked: false,
        isToday: d === today,
        isFuture: d > today,
      });
    }

    this.setData({
      calendarTitle: title,
      calendarDays: days,
      monthStartOffset: firstDay,
    });
  },

  // 从 localStorage 读取签到数据并渲染
  _loadCheckinData: function() {
    var data = wx.getStorageSync('tx_checkin_data') || {};
    var now = new Date();
    var todayKey = this._dateKey(now);
    var checkedToday = !!(data[todayKey]);

    // 计算连续签到天数
    var streak = this._calcStreak(data, now);

    // 计算今日积分（签到5分 + 里程碑额外奖励）
    var todayPoints = checkedToday ? this._calcTodayPoints(streak) : 0;

    // 标记日历中已签到的天
    var calendarDays = this.data.calendarDays.map(function(cell) {
      var key = now.getFullYear() + '-' + (now.getMonth() + 1) + '-' + cell.day;
      return Object.assign({}, cell, { checked: !!(data[key]) });
    });

    // 统计本月签到次数
    var monthCheckinCount = calendarDays.filter(function(c) { return c.checked; }).length;

    this.setData({
      checkedToday: checkedToday,
      streakDays: streak,
      todayPoints: todayPoints,
      calendarDays: calendarDays,
      monthCheckinCount: monthCheckinCount,
    });
  },

  // 执行签到
  doCheckin: function() {
    if (this.data.checkedToday) {
      wx.showToast({ title: '今日已签到', icon: 'none' });
      return;
    }

    var that = this;
    var customerId = wx.getStorageSync('tx_customer_id') || '';

    wx.showLoading({ title: '签到中...' });

    api.txRequest('/api/v1/member/checkin', 'POST', { customer_id: customerId })
      .then(function(data) {
        wx.hideLoading();
        that._onCheckinSuccess(data || {});
      })
      .catch(function() {
        wx.hideLoading();
        // 网络失败或接口异常时 mock 签到成功（演示环境）
        that._onCheckinSuccess({});
      });
  },

  // 签到成功处理：更新本地数据 + 刷新 UI + 更新全局积分
  _onCheckinSuccess: function(serverData) {
    var now = new Date();
    var todayKey = this._dateKey(now);

    // 更新签到记录到 localStorage
    var data = wx.getStorageSync('tx_checkin_data') || {};
    data[todayKey] = { ts: Date.now(), points: 5 };
    wx.setStorageSync('tx_checkin_data', data);

    // 重新计算连续天数和今日积分
    var streak = this._calcStreak(data, now);
    var todayPoints = this._calcTodayPoints(streak);

    // 更新全局积分缓存
    var currentPoints = wx.getStorageSync('tx_points') || 0;
    wx.setStorageSync('tx_points', currentPoints + todayPoints);

    // 刷新页面数据
    this._loadCheckinData();

    // 积分到账提示动画
    var msg = '+' + todayPoints + '积分到账！';
    if (streak >= 7) msg += ' 连续签到奖励已发放';
    wx.showToast({ title: msg, icon: 'success', duration: 2000 });
  },

  // 计算连续签到天数（从今天往前数）
  _calcStreak: function(data, now) {
    var streak = 0;
    var d = new Date(now);
    // 如果今天已签到，从今天开始算；否则从昨天开始（避免今天未签到归零）
    var todayKey = this._dateKey(d);
    if (!data[todayKey]) {
      d.setDate(d.getDate() - 1);
    }
    for (var i = 0; i < 366; i++) {
      var key = this._dateKey(d);
      if (data[key]) {
        streak++;
        d.setDate(d.getDate() - 1);
      } else {
        break;
      }
    }
    return streak;
  },

  // 根据连续天数计算今日获得积分
  _calcTodayPoints: function(streak) {
    var base = 5;
    // 里程碑额外奖励（只在刚达到里程碑当天发放）
    if (streak === 30) return base + 200;
    if (streak === 15) return base + 80;
    if (streak === 7)  return base + 30;
    // 连续3天及以上，基础积分1.5倍
    if (streak >= 3)  return Math.round(base * 1.5);
    return base;
  },

  // 生成日期 key：YYYY-M-D（与日历格子保持一致）
  _dateKey: function(d) {
    return d.getFullYear() + '-' + (d.getMonth() + 1) + '-' + d.getDate();
  },

  // 跳转积分明细
  goPointsDetail: function() {
    // points 页已在 subPackages 中注册
    wx.navigateTo({ url: '/pages/points/points' });
  },
});
