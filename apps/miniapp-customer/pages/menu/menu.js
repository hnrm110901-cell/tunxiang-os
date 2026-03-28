// 菜单浏览 + 点餐页
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    storeName: '屯象点餐',
    tableNo: '',
    // 分类
    categories: [],
    activeCategoryId: '',
    // 菜品
    allDishes: [],
    filteredDishes: [],
    loading: true,
    // 购物车
    cartItems: [],    // [{dish, quantity}]
    cartCount: 0,
    cartTotalFen: 0,
    showCartPopup: false,
    // 搜索
    searchKeyword: '',
  },

  onLoad: function (options) {
    this.setData({
      tableNo: options.table || '',
      storeName: options.store_name ? decodeURIComponent(options.store_name) : '屯象点餐',
    });
  },

  onShow: function () {
    this._loadMenu();
  },

  onShareAppMessage: function () {
    return {
      title: this.data.storeName + ' - 在线点餐',
      path: '/pages/menu/menu',
    };
  },

  // ─── 数据加载 ───

  _loadMenu: function () {
    var self = this;
    var storeId = app.globalData.storeId;
    self.setData({ loading: true });

    Promise.all([
      api.fetchCategories(storeId).catch(function () { return { categories: [] }; }),
      api.fetchDishes(storeId).catch(function () { return { items: [] }; }),
    ]).then(function (results) {
      var cats = results[0].categories || results[0] || [];
      var dishes = results[1].items || results[1] || [];

      // 构造分类列表，首项为"推荐"
      var categoryList = [{ id: 'recommend', name: '推荐' }];
      if (Array.isArray(cats)) {
        cats.forEach(function (c) {
          categoryList.push({
            id: typeof c === 'string' ? c : (c.id || c.name),
            name: typeof c === 'string' ? c : c.name,
          });
        });
      }

      self.setData({
        categories: categoryList,
        activeCategoryId: 'recommend',
        allDishes: dishes,
        loading: false,
      });
      self._filterDishes();
    }).catch(function () {
      self.setData({ loading: false });
    });
  },

  _filterDishes: function () {
    var self = this;
    var dishes = self.data.allDishes;
    var catId = self.data.activeCategoryId;
    var keyword = self.data.searchKeyword.toLowerCase();

    var filtered = dishes;

    // 分类筛选
    if (catId && catId !== 'recommend') {
      filtered = filtered.filter(function (d) {
        return d.category === catId || d.category_name === catId;
      });
    }

    // 搜索筛选
    if (keyword) {
      filtered = filtered.filter(function (d) {
        return (d.name || '').toLowerCase().indexOf(keyword) >= 0;
      });
    }

    self.setData({ filteredDishes: filtered });
  },

  // ─── 分类切换 ───

  selectCategory: function (e) {
    this.setData({ activeCategoryId: e.currentTarget.dataset.id });
    this._filterDishes();
  },

  // ─── 搜索 ───

  onSearchInput: function (e) {
    this.setData({ searchKeyword: e.detail.value });
    this._filterDishes();
  },

  clearSearch: function () {
    this.setData({ searchKeyword: '' });
    this._filterDishes();
  },

  // ─── 购物车操作 ───

  onDishAdd: function (e) {
    var dish = e.detail.dish;
    this._addToCart(dish);
  },

  onDishMinus: function (e) {
    var dish = e.detail.dish;
    this._removeFromCart(dish.id);
  },

  _addToCart: function (dish) {
    var cart = this.data.cartItems.slice();
    var idx = -1;
    for (var i = 0; i < cart.length; i++) {
      if (cart[i].dish.id === dish.id) { idx = i; break; }
    }

    if (idx >= 0) {
      cart[idx] = { dish: cart[idx].dish, quantity: cart[idx].quantity + 1 };
    } else {
      cart.push({ dish: dish, quantity: 1 });
    }

    this._updateCart(cart);
  },

  _removeFromCart: function (dishId) {
    var cart = this.data.cartItems.slice();
    var idx = -1;
    for (var i = 0; i < cart.length; i++) {
      if (cart[i].dish.id === dishId) { idx = i; break; }
    }

    if (idx >= 0) {
      if (cart[idx].quantity > 1) {
        cart[idx] = { dish: cart[idx].dish, quantity: cart[idx].quantity - 1 };
      } else {
        cart.splice(idx, 1);
      }
    }

    this._updateCart(cart);
  },

  _updateCart: function (cart) {
    var count = 0;
    var total = 0;
    cart.forEach(function (item) {
      count += item.quantity;
      total += (item.dish.priceFen || item.dish.price_fen || 0) * item.quantity;
    });

    this.setData({
      cartItems: cart,
      cartCount: count,
      cartTotalFen: total,
    });
  },

  getQuantityForDish: function (dishId) {
    var items = this.data.cartItems;
    for (var i = 0; i < items.length; i++) {
      if (items[i].dish.id === dishId) return items[i].quantity;
    }
    return 0;
  },

  // ─── 购物车弹层 ───

  onShowCart: function () {
    if (this.data.cartCount > 0) {
      this.setData({ showCartPopup: true });
    }
  },

  closeCartPopup: function () {
    this.setData({ showCartPopup: false });
  },

  clearCart: function () {
    this.setData({
      cartItems: [],
      cartCount: 0,
      cartTotalFen: 0,
      showCartPopup: false,
    });
  },

  // ─── 结算 ───

  goToCheckout: function () {
    if (this.data.cartCount === 0) return;

    var orderItems = this.data.cartItems.map(function (item) {
      return {
        dishId: item.dish.id || item.dish.dish_id,
        dishName: item.dish.name || item.dish.dish_name,
        quantity: item.quantity,
        unitPriceFen: item.dish.priceFen || item.dish.price_fen || 0,
        imageUrl: item.dish.imageUrl || item.dish.image_url || '',
      };
    });

    wx.navigateTo({
      url: '/pages/order/order?items=' + encodeURIComponent(JSON.stringify(orderItems)) +
           '&total=' + this.data.cartTotalFen +
           '&table=' + (this.data.tableNo || ''),
    });
  },
});
