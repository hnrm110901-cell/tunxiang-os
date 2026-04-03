/**
 * 套餐分组内商品行组件
 * Props: item（菜品信息）、maxSelect（最大可选数）、selectedCount（当前已选数）
 * Emits: add、remove
 */
Component({
  properties: {
    item: {
      type: Object,
      value: {},
    },
    maxSelect: {
      type: Number,
      value: 1,
    },
    selectedCount: {
      type: Number,
      value: 0,
    },
    // 整个分组已选总数（用于判断是否达到上限）
    groupSelectedTotal: {
      type: Number,
      value: 0,
    },
  },

  data: {
    extraPriceYuan: '0',
    reachedMax: false,
  },

  observers: {
    'item.extra_price_fen': function (val) {
      if (val) {
        this.setData({
          extraPriceYuan: (val / 100).toFixed(val % 100 === 0 ? 0 : 2),
        });
      }
    },
    'selectedCount, groupSelectedTotal, maxSelect': function (selected, groupTotal, max) {
      // "+"按钮灰掉条件：自身已选达到组内上限，或整组已达上限
      var reachedMax = (selected > 0 && max === 1) || groupTotal >= max;
      this.setData({ reachedMax: reachedMax });
    },
  },

  methods: {
    onPlus: function () {
      if (this.data.reachedMax) return;
      this.triggerEvent('add', { item: this.data.item });
    },

    onMinus: function () {
      if (this.data.selectedCount <= 0) return;
      this.triggerEvent('remove', { item: this.data.item });
    },
  },
});
