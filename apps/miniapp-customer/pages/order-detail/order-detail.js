// 订单详情页 — 状态大图标 + 订单信息 + 菜品列表 + 金额明细 + 操作按钮
var app = getApp();
var api = require('../../utils/api.js');

var STATUS_MAP = {
  pending_payment: { text: '待支付', icon: '\u{1F550}', color: '#FF6B2C' },
  paid:            { text: '已支付', icon: '\u{1F468}\u200D\u{1F373}', color: '#BA7517' },
  cooking:         { text: '制作中', icon: '\u{1F468}\u200D\u{1F373}', color: '#BA7517' },
  delivering:      { text: '配送中', icon: '\u{1F6F5}', color: '#2196F3' },
  ready:           { text: '待取餐', icon: '\u2705', color: '#4CAF50' },
  completed:       { text: '已完成', icon: '\u2705', color: '#4CAF50' },
  cancelled:       { text: '已取消', icon: '\u274C', color: '#999' },
  refunded:        { text: '已退款', icon: '\u274C', color: '#999' },
};

Page({
  data: {
    orderId: '',
    orderNo: '',
    status: '',
    statusText: '',
    statusIcon: '',
    statusColor: '',
    // 订单信息
    storeName: '',
    tableNo: '',
    address: '',
    orderType: '',
    createdAt: '',
    // 菜品列表
    items: [],
    // 金额明细
    itemsTotalYuan: '0.00',
    discountYuan: '0.00',
    deliveryFeeYuan: '0.00',
    finalTotalYuan: '0.00',
    // 操作按钮控制
    showPay: false,
    showCancel: false,
    showRush: false,
    showContactRider: false,
    showReorder: false,
    showReview: false,
    showRefund: false,
    showResubmit: false,
    // 加载
    loading: true,
  },

  onLoad: function (options) {
    var orderId = options.order_id || options.id || '';
    this.setData({ orderId: orderId });
    if (orderId) {
      this._loadDetail();
    }
  },

  onShow: function () {
    if (this.data.orderId && !this.data.loading) {
      this._loadDetail();
    }
  },

  onShareAppMessage: function () {
    return {
      title: '订单详情 - ' + this.data.orderNo,
      path: '/pages/order-detail/order-detail?order_id=' + this.data.orderId,
    };
  },

  _loadDetail: function () {
    var self = this;
    self.setData({ loading: true });

    api.fetchOrderDetail(self.data.orderId)
      .then(function (data) {
        var status = data.status || 'pending_payment';
        var info = STATUS_MAP[status] || { text: status, icon: '\u2753', color: '#999' };

        var items = (data.items || []).map(function (item) {
          return {
            id: item.id || item.dish_id,
            name: item.dish_name || item.name,
            spec: item.spec || item.sku_name || '',
            imageUrl: item.image_url || '',
            quantity: item.quantity || 1,
            unitPriceYuan: ((item.unit_price_fen || 0) / 100).toFixed(2),
            subtotalYuan: (((item.unit_price_fen || 0) * (item.quantity || 1)) / 100).toFixed(2),
          };
        });

        var itemsTotalFen = data.items_total_fen || 0;
        if (!itemsTotalFen) {
          itemsTotalFen = (data.items || []).reduce(function (sum, item) {
            return sum + (item.unit_price_fen || 0) * (item.quantity || 1);
          }, 0);
        }
        var discountFen = data.discount_fen || 0;
        var deliveryFeeFen = data.delivery_fee_fen || 0;
        var finalTotalFen = data.final_total_fen || data.total_amount_fen || 0;

        self.setData({
          orderNo: data.order_no || '',
          status: status,
          statusText: info.text,
          statusIcon: info.icon,
          statusColor: info.color,
          storeName: data.store_name || '',
          tableNo: data.table_no || '',
          address: data.delivery_address || '',
          orderType: data.order_type || 'dine_in',
          createdAt: (data.created_at || '').slice(0, 16).replace('T', ' '),
          items: items,
          itemsTotalYuan: (itemsTotalFen / 100).toFixed(2),
          discountYuan: (discountFen / 100).toFixed(2),
          deliveryFeeYuan: (deliveryFeeFen / 100).toFixed(2),
          finalTotalYuan: (finalTotalFen / 100).toFixed(2),
          // 按钮状态
          showPay: status === 'pending_payment',
          showCancel: status === 'pending_payment',
          showRush: status === 'cooking' || status === 'paid',
          showContactRider: status === 'delivering',
          showReorder: status === 'completed',
          showReview: status === 'completed',
          showRefund: status === 'completed',
          showResubmit: status === 'cancelled',
          loading: false,
        });
      })
      .catch(function (err) {
        console.error('加载订单详情失败', err);
        wx.showToast({ title: err.message || '加载失败', icon: 'none' });
        self.setData({ loading: false });
        // Mock 降级
        self._loadMockDetail();
      });
  },

  _loadMockDetail: function () {
    var self = this;
    var mockData = {
      order_no: 'TX20260402001',
      status: 'cooking',
      store_name: '屯象测试门店',
      table_no: 'A3',
      order_type: 'dine_in',
      created_at: '2026-04-02T12:30:00',
      items: [
        { dish_name: '剁椒鱼头', spec: '大份', image_url: '', quantity: 1, unit_price_fen: 6800 },
        { dish_name: '蒜蓉西兰花', spec: '', image_url: '', quantity: 1, unit_price_fen: 2800 },
        { dish_name: '米饭', spec: '', image_url: '', quantity: 2, unit_price_fen: 300 },
      ],
      items_total_fen: 10200,
      discount_fen: 500,
      delivery_fee_fen: 0,
      final_total_fen: 9700,
    };

    var status = mockData.status;
    var info = STATUS_MAP[status] || { text: status, icon: '\u2753', color: '#999' };

    var items = mockData.items.map(function (item) {
      return {
        id: '',
        name: item.dish_name,
        spec: item.spec || '',
        imageUrl: item.image_url || '',
        quantity: item.quantity,
        unitPriceYuan: (item.unit_price_fen / 100).toFixed(2),
        subtotalYuan: ((item.unit_price_fen * item.quantity) / 100).toFixed(2),
      };
    });

    self.setData({
      orderNo: mockData.order_no,
      status: status,
      statusText: info.text,
      statusIcon: info.icon,
      statusColor: info.color,
      storeName: mockData.store_name,
      tableNo: mockData.table_no,
      orderType: mockData.order_type,
      createdAt: mockData.created_at.slice(0, 16).replace('T', ' '),
      items: items,
      itemsTotalYuan: (mockData.items_total_fen / 100).toFixed(2),
      discountYuan: (mockData.discount_fen / 100).toFixed(2),
      deliveryFeeYuan: (mockData.delivery_fee_fen / 100).toFixed(2),
      finalTotalYuan: (mockData.final_total_fen / 100).toFixed(2),
      showPay: status === 'pending_payment',
      showCancel: status === 'pending_payment',
      showRush: status === 'cooking' || status === 'paid',
      showContactRider: status === 'delivering',
      showReorder: status === 'completed',
      showReview: status === 'completed',
      showRefund: status === 'completed',
      showResubmit: status === 'cancelled',
      loading: false,
    });
  },

  // ─── 操作 ───

  goPay: function () {
    var self = this;
    api.createPayment(self.data.orderId, 'wechat', 0)
      .then(function (payData) {
        if (payData.wx_pay_params) {
          wx.requestPayment({
            timeStamp: payData.wx_pay_params.timeStamp,
            nonceStr: payData.wx_pay_params.nonceStr,
            package: payData.wx_pay_params.package,
            signType: payData.wx_pay_params.signType,
            paySign: payData.wx_pay_params.paySign,
            success: function () {
              wx.showToast({ title: '支付成功', icon: 'success' });
              self._loadDetail();
            },
            fail: function () {
              wx.showToast({ title: '支付取消', icon: 'none' });
            },
          });
        }
      })
      .catch(function (err) {
        wx.showToast({ title: err.message || '支付失败', icon: 'none' });
      });
  },

  cancelOrder: function () {
    var self = this;
    wx.showModal({
      title: '确认取消',
      content: '确定要取消此订单吗？',
      success: function (res) {
        if (res.confirm) {
          api.cancelOrder(self.data.orderId)
            .then(function () {
              wx.showToast({ title: '已取消', icon: 'success' });
              self._loadDetail();
            })
            .catch(function (err) {
              wx.showToast({ title: err.message || '取消失败', icon: 'none' });
            });
        }
      },
    });
  },

  rushOrder: function () {
    var self = this;
    wx.navigateTo({
      url: '/pages/rush-result/rush-result?order_id=' + self.data.orderId,
    });
  },

  contactRider: function () {
    wx.showToast({ title: '正在联系骑手...', icon: 'none' });
    // TODO: 接入骑手电话
    wx.makePhoneCall({
      phoneNumber: '10086',
      fail: function () {},
    });
  },

  reorder: function () {
    // 重新下单：带菜品跳转到订单确认
    var items = this.data.items.map(function (item) {
      return {
        dishId: item.id,
        dishName: item.name,
        quantity: item.quantity,
        unitPriceFen: Math.round(parseFloat(item.unitPriceYuan) * 100),
      };
    });
    var totalFen = items.reduce(function (sum, i) { return sum + i.unitPriceFen * i.quantity; }, 0);
    wx.switchTab({ url: '/pages/order/order' });
  },

  goReview: function () {
    wx.navigateTo({
      url: '/pages/review/review?order_id=' + this.data.orderId +
           '&order_no=' + encodeURIComponent(this.data.orderNo) +
           '&store_name=' + encodeURIComponent(this.data.storeName),
    });
  },

  goRefund: function () {
    wx.navigateTo({
      url: '/pages/refund-apply/refund-apply?order_id=' + this.data.orderId +
           '&order_no=' + encodeURIComponent(this.data.orderNo),
    });
  },

  resubmit: function () {
    this.reorder();
  },

  copyOrderNo: function () {
    wx.setClipboardData({
      data: this.data.orderNo,
      success: function () {
        wx.showToast({ title: '已复制', icon: 'success' });
      },
    });
  },
});
