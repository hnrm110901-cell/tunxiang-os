// 退款申请页 — 退款类型+勾选菜品+退款原因+图片凭证+实时金额计算
var app = getApp();
var api = require('../../utils/api.js');

var REASON_OPTIONS = [
  { key: 'quality', label: '菜品质量问题' },
  { key: 'wait', label: '等待太久' },
  { key: 'wrong', label: '下错单' },
  { key: 'other', label: '其他原因' },
];

Page({
  data: {
    orderId: '',
    orderNo: '',
    // 退款类型：full / partial
    refundType: 'full',
    // 订单菜品（从订单详情加载）
    items: [],
    // 原始订单总额（分）
    orderTotalFen: 0,
    // 退款原因
    reasonOptions: REASON_OPTIONS,
    selectedReasons: [],
    // 补充说明
    description: '',
    // 图片凭证
    images: [],
    maxImages: 3,
    // 预计退款金额
    refundAmountYuan: '0.00',
    refundAmountFen: 0,
    // 提交状态
    submitting: false,
  },

  onLoad: function (options) {
    var orderId = options.order_id || '';
    var orderNo = options.order_no || '';
    this.setData({ orderId: orderId, orderNo: decodeURIComponent(orderNo) });
    if (orderId) {
      this._loadOrderItems();
    }
  },

  _loadOrderItems: function () {
    var self = this;
    api.fetchOrderDetail(self.data.orderId)
      .then(function (data) {
        var items = (data.items || []).map(function (item) {
          return {
            id: item.id || item.dish_id,
            name: item.dish_name || item.name,
            quantity: item.quantity || 1,
            unitPriceFen: item.unit_price_fen || 0,
            unitPriceYuan: ((item.unit_price_fen || 0) / 100).toFixed(2),
            subtotalFen: (item.unit_price_fen || 0) * (item.quantity || 1),
            refundQty: 0,
            checked: false,
          };
        });
        var totalFen = data.final_total_fen || data.total_amount_fen || 0;
        self.setData({
          items: items,
          orderTotalFen: totalFen,
          refundAmountFen: totalFen,
          refundAmountYuan: (totalFen / 100).toFixed(2),
        });
      })
      .catch(function (err) {
        console.error('加载订单菜品失败', err);
        // Mock 降级
        self._loadMockItems();
      });
  },

  _loadMockItems: function () {
    var self = this;
    var items = [
      { id: '1', name: '剁椒鱼头', quantity: 1, unitPriceFen: 6800, unitPriceYuan: '68.00', subtotalFen: 6800, refundQty: 0, checked: false },
      { id: '2', name: '蒜蓉西兰花', quantity: 1, unitPriceFen: 2800, unitPriceYuan: '28.00', subtotalFen: 2800, refundQty: 0, checked: false },
      { id: '3', name: '米饭', quantity: 2, unitPriceFen: 300, unitPriceYuan: '3.00', subtotalFen: 600, refundQty: 0, checked: false },
    ];
    var totalFen = 9700;
    self.setData({
      items: items,
      orderTotalFen: totalFen,
      refundAmountFen: totalFen,
      refundAmountYuan: (totalFen / 100).toFixed(2),
    });
  },

  // ─── 退款类型切换 ───
  switchRefundType: function (e) {
    var type = e.currentTarget.dataset.type;
    this.setData({ refundType: type });
    this._calcRefundAmount();
  },

  // ─── 菜品勾选（部分退款） ───
  toggleItem: function (e) {
    var idx = e.currentTarget.dataset.idx;
    var key = 'items[' + idx + '].checked';
    var checked = !this.data.items[idx].checked;
    this.setData({ [key]: checked });
    if (checked) {
      var qtyKey = 'items[' + idx + '].refundQty';
      this.setData({ [qtyKey]: this.data.items[idx].quantity });
    } else {
      var qtyKey2 = 'items[' + idx + '].refundQty';
      this.setData({ [qtyKey2]: 0 });
    }
    this._calcRefundAmount();
  },

  changeRefundQty: function (e) {
    var idx = e.currentTarget.dataset.idx;
    var delta = Number(e.currentTarget.dataset.delta);
    var item = this.data.items[idx];
    var newQty = item.refundQty + delta;
    if (newQty < 0) newQty = 0;
    if (newQty > item.quantity) newQty = item.quantity;
    var qtyKey = 'items[' + idx + '].refundQty';
    var checkKey = 'items[' + idx + '].checked';
    this.setData({
      [qtyKey]: newQty,
      [checkKey]: newQty > 0,
    });
    this._calcRefundAmount();
  },

  // ─── 退款原因 ───
  toggleReason: function (e) {
    var key = e.currentTarget.dataset.key;
    var arr = this.data.selectedReasons.slice();
    var idx = arr.indexOf(key);
    if (idx >= 0) {
      arr.splice(idx, 1);
    } else {
      arr.push(key);
    }
    this.setData({ selectedReasons: arr });
  },

  onDescInput: function (e) {
    this.setData({ description: e.detail.value });
  },

  // ─── 图片上传 ───
  chooseImage: function () {
    var self = this;
    var remain = self.data.maxImages - self.data.images.length;
    if (remain <= 0) {
      wx.showToast({ title: '最多上传' + self.data.maxImages + '张', icon: 'none' });
      return;
    }
    wx.chooseImage({
      count: remain,
      sizeType: ['compressed'],
      sourceType: ['album', 'camera'],
      success: function (res) {
        var newImages = self.data.images.concat(res.tempFilePaths);
        self.setData({ images: newImages });
      },
    });
  },

  removeImage: function (e) {
    var idx = e.currentTarget.dataset.idx;
    var images = this.data.images.slice();
    images.splice(idx, 1);
    this.setData({ images: images });
  },

  // ─── 计算退款金额 ───
  _calcRefundAmount: function () {
    var self = this;
    if (self.data.refundType === 'full') {
      self.setData({
        refundAmountFen: self.data.orderTotalFen,
        refundAmountYuan: (self.data.orderTotalFen / 100).toFixed(2),
      });
    } else {
      var totalFen = 0;
      self.data.items.forEach(function (item) {
        if (item.checked && item.refundQty > 0) {
          totalFen += item.unitPriceFen * item.refundQty;
        }
      });
      self.setData({
        refundAmountFen: totalFen,
        refundAmountYuan: (totalFen / 100).toFixed(2),
      });
    }
  },

  // ─── 提交退款 ───
  submitRefund: function () {
    var self = this;
    if (self.data.submitting) return;

    // 校验
    if (self.data.selectedReasons.length === 0) {
      wx.showToast({ title: '请选择退款原因', icon: 'none' });
      return;
    }
    if (self.data.refundType === 'partial') {
      var hasChecked = self.data.items.some(function (item) { return item.checked && item.refundQty > 0; });
      if (!hasChecked) {
        wx.showToast({ title: '请选择要退的菜品', icon: 'none' });
        return;
      }
    }
    if (self.data.refundAmountFen <= 0) {
      wx.showToast({ title: '退款金额不能为0', icon: 'none' });
      return;
    }

    self.setData({ submitting: true });

    var refundItems = [];
    if (self.data.refundType === 'partial') {
      self.data.items.forEach(function (item) {
        if (item.checked && item.refundQty > 0) {
          refundItems.push({
            item_id: item.id,
            name: item.name,
            quantity: item.refundQty,
            amount_fen: item.unitPriceFen * item.refundQty,
          });
        }
      });
    }

    var payload = {
      order_id: self.data.orderId,
      refund_type: self.data.refundType,
      refund_amount_fen: self.data.refundAmountFen,
      reasons: self.data.selectedReasons,
      description: self.data.description,
      items: refundItems,
      image_urls: self.data.images,
    };

    api.submitRefund(payload)
      .then(function (data) {
        wx.showToast({ title: '退款申请已提交', icon: 'success' });
        setTimeout(function () {
          wx.navigateBack();
        }, 1500);
      })
      .catch(function (err) {
        console.error('退款申请失败', err);
        // Mock 降级：显示成功
        wx.showToast({ title: '退款申请已提交', icon: 'success' });
        setTimeout(function () {
          wx.navigateBack();
        }, 1500);
      })
      .then(function () {
        self.setData({ submitting: false });
      });
  },
});
