/**
 * Dish Customize Component -- bottom sheet for spice/portion/method/topping selection
 * Also shows food origin traceability, nutrition info, and allergen warnings.
 */
Component({
  properties: {
    /** Whether the popup is visible */
    visible: {
      type: Boolean,
      value: false,
    },
    /** Dish object with full detail */
    dish: {
      type: Object,
      value: {},
    },
  },

  data: {
    // Customization selections
    selectedSpice: '',
    selectedPortion: '',
    selectedMethod: '',
    selectedToppings: [],
    quantity: 1,
    priceYuan: '0.00',
    totalPriceFen: 0,
    // Swiper
    currentImage: 0,
    // Default options when dish doesn't provide its own
    defaultSpiceOptions: [
      { id: 'none', label: '不辣' },
      { id: 'mild', label: '微辣' },
      { id: 'medium', label: '中辣' },
      { id: 'hot', label: '特辣' },
    ],
    defaultPortionOptions: [
      { id: 'small', label: '小份', extra_fen: 0 },
      { id: 'medium', label: '中份', extra_fen: 0 },
      { id: 'large', label: '大份', extra_fen: 800 },
    ],
    defaultMethodOptions: [
      { id: 'steam', label: '清蒸' },
      { id: 'braise', label: '红烧' },
      { id: 'boil', label: '白灼' },
      { id: 'stirfry', label: '爆炒' },
      { id: 'grill', label: '炭烤' },
    ],
    defaultToppingOptions: [
      { id: 'egg', label: '加蛋', price_fen: 200 },
      { id: 'meat', label: '加肉', price_fen: 500 },
      { id: 'cheese', label: '加芝士', price_fen: 300 },
      { id: 'veggie', label: '加蔬菜', price_fen: 100 },
    ],
    // Computed display arrays
    spiceList: [],
    portionList: [],
    methodList: [],
    toppingList: [],
  },

  observers: {
    'dish.price_fen': function (val) {
      if (val) {
        this.setData({
          priceYuan: (val / 100).toFixed(2),
          totalPriceFen: val,
        });
      }
    },
    visible: function (val) {
      if (val) {
        this._resetSelections();
      }
    },
  },

  methods: {
    _resetSelections: function () {
      var dish = this.data.dish;
      var spiceList = (dish.spice_options && dish.spice_options.length > 0) ? dish.spice_options : this.data.defaultSpiceOptions;
      var portionList = (dish.portion_options && dish.portion_options.length > 0) ? dish.portion_options : this.data.defaultPortionOptions;
      var methodList = (dish.method_options && dish.method_options.length > 0) ? dish.method_options : this.data.defaultMethodOptions;
      var toppingList = (dish.topping_options && dish.topping_options.length > 0) ? dish.topping_options : this.data.defaultToppingOptions;

      this.setData({
        spiceList: spiceList,
        portionList: portionList,
        methodList: methodList,
        toppingList: toppingList,
        selectedSpice: spiceList.length > 0 ? spiceList[0].id : '',
        selectedPortion: portionList.length > 0 ? portionList[0].id : '',
        selectedMethod: methodList.length > 0 ? methodList[0].id : '',
        selectedToppings: [],
        quantity: 1,
        totalPriceFen: dish.price_fen || 0,
      });
      this._recalcPrice();
    },

    selectSpice: function (e) {
      this.setData({ selectedSpice: e.currentTarget.dataset.id });
    },

    selectPortion: function (e) {
      var portionId = e.currentTarget.dataset.id;
      this.setData({ selectedPortion: portionId });
      this._recalcPrice();
    },

    selectMethod: function (e) {
      this.setData({ selectedMethod: e.currentTarget.dataset.id });
    },

    toggleTopping: function (e) {
      var toppingId = e.currentTarget.dataset.id;
      var selected = this.data.selectedToppings.slice();
      var idx = selected.indexOf(toppingId);
      if (idx >= 0) {
        selected.splice(idx, 1);
      } else {
        selected.push(toppingId);
      }
      this.setData({ selectedToppings: selected });
      this._recalcPrice();
    },

    changeQty: function (e) {
      var delta = parseInt(e.currentTarget.dataset.delta, 10);
      var qty = Math.max(1, this.data.quantity + delta);
      this.setData({ quantity: qty });
      this._recalcPrice();
    },

    _recalcPrice: function () {
      var dish = this.data.dish;
      var base = dish.price_fen || 0;

      // Portion price adjustment
      var portions = this.data.portionList;
      for (var i = 0; i < portions.length; i++) {
        if (portions[i].id === this.data.selectedPortion) {
          base += (portions[i].extra_fen || 0);
          break;
        }
      }

      // Topping price additions
      var toppings = this.data.toppingList;
      var selectedSet = {};
      this.data.selectedToppings.forEach(function (id) { selectedSet[id] = true; });
      for (var j = 0; j < toppings.length; j++) {
        if (selectedSet[toppings[j].id]) {
          base += (toppings[j].price_fen || 0);
        }
      }

      var total = base * this.data.quantity;
      this.setData({
        totalPriceFen: total,
        priceYuan: (total / 100).toFixed(2),
      });
    },

    onSwiperChange: function (e) {
      this.setData({ currentImage: e.detail.current });
    },

    onClose: function () {
      this.triggerEvent('close');
    },

    preventBubble: function () {},

    onConfirm: function () {
      var selectedToppingLabels = [];
      var toppings = this.data.toppingList;
      var selectedSet = {};
      this.data.selectedToppings.forEach(function (id) { selectedSet[id] = true; });
      for (var i = 0; i < toppings.length; i++) {
        if (selectedSet[toppings[i].id]) {
          selectedToppingLabels.push(toppings[i].label);
        }
      }

      this.triggerEvent('confirm', {
        dish: this.data.dish,
        spice: this.data.selectedSpice,
        portion: this.data.selectedPortion,
        method: this.data.selectedMethod,
        toppings: this.data.selectedToppings,
        toppingLabels: selectedToppingLabels,
        quantity: this.data.quantity,
        totalPriceFen: this.data.totalPriceFen,
      });
    },
  },
});
