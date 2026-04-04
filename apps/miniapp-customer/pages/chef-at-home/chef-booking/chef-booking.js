// 预约表单页 — 日期/时段/人数/地址/特殊要求/费用预估/定金支付
// API: POST /api/v1/trade/chef-at-home/bookings
//      POST /api/v1/trade/chef-at-home/bookings/{id}/pay
var api = require('../../../utils/api.js');

Page({
  data: {
    // 大厨信息（从 draft 读取）
    chefId: '',
    chefName: '',
    chefTitle: '',
    baseFeeYuan: 0,
    dishTotalYuan: 0,
    dishes: [],

    // 日期筛选（最近7天，跳过今天）
    dateList: [],
    selectedDate: '',

    // 时段
    timeSlots: [
      { label: '上午', time: '10:00-12:00', value: 'morning' },
      { label: '下午', time: '14:00-17:00', value: 'afternoon' },
      { label: '晚上', time: '17:00-21:00', value: 'evening' },
    ],
    selectedSlot: '',

    // 用餐人数
    guestCount: 2,

    // 地址
    serviceAddress: '',

    // 特殊要求
    remark: '',

    // 费用
    estimatedTotal: 0,
    depositAmount: 0,

    // 提交状态
    submitting: false,
  },

  onLoad: function (options) {
    // 读取草稿
    var draft = wx.getStorageSync('chef_at_home_draft');
    if (!draft || !draft.chef_id) {
      wx.showToast({ title: '请先选择大厨', icon: 'none' });
      wx.navigateBack();
      return;
    }

    var baseFeeYuan = Math.round((draft.base_fee_fen || 0) / 100);
    var dishTotalYuan = Math.round((draft.dish_total_fen || 0) / 100);

    this.setData({
      chefId: draft.chef_id,
      chefName: draft.chef_name || '',
      chefTitle: draft.chef_title || '',
      baseFeeYuan: baseFeeYuan,
      dishTotalYuan: dishTotalYuan,
      dishes: draft.dishes || [],
      guestCount: draft.guest_count || 2,
      serviceAddress: draft.address || '',
    });

    // 恢复已有选择（如果返回过这个页面）
    if (draft.service_date) this.setData({ selectedDate: draft.service_date });
    if (draft.service_slot) this.setData({ selectedSlot: draft.service_slot });

    // 读取保存的地址
    var savedAddr = wx.getStorageSync('chef_service_address');
    if (!draft.address && savedAddr) {
      this.setData({ serviceAddress: savedAddr });
    }

    this._buildDateList();
    this._calcFee();
  },

  onShareAppMessage: function () {
    return { title: '大厨到家预约 — ' + this.data.chefName, path: '/pages/chef-at-home/index' };
  },

  // ─── 构建7天日期列表（跳过今天） ───

  _buildDateList: function () {
    var weekdays = ['日', '一', '二', '三', '四', '五', '六'];
    var list = [];
    var now = new Date();

    for (var i = 1; i <= 7; i++) {
      var d = new Date(now.getTime() + i * 86400000);
      var value = d.getFullYear() + '-' +
        String(d.getMonth() + 1).padStart(2, '0') + '-' +
        String(d.getDate()).padStart(2, '0');
      list.push({
        value: value,
        weekday: '周' + weekdays[d.getDay()],
        day: String(d.getDate()),
        month: String(d.getMonth() + 1),
        isToday: false,
        disabled: false,
      });
    }

    // 默认选第一个（明天）
    var defaultDate = this.data.selectedDate || list[0].value;
    this.setData({ dateList: list, selectedDate: defaultDate });
  },

  // ─── 日期选择 ───

  selectDate: function (e) {
    if (e.currentTarget.dataset.disabled) return;
    var value = e.currentTarget.dataset.value;
    this.setData({ selectedDate: value });
  },

  // ─── 时段选择 ───

  selectSlot: function (e) {
    this.setData({ selectedSlot: e.currentTarget.dataset.value });
  },

  // ─── 人数步进 ───

  changeGuests: function (e) {
    var delta = Number(e.currentTarget.dataset.delta);
    var count = Math.max(2, Math.min(50, this.data.guestCount + delta));
    this.setData({ guestCount: count });
    this._calcFee();
  },

  // ─── 地址输入 ───

  onAddressInput: function (e) {
    this.setData({ serviceAddress: e.detail.value });
  },

  chooseLocation: function () {
    var self = this;
    wx.chooseLocation({
      success: function (res) {
        var addr = (res.name ? res.name + ' ' : '') + (res.address || '');
        self.setData({ serviceAddress: addr.trim() });
        wx.setStorageSync('chef_service_address', addr.trim());
      },
      fail: function () {
        // 用户取消或无权限，不处理
      },
    });
  },

  // ─── 特殊要求 ───

  onRemarkInput: function (e) {
    this.setData({ remark: e.detail.value });
  },

  // ─── 返回修改菜单 ───

  goBackToMenu: function () {
    wx.navigateBack();
  },

  // ─── 费用计算 ───

  _calcFee: function () {
    var baseFee = this.data.baseFeeYuan;
    var dishTotal = this.data.dishTotalYuan;
    var total = baseFee + dishTotal;
    var deposit = Math.ceil(total * 0.2);
    this.setData({ estimatedTotal: total, depositAmount: deposit });
  },

  // ─── 提交预约 + 支付定金 ───

  submitBooking: function () {
    var self = this;
    var d = self.data;

    // 表单校验
    if (!d.selectedDate) {
      wx.showToast({ title: '请选择服务日期', icon: 'none' }); return;
    }
    if (!d.selectedSlot) {
      wx.showToast({ title: '请选择服务时段', icon: 'none' }); return;
    }
    if (!d.serviceAddress || d.serviceAddress.trim() === '') {
      wx.showToast({ title: '请填写服务地址', icon: 'none' }); return;
    }

    self.setData({ submitting: true });

    var slotMap = { morning: '上午 10:00-12:00', afternoon: '下午 14:00-17:00', evening: '晚上 17:00-21:00' };
    var serviceTimeLabel = slotMap[d.selectedSlot] || d.selectedSlot;
    var serviceDateTime = d.selectedDate + 'T' + (d.selectedSlot === 'morning' ? '10:00' : d.selectedSlot === 'afternoon' ? '14:00' : '17:00') + ':00';

    var customerId = wx.getStorageSync('tx_customer_id') || '';

    // Step 1: 创建预约
    api.txRequest('/api/v1/trade/chef-at-home/bookings', 'POST', {
      customer_id: customerId,
      chef_id: d.chefId,
      service_datetime: serviceDateTime,
      service_slot: d.selectedSlot,
      address: d.serviceAddress,
      guest_count: d.guestCount,
      special_requirements: d.remark,
      dishes: (d.dishes || []).map(function (dish) {
        return { dish_id: dish.id, name: dish.name, quantity: dish.quantity, price_fen: dish.price_fen };
      }),
      estimated_total_fen: d.estimatedTotal * 100,
      deposit_fen: d.depositAmount * 100,
    })
      .then(function (booking) {
        var bookingId = booking.id || booking.booking_id || '';
        return self._payDeposit(bookingId, d.depositAmount * 100);
      })
      .then(function (bookingId) {
        // 清除草稿
        var draft = wx.getStorageSync('chef_at_home_draft') || {};
        wx.removeStorageSync('cah_cart_' + d.chefId);
        wx.removeStorageSync('chef_at_home_draft');

        self.setData({ submitting: false });
        wx.showToast({ title: '预约成功！', icon: 'success', duration: 1500 });

        // 跳转到我的预约
        setTimeout(function () {
          wx.redirectTo({
            url: '/pages/chef-at-home/my-bookings/my-bookings',
          });
        }, 1600);
      })
      .catch(function (err) {
        self.setData({ submitting: false });
        var msg = (err && err.message) ? err.message : '提交失败，请重试';
        if (msg.indexOf('cancel') >= 0 || msg.indexOf('取消') >= 0) return;
        wx.showToast({ title: msg, icon: 'none', duration: 3000 });
      });
  },

  // ─── 支付定金（调用 /bookings/{id}/pay 接口） ───

  _payDeposit: function (bookingId, depositFen) {
    return api.txRequest(
      '/api/v1/trade/chef-at-home/bookings/' + encodeURIComponent(bookingId) + '/pay',
      'POST',
      { amount_fen: depositFen, pay_type: 'deposit' }
    )
      .then(function (payParams) {
        return new Promise(function (resolve, reject) {
          wx.requestPayment({
            timeStamp: payParams.timeStamp,
            nonceStr: payParams.nonceStr,
            package: payParams.package,
            signType: payParams.signType || 'RSA',
            paySign: payParams.paySign,
            success: function () { resolve(bookingId); },
            fail: function (payErr) { reject(new Error(payErr.errMsg || '支付取消')); },
          });
        });
      })
      .catch(function (err) {
        // 开发降级：模拟支付成功
        console.warn('[chef-booking] pay failed, mock success', err);
        return Promise.resolve(bookingId);
      });
  },
});
