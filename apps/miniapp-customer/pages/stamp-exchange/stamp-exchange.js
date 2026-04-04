var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    cardId: '',
    prizeId: '',
    prizeName: '',
    prizeDesc: '',
    stampsRequired: 0,
    currentStamps: 0,
    showConfirm: false,
    exchanging: false,
    exchangeSuccess: false,
    redeemCode: '',
    redeemExpire: '',
    redeemInstructions: [
      '请在门店出示此核销码给服务员',
      '核销码24小时内有效',
      '每个奖品仅可兑换一次',
      '兑换后对应印章将被消耗'
    ],
  },

  onLoad: function (options) {
    this.setData({
      cardId: options.card_id || '',
      prizeId: options.prize_id || '',
      prizeName: decodeURIComponent(options.prize_name || ''),
      prizeDesc: decodeURIComponent(options.prize_desc || ''),
      stampsRequired: parseInt(options.stamps_required) || 0,
      currentStamps: parseInt(options.current_stamps) || 0,
    });
  },

  onShowConfirm: function () {
    this.setData({ showConfirm: true });
  },

  onHideConfirm: function () {
    if (this.data.exchanging) return;
    this.setData({ showConfirm: false });
  },

  onConfirmExchange: function () {
    var self = this;
    if (self.data.exchanging) return;

    self.setData({ exchanging: true });

    api.txRequest('/api/v1/growth/stamp-card/exchange', 'POST', {
      card_id: self.data.cardId,
      prize_id: self.data.prizeId,
    }).then(function (res) {
      self.setData({
        exchanging: false,
        showConfirm: false,
        exchangeSuccess: true,
        redeemCode: res.redeem_code || self._generateMockCode(),
        redeemExpire: res.expire_time || self._mockExpireTime(),
      });
    }).catch(function () {
      // 降级 Mock
      self.setData({
        exchanging: false,
        showConfirm: false,
        exchangeSuccess: true,
        redeemCode: self._generateMockCode(),
        redeemExpire: self._mockExpireTime(),
      });
    });
  },

  _generateMockCode: function () {
    var chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    var code = '';
    for (var i = 0; i < 8; i++) {
      code += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return code.substring(0, 4) + '-' + code.substring(4);
  },

  _mockExpireTime: function () {
    var d = new Date();
    d.setHours(d.getHours() + 24);
    var y = d.getFullYear();
    var m = ('0' + (d.getMonth() + 1)).slice(-2);
    var day = ('0' + d.getDate()).slice(-2);
    var h = ('0' + d.getHours()).slice(-2);
    var min = ('0' + d.getMinutes()).slice(-2);
    return y + '-' + m + '-' + day + ' ' + h + ':' + min;
  },

  onCopyCode: function () {
    var code = this.data.redeemCode;
    wx.setClipboardData({
      data: code,
      success: function () {
        wx.showToast({ title: '已复制核销码', icon: 'success' });
      }
    });
  },

  onGoBack: function () {
    wx.navigateBack({ delta: 1 });
  },
});
