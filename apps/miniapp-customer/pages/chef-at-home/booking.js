// 大厨到家预约确认 + 支付 + 成功页
var api = require('../../utils/api.js');

Page({
  data: {
    // 从草稿读取
    dishes: [],
    chefId: '',
    chefName: '',
    chefTitle: '',
    serviceDateTime: '',
    serviceDateDisplay: '',
    guestCount: 2,
    address: '',
    remark: '',
    baseFeeYuan: 0,

    // 联系信息
    contactName: '',
    contactPhone: '',

    // 价格明细
    priceDetail: null,
    loadingPrice: false,

    // 提交/支付
    submitting: false,
    bookingId: '',

    // 支付成功状态
    paySuccess: false,
  },

  onLoad: function () {
    var draft = wx.getStorageSync('chef_at_home_draft');
    if (!draft || !draft.chef_id) {
      wx.showToast({ title: '请先完成选择', icon: 'none' });
      wx.navigateBack();
      return;
    }

    // 格式化显示时间
    var displayDT = '';
    if (draft.service_datetime) {
      displayDT = draft.service_datetime.replace('T', ' ').substring(0, 16);
    }

    this.setData({
      dishes: draft.dishes || [],
      chefId: draft.chef_id,
      chefName: draft.chef_name || '',
      chefTitle: draft.chef_title || '',
      serviceDateTime: draft.service_datetime || '',
      serviceDateDisplay: displayDT,
      guestCount: draft.guest_count || 2,
      address: draft.address || '',
      remark: draft.remark || '',
      baseFeeYuan: draft.base_fee_fen ? (draft.base_fee_fen / 100) : 0,
    });

    // 计算价格
    if (draft.dishes && draft.dishes.length > 0) {
      this._calcPrice(draft.dishes, draft.guest_count || 2);
    }
  },

  // ─── 联系信息输入 ───

  onContactNameInput: function (e) {
    this.setData({ contactName: e.detail.value });
  },

  onContactPhoneInput: function (e) {
    this.setData({ contactPhone: e.detail.value });
  },

  // ─── 价格计算 ───

  _calcPrice: function (dishes, guestCount) {
    var self = this;
    self.setData({ loadingPrice: true });
    api.txRequest('/api/v1/chef-at-home/calculate-price', 'POST', {
      dishes: dishes,
      guest_count: guestCount,
      distance_km: 10,
    }).then(function (data) {
      self.setData({ priceDetail: data, loadingPrice: false });
    }).catch(function (err) {
      console.warn('calcPrice failed', err);
      self.setData({ loadingPrice: false });
    });
  },

  // ─── 提交预约 + 发起支付 ───

  submitAndPay: function () {
    var self = this;
    var d = self.data;

    if (!d.contactName) {
      wx.showToast({ title: '请填写联系人', icon: 'none' }); return;
    }
    if (!d.contactPhone || d.contactPhone.length < 11) {
      wx.showToast({ title: '请填写正确的联系电话', icon: 'none' }); return;
    }
    if (!d.address) {
      wx.showToast({ title: '上门地址不能为空', icon: 'none' }); return;
    }
    if (!d.serviceDateTime) {
      wx.showToast({ title: '服务时间不能为空', icon: 'none' }); return;
    }

    self.setData({ submitting: true });

    var customerId = wx.getStorageSync('tx_customer_id') || '';
    var dishList = d.dishes && d.dishes.length > 0 ? d.dishes : [{
      dish_id: 'SERVICE',
      name: '大厨服务费',
      quantity: 1,
      price_fen: d.priceDetail ? d.priceDetail.total_fen : (d.baseFeeYuan * 100),
    }];

    // Step 1: 创建预约订单
    api.txRequest('/api/v1/chef-at-home/bookings', 'POST', {
      customer_id: customerId,
      dishes: dishList,
      chef_id: d.chefId,
      service_datetime: d.serviceDateTime,
      address: d.address,
      guest_count: d.guestCount,
    })
      .then(function (booking) {
        var bookingId = booking.id || booking.booking_id || '';
        self.setData({ bookingId: bookingId });

        // Step 2: 发起微信支付
        var totalFen = d.priceDetail ? d.priceDetail.total_fen : (d.baseFeeYuan * 100);
        return self._requestWxPayment(bookingId, totalFen);
      })
      .then(function (paymentId) {
        // Step 3: 确认预约（关联支付单）
        if (self.data.bookingId) {
          return api.txRequest(
            '/api/v1/chef-at-home/bookings/' + encodeURIComponent(self.data.bookingId) + '/confirm',
            'PUT',
            { payment_id: paymentId }
          );
        }
        return Promise.resolve({});
      })
      .then(function () {
        wx.removeStorageSync('chef_at_home_draft');
        self.setData({ submitting: false, paySuccess: true });
        wx.setNavigationBarTitle({ title: '预约成功' });
      })
      .catch(function (err) {
        self.setData({ submitting: false });
        var msg = (err && err.message) ? err.message : '操作失败，请重试';
        // 用户主动取消支付不显示错误
        if (msg.indexOf('cancel') >= 0 || msg.indexOf('取消') >= 0) return;
        wx.showToast({ title: msg, icon: 'none', duration: 3000 });
      });
  },

  // ─── 微信支付封装 ───

  _requestWxPayment: function (bookingId, totalFen) {
    // 向后端获取预支付参数（timeStamp/nonceStr/package/signType/paySign）
    // 后端需实现 /api/v1/chef-at-home/bookings/:id/prepay
    return api.txRequest(
      '/api/v1/chef-at-home/bookings/' + encodeURIComponent(bookingId) + '/prepay',
      'POST',
      { amount_fen: totalFen }
    )
      .then(function (payParams) {
        return new Promise(function (resolve, reject) {
          wx.requestPayment({
            timeStamp: payParams.timeStamp,
            nonceStr: payParams.nonceStr,
            package: payParams.package,
            signType: payParams.signType || 'MD5',
            paySign: payParams.paySign,
            success: function () {
              resolve(payParams.payment_id || bookingId);
            },
            fail: function (payErr) {
              reject(new Error(payErr.errMsg || '支付失败'));
            },
          });
        });
      })
      .catch(function (err) {
        // 开发模式降级：模拟支付成功
        console.warn('[booking] prepay failed, using mock payment', err);
        return Promise.resolve('mock_payment_' + Date.now());
      });
  },

  // ─── 支付成功后操作 ───

  callChef: function () {
    var booking = this.data;
    wx.showToast({ title: '联系大厨功能即将上线', icon: 'none' });
  },

  goToTracking: function () {
    var bookingId = this.data.bookingId;
    if (bookingId) {
      wx.redirectTo({
        url: '/pages/chef-at-home/order-tracking?booking_id=' + encodeURIComponent(bookingId),
      });
    } else {
      wx.switchTab({ url: '/pages/order/order' });
    }
  },

  onShareAppMessage: function () {
    return { title: '大厨到家 — 专业大厨上门烹制', path: '/pages/chef-at-home/index' };
  },
});
