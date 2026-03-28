// 订单页 — 订单确认（从菜单跳入）+ 历史订单列表（从tabBar进入）
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    // 模式：'confirm' 确认下单 / 'list' 历史订单
    mode: 'list',
    // ─── 确认下单 ───
    orderItems: [],
    totalFen: 0,
    totalYuan: '0.00',
    tableNo: '',
    remark: '',
    payMethod: 'wechat',
    submitting: false,
    // ─── 历史订单 ───
    activeTab: 'all',
    orderTabs: [
      { key: 'all', label: '全部' },
      { key: 'pending', label: '待支付' },
      { key: 'cooking', label: '制作中' },
      { key: 'completed', label: '已完成' },
    ],
    orders: [],
    orderPage: 1,
    hasMore: false,
    loadingOrders: false,
  },

  onLoad: function (options) {
    if (options.items) {
      // 从菜单跳入：确认下单模式
      try {
        var items = JSON.parse(decodeURIComponent(options.items));
        var total = Number(options.total) || 0;
        this.setData({
          mode: 'confirm',
          orderItems: items,
          totalFen: total,
          totalYuan: (total / 100).toFixed(2),
          tableNo: options.table || '',
        });
      } catch (e) {
        console.error('解析订单项失败', e);
        this.setData({ mode: 'list' });
      }
    } else {
      this.setData({ mode: 'list' });
      this._loadOrders();
    }
  },

  onShow: function () {
    if (this.data.mode === 'list') {
      this._loadOrders();
    }
  },

  onPullDownRefresh: function () {
    var self = this;
    self.setData({ orderPage: 1, orders: [] });
    self._loadOrders().then(function () {
      wx.stopPullDownRefresh();
    });
  },

  onReachBottom: function () {
    if (this.data.hasMore && this.data.mode === 'list') {
      this.setData({ orderPage: this.data.orderPage + 1 });
      this._loadOrders();
    }
  },

  onShareAppMessage: function () {
    return { title: '屯象点餐 - 我的订单', path: '/pages/order/order' };
  },

  // ─── 确认下单 ───

  onRemarkInput: function (e) {
    this.setData({ remark: e.detail.value });
  },

  selectPayMethod: function (e) {
    this.setData({ payMethod: e.currentTarget.dataset.method });
  },

  submitOrder: function () {
    var self = this;
    if (self.data.submitting) return;
    self.setData({ submitting: true });

    var storeId = app.globalData.storeId;
    var items = self.data.orderItems.map(function (item) {
      return {
        dish_id: item.dishId,
        dish_name: item.dishName,
        quantity: item.quantity,
        unit_price_fen: item.unitPriceFen,
      };
    });

    api.createOrder({
      store_id: storeId,
      customer_id: wx.getStorageSync('tx_customer_id') || '',
      table_no: self.data.tableNo,
      items: items,
      remark: self.data.remark,
      order_type: self.data.tableNo ? 'dine_in' : 'takeaway',
    }).then(function (data) {
      // 创建支付
      return api.createPayment(data.order_id, self.data.payMethod, self.data.totalFen)
        .then(function (payData) {
          if (self.data.payMethod === 'wechat' && payData.wx_pay_params) {
            // 调起微信支付
            return new Promise(function (resolve, reject) {
              wx.requestPayment({
                timeStamp: payData.wx_pay_params.timeStamp,
                nonceStr: payData.wx_pay_params.nonceStr,
                package: payData.wx_pay_params.package,
                signType: payData.wx_pay_params.signType,
                paySign: payData.wx_pay_params.paySign,
                success: function () { resolve(data); },
                fail: function (err) {
                  // 用户取消支付不算错误
                  if (err.errMsg && err.errMsg.indexOf('cancel') >= 0) {
                    resolve(data);
                  } else {
                    reject(err);
                  }
                },
              });
            });
          }
          return data;
        });
    }).then(function (data) {
      wx.showToast({ title: '下单成功', icon: 'success' });
      setTimeout(function () {
        // 跳回订单列表
        self.setData({
          mode: 'list',
          orderItems: [],
          submitting: false,
        });
        self._loadOrders();
      }, 1500);
    }).catch(function (err) {
      console.error('下单失败', err);
      wx.showToast({ title: err.message || '下单失败', icon: 'none' });
      self.setData({ submitting: false });
    });
  },

  // ─── 历史订单 ───

  switchOrderTab: function (e) {
    this.setData({
      activeTab: e.currentTarget.dataset.tab,
      orders: [],
      orderPage: 1,
    });
    this._loadOrders();
  },

  _loadOrders: function () {
    var self = this;
    self.setData({ loadingOrders: true });

    return api.fetchMyOrders(self.data.orderPage)
      .then(function (data) {
        var statusMap = {
          pending_payment: '待支付',
          paid: '已支付',
          cooking: '制作中',
          ready: '待取餐',
          completed: '已完成',
          cancelled: '已取消',
          refunded: '已退款',
        };

        var items = (data.items || []).map(function (o) {
          return {
            id: o.id || o.order_id,
            orderNo: o.order_no || '',
            status: o.status,
            statusText: statusMap[o.status] || o.status,
            totalYuan: ((o.total_amount_fen || 0) / 100).toFixed(2),
            itemCount: o.item_count || 0,
            firstDishName: o.first_dish_name || '',
            createdAt: (o.created_at || '').slice(0, 16).replace('T', ' '),
          };
        });

        // 按 tab 筛选
        var tab = self.data.activeTab;
        if (tab !== 'all') {
          items = items.filter(function (o) {
            if (tab === 'pending') return o.status === 'pending_payment';
            if (tab === 'cooking') return o.status === 'cooking' || o.status === 'paid';
            if (tab === 'completed') return o.status === 'completed';
            return true;
          });
        }

        var merged = self.data.orderPage > 1 ? self.data.orders.concat(items) : items;
        self.setData({
          orders: merged,
          hasMore: items.length >= 20,
          loadingOrders: false,
        });
      })
      .catch(function (err) {
        console.error('加载订单失败', err);
        self.setData({ loadingOrders: false });
      });
  },

  goToOrderDetail: function (e) {
    var id = e.currentTarget.dataset.id;
    wx.navigateTo({ url: '/pages/order/order?order_id=' + id });
  },
});
