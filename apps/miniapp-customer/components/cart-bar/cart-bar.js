/**
 * 底部购物车栏组件
 * 固定在页面底部，展示已选数量、总价，提供结算入口
 */
Component({
  properties: {
    count: {
      type: Number,
      value: 0,
    },
    totalFen: {
      type: Number,
      value: 0,
    },
    deliveryFeeText: {
      type: String,
      value: '',
    },
    alwaysShow: {
      type: Boolean,
      value: false,
    },
  },

  data: {
    totalYuan: '0.00',
  },

  observers: {
    totalFen: function (val) {
      this.setData({
        totalYuan: (val / 100).toFixed(2),
      });
    },
  },

  methods: {
    onTapCart: function () {
      this.triggerEvent('showcart');
    },

    onCheckout: function () {
      this.triggerEvent('checkout');
    },
  },
});
