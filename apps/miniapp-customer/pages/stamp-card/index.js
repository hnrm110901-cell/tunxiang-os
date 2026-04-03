var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    tab: 'cards',
    myCards: [],
    templates: [],
    loading: false,
    redeeming: false,
  },

  onLoad: function () {
    this._loadMyCards();
  },

  onPullDownRefresh: function () {
    var self = this;
    var p = self.data.tab === 'cards' ? self._loadMyCards() : self._loadTemplates();
    Promise.resolve(p).finally(function () {
      wx.stopPullDownRefresh();
    });
  },

  switchTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    this.setData({ tab: tab });
    if (tab === 'cards') this._loadMyCards();
    if (tab === 'all') this._loadTemplates();
  },

  _loadMyCards: function () {
    var self = this;
    self.setData({ loading: true });
    return api.get('/api/v1/stamp-cards/mine').then(function (res) {
      self.setData({ myCards: res.data.items || [], loading: false });
    }).catch(function () {
      self.setData({ loading: false });
    });
  },

  _loadTemplates: function () {
    var self = this;
    self.setData({ loading: true });
    return api.get('/api/v1/stamp-cards/templates', { status: 'active' }).then(function (res) {
      self.setData({ templates: res.data.items || [], loading: false });
    }).catch(function () {
      self.setData({ loading: false });
    });
  },

  onRedeemCard: function (e) {
    var instanceId = e.currentTarget.dataset.id;
    var self = this;
    if (self.data.redeeming) return;

    wx.showModal({
      title: '兑换奖励',
      content: '确定要兑换此集点卡的奖励吗？',
      success: function (res) {
        if (!res.confirm) return;
        self.setData({ redeeming: true });
        api.post('/api/v1/stamp-cards/' + instanceId + '/redeem', {}).then(function (res) {
          self.setData({ redeeming: false });
          wx.showToast({ title: '兑换成功！', icon: 'success' });
          self._loadMyCards();
        }).catch(function () {
          self.setData({ redeeming: false });
          wx.showToast({ title: '兑换失败', icon: 'none' });
        });
      },
    });
  },

  onShareAppMessage: function () {
    return {
      title: '消费集印，好礼相送！',
      path: '/pages/stamp-card/index',
    };
  },
});
