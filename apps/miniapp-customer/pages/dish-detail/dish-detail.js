// 菜品详情页 — 展示菜品详情、规格选择、加入购物车
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    // 菜品数据
    dish: {},
    loading: true,

    // 价格展示
    priceYuan: '0',
    originalPriceYuan: '',
    subtotalYuan: '0',

    // 规格
    specs: [],
    selectedSpec: '',
    selectedPriceFen: 0,

    // 数量
    qty: 1,

    // 过敏原展开
    showAllergen: false,

    // 相关推荐
    related: [],

    // 加入购物车动画
    adding: false,

    // 来源（用于返回）
    fromTable: '',
    fromStore: '',
  },

  onLoad: function (options) {
    var dishId = options.id || options.dish_id;
    var dishStr = options.dish;

    this.setData({
      fromTable: options.table || '',
      fromStore: options.store_id || '',
    });

    if (!dishId && !dishStr) {
      wx.showToast({ title: '菜品信息缺失', icon: 'none' });
      return;
    }

    // 优先从 URL 参数中直接用 dish 对象（省一次请求）
    if (dishStr) {
      try {
        var dish = JSON.parse(decodeURIComponent(dishStr));
        this._initFromDish(dish);
        // 同时拉取完整详情（过敏原/食材/相关推荐等额外字段）
        if (dish.id || dish.dish_id) {
          this._loadFullDetail(dish.id || dish.dish_id);
        }
        return;
      } catch (e) {
        // 解析失败则走网络请求
      }
    }

    // 走 API 请求
    this._loadFullDetail(dishId);
  },

  onShareAppMessage: function () {
    return {
      title: (this.data.dish.name || '菜品详情') + ' — ' + (this.data.dish.description || ''),
      path: '/pages/dish-detail/dish-detail?id=' + (this.data.dish.id || this.data.dish.dish_id || ''),
    };
  },

  // ─── 数据加载 ───

  _loadFullDetail: function (dishId) {
    var self = this;
    self.setData({ loading: true });

    api.fetchDishDetail(dishId)
      .then(function (data) {
        self._initFromDish(data);
      })
      .catch(function (err) {
        self.setData({ loading: false });
        wx.showToast({ title: err.message || '加载失败', icon: 'none' });
      });
  },

  _initFromDish: function (dish) {
    var self = this;

    // 统一字段名
    dish.id = dish.id || dish.dish_id;
    dish.name = dish.name || dish.dish_name;
    dish.priceFen = dish.priceFen || dish.price_fen || 0;
    dish.imageUrl = dish.imageUrl || dish.image_url;

    // 价格展示
    var priceYuan = (dish.priceFen / 100).toFixed(dish.priceFen % 100 === 0 ? 0 : 2);
    var originalPriceYuan = '';
    if (dish.originalPriceFen && dish.originalPriceFen > dish.priceFen) {
      originalPriceYuan = (dish.originalPriceFen / 100).toFixed(0);
    }

    // 构造规格列表（如有）
    var specs = [];
    if (dish.specs && dish.specs.length > 0) {
      specs = dish.specs.map(function (s) {
        return {
          key: s.key || s.name,
          name: s.name,
          priceFen: s.price_fen || dish.priceFen,
        };
      });
    } else if (dish.portions && dish.portions.length > 0) {
      // 兼容份量格式
      specs = dish.portions.map(function (p) {
        return {
          key: p.key || p.name,
          name: p.name,
          priceFen: p.price_fen || dish.priceFen,
        };
      });
    }

    var selectedSpec = specs.length > 0 ? specs[0].key : '';
    var selectedPriceFen = specs.length > 0 ? specs[0].priceFen : dish.priceFen;

    self.setData({
      dish: dish,
      loading: false,
      priceYuan: priceYuan,
      originalPriceYuan: originalPriceYuan,
      specs: specs,
      selectedSpec: selectedSpec,
      selectedPriceFen: selectedPriceFen,
    });
    self._updateSubtotal();

    // 加载相关推荐
    self._loadRelated(dish);
  },

  _loadRelated: function (dish) {
    var self = this;
    var storeId = self.data.fromStore || (app.globalData && app.globalData.storeId) || '';
    if (!storeId) return;

    api.fetchDishes(storeId, dish.category_id || dish.category)
      .then(function (data) {
        var dishes = (data.items || data || []).filter(function (d) {
          return (d.id || d.dish_id) !== dish.id;
        });
        // 最多显示6个
        var related = dishes.slice(0, 6).map(function (d) {
          return {
            id: d.id || d.dish_id,
            name: d.name || d.dish_name,
            imageUrl: d.imageUrl || d.image_url,
            priceYuan: (d.priceFen || d.price_fen || 0) > 0
              ? ((d.priceFen || d.price_fen) / 100).toFixed(0)
              : '0',
          };
        });
        self.setData({ related: related });
      })
      .catch(function () {});
  },

  // ─── 价格计算 ───

  _updateSubtotal: function () {
    var priceFen = this.data.selectedPriceFen || this.data.dish.priceFen || 0;
    var subtotal = priceFen * this.data.qty;
    this.setData({
      subtotalYuan: (subtotal / 100).toFixed(subtotal % 100 === 0 ? 0 : 2),
    });
  },

  // ─── 规格选择 ───

  selectSpec: function (e) {
    var key = e.currentTarget.dataset.key;
    var priceFen = parseInt(e.currentTarget.dataset.price, 10) || this.data.dish.priceFen;
    this.setData({ selectedSpec: key, selectedPriceFen: priceFen });
    this._updateSubtotal();
  },

  // ─── 数量控制 ───

  increaseQty: function () {
    this.setData({ qty: this.data.qty + 1 });
    this._updateSubtotal();
  },

  decreaseQty: function () {
    if (this.data.qty <= 1) return;
    this.setData({ qty: this.data.qty - 1 });
    this._updateSubtotal();
  },

  // ─── 过敏原展开 ───

  toggleAllergen: function () {
    this.setData({ showAllergen: !this.data.showAllergen });
  },

  // ─── 加入购物车 ───

  addToCart: function () {
    var self = this;
    var dish = self.data.dish;
    if (!dish || !dish.id) return;
    if (dish.is_soldout) {
      wx.showToast({ title: '该菜品已沽清', icon: 'none' });
      return;
    }

    // 构造购物车 item（与 cart.js 的数据格式对齐）
    var priceFen = self.data.selectedPriceFen || dish.priceFen;
    var specName = '';
    if (self.data.selectedSpec) {
      var matched = self.data.specs.filter(function (s) {
        return s.key === self.data.selectedSpec;
      });
      if (matched.length > 0) specName = matched[0].name;
    }

    var cartItem = {
      dishId: dish.id,
      dishName: dish.name + (specName ? '（' + specName + '）' : ''),
      quantity: self.data.qty,
      unitPriceFen: priceFen,
      imageUrl: dish.imageUrl || '',
      spec: specName,
      notes: '',
    };

    // 写入 globalData.cart
    var cart = (app.globalData && app.globalData.cart) || [];
    var found = false;
    var key = cartItem.dishId + '_' + specName;
    for (var i = 0; i < cart.length; i++) {
      var existKey = cart[i].dishId + '_' + (cart[i].spec || '');
      if (existKey === key) {
        cart[i] = Object.assign({}, cart[i], {
          quantity: cart[i].quantity + cartItem.quantity,
        });
        found = true;
        break;
      }
    }
    if (!found) {
      cart = cart.concat([cartItem]);
    }

    if (app.globalData) app.globalData.cart = cart;
    wx.setStorageSync('tx_cart', JSON.stringify(cart));

    // 动画反馈
    self.setData({ adding: true });
    setTimeout(function () {
      self.setData({ adding: false });
    }, 800);

    wx.showToast({ title: '已加入购物车', icon: 'success', duration: 1000 });
  },

  // ─── 相关推荐跳转 ───

  goRelated: function (e) {
    var id = e.currentTarget.dataset.id;
    wx.redirectTo({
      url: '/pages/dish-detail/dish-detail?id=' + encodeURIComponent(id) +
           '&table=' + encodeURIComponent(this.data.fromTable) +
           '&store_id=' + encodeURIComponent(this.data.fromStore),
    });
  },

  // ─── 返回 ───

  goBack: function () {
    wx.navigateBack({ delta: 1 });
  },
});
