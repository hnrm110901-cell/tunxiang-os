/**
 * 菜品卡片组件
 * 展示菜品图片、名称、价格、加减数量
 */
Component({
  properties: {
    dish: {
      type: Object,
      value: {},
    },
    quantity: {
      type: Number,
      value: 0,
    },
  },

  computed: {},

  data: {
    priceYuan: '0',
    originalPriceYuan: '0',
  },

  observers: {
    'dish.priceFen': function (val) {
      this.setData({ priceYuan: (val / 100).toFixed(val % 100 === 0 ? 0 : 2) });
    },
    'dish.originalPriceFen': function (val) {
      if (val) {
        this.setData({ originalPriceYuan: (val / 100).toFixed(val % 100 === 0 ? 0 : 2) });
      }
    },
  },

  methods: {
    onTapCard: function () {
      this.triggerEvent('detail', { dish: this.data.dish });
    },

    onPlus: function () {
      this.triggerEvent('add', { dish: this.data.dish });
    },

    onMinus: function () {
      this.triggerEvent('minus', { dish: this.data.dish });
    },
  },
});
