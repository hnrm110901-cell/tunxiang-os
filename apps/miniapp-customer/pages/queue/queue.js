// 排队取号页
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    guestOptions: [
      { label: '1-2人', value: '1-2' },
      { label: '3-4人', value: '3-4' },
      { label: '5-6人', value: '5-6' },
      { label: '7人以上', value: '7+' },
    ],
    selectedGuests: '',
    queueSummary: [],
    queueTicket: null,
    submitting: false,
    pollTimer: null,
  },

  onLoad: function () {
    this.loadQueueSummary();
    this.checkExistingTicket();
  },

  onUnload: function () {
    if (this.data.pollTimer) {
      clearInterval(this.data.pollTimer);
    }
  },

  selectGuests: function (e) {
    this.setData({ selectedGuests: e.currentTarget.dataset.value });
  },

  loadQueueSummary: function () {
    var self = this;
    var storeId = app.globalData.storeId;
    api.fetchQueueSummary(storeId)
      .then(function (data) {
        self.setData({ queueSummary: data.items || [] });
      })
      .catch(function (err) {
        console.error('loadQueueSummary failed', err);
      });
  },

  checkExistingTicket: function () {
    var self = this;
    var storeId = app.globalData.storeId;
    api.fetchMyTicket(storeId)
      .then(function (data) {
        if (data) {
          self.setData({ queueTicket: data });
          self.startPolling();
        }
      })
      .catch(function (err) {
        console.error('checkExistingTicket failed', err);
      });
  },

  takeNumber: function () {
    var self = this;
    if (!self.data.selectedGuests) {
      wx.showToast({ title: '请选择用餐人数', icon: 'none' });
      return;
    }
    self.setData({ submitting: true });

    var storeId = app.globalData.storeId;
    api.takeQueue(storeId, self.data.selectedGuests)
      .then(function (data) {
        wx.showToast({ title: '取号成功', icon: 'success' });
        self.setData({ queueTicket: data, submitting: false });
        self.startPolling();
      })
      .catch(function (err) {
        console.error('takeNumber failed', err);
        wx.showToast({ title: err.message || '取号失败', icon: 'none' });
        self.setData({ submitting: false });
      });
  },

  startPolling: function () {
    var self = this;
    if (self.data.pollTimer) clearInterval(self.data.pollTimer);
    var timer = setInterval(function () {
      self.refreshTicketStatus();
    }, 15000);
    self.setData({ pollTimer: timer });
  },

  refreshTicketStatus: function () {
    var self = this;
    var storeId = app.globalData.storeId;
    api.fetchMyTicket(storeId)
      .then(function (data) {
        if (data) {
          self.setData({ queueTicket: data });
          if (data.status === 'called') {
            wx.showModal({
              title: '叫号通知',
              content: '您的号码 ' + data.ticketNo + ' 已到，请前往就座！',
              showCancel: false,
            });
            clearInterval(self.data.pollTimer);
          }
        } else {
          self.setData({ queueTicket: null });
          clearInterval(self.data.pollTimer);
        }
      })
      .catch(function (err) {
        console.error('refreshTicketStatus failed', err);
      });
  },

  cancelQueue: function () {
    var self = this;
    wx.showModal({
      title: '提示',
      content: '确定取消排队？',
      success: function (res) {
        if (!res.confirm) return;
        var ticket = self.data.queueTicket;
        api.cancelQueueTicket(ticket.id)
          .then(function () {
            wx.showToast({ title: '已取消', icon: 'success' });
            clearInterval(self.data.pollTimer);
            self.setData({ queueTicket: null, pollTimer: null });
            self.loadQueueSummary();
          })
          .catch(function (err) {
            console.error('cancelQueue failed', err);
            wx.showToast({ title: '取消失败', icon: 'none' });
          });
      },
    });
  },
});
