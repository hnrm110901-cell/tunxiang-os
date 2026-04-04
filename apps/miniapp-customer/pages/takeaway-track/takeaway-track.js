// 外卖订单跟踪页 — 10秒轮询更新状态
var app = getApp();
var api = require('../../utils/api.js');

var STATUS_MAP = {
  pending: { icon: '&#9203;', text: '待接单', desc: '商家正在确认您的订单', step: 0 },
  accepted: { icon: '&#127859;', text: '商家制作中', desc: '商家正在准备您的餐品', step: 1 },
  waiting_rider: { icon: '&#128230;', text: '等待骑手', desc: '餐品已备好，等待骑手取餐', step: 2 },
  delivering: { icon: '&#128692;', text: '配送中', desc: '骑手正在火速赶来', step: 3 },
  delivered: { icon: '&#9989;', text: '已送达', desc: '餐品已送达，请及时取餐', step: 4 },
};

var TIMELINE_LABELS = ['下单成功', '商家接单', '商家出餐', '骑手取餐', '已送达'];

Page({
  data: {
    loading: true,
    orderId: '',
    orderNo: '',
    orderTime: '',
    // 状态
    status: 'pending',
    statusIcon: '&#9203;',
    statusText: '待接单',
    statusDesc: '商家正在确认您的订单',
    // 倒计时
    showCountdown: false,
    countdownText: '',
    estimatedAt: null,
    // 骑手
    rider: null,
    // 时间线
    timeline: [],
    // 订单详情
    showDetail: false,
    orderItems: [],
    deliveryAddress: '',
    deliveryFeeYuan: '5.00',
    packFeeYuan: '0.00',
    payTotalYuan: '0.00',
  },

  _pollTimer: null,
  _countdownTimer: null,

  onLoad: function (options) {
    var orderId = options.order_id || '';
    this.setData({ orderId: orderId });
    this._fetchOrderStatus(orderId);
    this._startPolling(orderId);
  },

  onUnload: function () {
    this._stopPolling();
    this._stopCountdown();
  },

  onHide: function () {
    this._stopPolling();
    this._stopCountdown();
  },

  onShow: function () {
    if (this.data.orderId) {
      this._startPolling(this.data.orderId);
      if (this.data.estimatedAt) {
        this._startCountdown();
      }
    }
  },

  // ─── 数据拉取 ───

  _fetchOrderStatus: function (orderId) {
    var self = this;

    api.fetchTakeawayTrack(orderId)
      .then(function (data) {
        self._applyData(data);
      })
      .catch(function (err) {
        console.warn('获取外卖跟踪失败，使用Mock', err);
        self._applyMockData();
      });
  },

  _applyData: function (data) {
    var status = data.status || 'pending';
    var meta = STATUS_MAP[status] || STATUS_MAP.pending;
    var step = meta.step;

    // 时间线
    var timeline = [];
    var times = data.timeline_times || [];
    for (var i = 0; i < TIMELINE_LABELS.length; i++) {
      timeline.push({
        step: i,
        label: TIMELINE_LABELS[i],
        time: times[i] || '',
        done: i < step,
        active: i === step,
      });
    }

    // 骑手
    var rider = null;
    if (data.rider && (status === 'delivering' || status === 'waiting_rider')) {
      rider = {
        name: data.rider.name || '骑手',
        phone: data.rider.phone || '',
        distance: data.rider.distance || '',
      };
    }

    // 订单菜品
    var orderItems = (data.items || []).map(function (item) {
      return {
        id: item.id || item.dish_id,
        name: item.name || item.dish_name || '',
        quantity: item.quantity || 1,
        subtotalYuan: ((item.subtotal_fen || item.price_fen || 0) / 100).toFixed(2),
      };
    });

    var estimatedAt = data.estimated_delivery_at ? new Date(data.estimated_delivery_at) : null;

    this.setData({
      loading: false,
      orderNo: data.order_no || data.id || this.data.orderId,
      orderTime: data.created_at || '',
      status: status,
      statusIcon: meta.icon,
      statusText: meta.text,
      statusDesc: meta.desc,
      timeline: timeline,
      rider: rider,
      orderItems: orderItems.length > 0 ? orderItems : this.data.orderItems,
      deliveryAddress: data.delivery_address || this.data.deliveryAddress,
      deliveryFeeYuan: data.delivery_fee_fen ? (data.delivery_fee_fen / 100).toFixed(2) : this.data.deliveryFeeYuan,
      packFeeYuan: data.pack_fee_fen ? (data.pack_fee_fen / 100).toFixed(2) : this.data.packFeeYuan,
      payTotalYuan: data.total_fen ? (data.total_fen / 100).toFixed(2) : this.data.payTotalYuan,
      estimatedAt: estimatedAt,
      showCountdown: !!estimatedAt && status !== 'delivered',
    });

    if (estimatedAt && status !== 'delivered') {
      this._startCountdown();
    } else {
      this._stopCountdown();
    }

    // 已送达则停止轮询
    if (status === 'delivered') {
      this._stopPolling();
    }
  },

  _applyMockData: function () {
    var now = new Date();
    var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
    var timeStr = pad(now.getHours()) + ':' + pad(now.getMinutes());
    var estimated = new Date(now.getTime() + 25 * 60000);

    this._applyData({
      id: this.data.orderId || 'TW20260402001',
      order_no: 'TW20260402001',
      status: 'accepted',
      created_at: timeStr,
      estimated_delivery_at: estimated.toISOString(),
      timeline_times: [timeStr, timeStr, '', '', ''],
      rider: null,
      items: [
        { id: 'd1', name: '招牌红烧肉套餐', quantity: 1, subtotal_fen: 3800 },
        { id: 'd7', name: '冰柠檬茶', quantity: 2, subtotal_fen: 1600 },
      ],
      delivery_address: '湖南省长沙市岳麓区麓谷街道中电软件园1号楼',
      delivery_fee_fen: 500,
      pack_fee_fen: 200,
      total_fen: 6100,
    });
  },

  // ─── 10秒轮询 ───

  _startPolling: function (orderId) {
    this._stopPolling();
    var self = this;
    self._pollTimer = setInterval(function () {
      self._fetchOrderStatus(orderId);
    }, 10000);
  },

  _stopPolling: function () {
    if (this._pollTimer) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
  },

  // ─── 倒计时 ───

  _startCountdown: function () {
    this._stopCountdown();
    var self = this;
    self._countdownTimer = setInterval(function () {
      if (!self.data.estimatedAt) { self._stopCountdown(); return; }
      var diff = self.data.estimatedAt.getTime() - Date.now();
      if (diff <= 0) {
        self.setData({ countdownText: '即将送达' });
        self._stopCountdown();
        return;
      }
      var min = Math.floor(diff / 60000);
      var sec = Math.floor((diff % 60000) / 1000);
      var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
      self.setData({ countdownText: min + '分' + pad(sec) + '秒' });
    }, 1000);
  },

  _stopCountdown: function () {
    if (this._countdownTimer) {
      clearInterval(this._countdownTimer);
      this._countdownTimer = null;
    }
  },

  // ─── 交互 ───

  callRider: function () {
    if (!this.data.rider || !this.data.rider.phone) {
      wx.showToast({ title: '暂无骑手电话', icon: 'none' });
      return;
    }
    wx.makePhoneCall({ phoneNumber: this.data.rider.phone });
  },

  toggleDetail: function () {
    this.setData({ showDetail: !this.data.showDetail });
  },

  copyOrderNo: function (e) {
    var text = e.currentTarget.dataset.text || '';
    wx.setClipboardData({ data: text });
  },
});
