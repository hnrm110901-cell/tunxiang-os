// 菜单浏览 + 点餐页
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    storeName: '屯象点餐',
    tableNo: '',
    // 扫码点单
    scanOrderMode: false,
    orderId: '',
    orderNo: '',
    isNewOrder: true,
    existingItems: [],
    recommendations: [],  // AI 智能推荐
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
    // 出餐进度
    showStatusPopup: false,
    orderStatus: null,
  },

  onLoad: function (options) {
    var tableNo = options.table || '';
    this.setData({
      tableNo: tableNo,
      storeName: options.store_name ? decodeURIComponent(options.store_name) : '屯象点餐',
    });

    // 如果有桌号，走扫码点单流程
    if (tableNo) {
      this.setData({ scanOrderMode: true });
      this._initScanOrder(tableNo);
    }
  },

  onShow: function () {
    if (!this.data.scanOrderMode) {
      this._loadMenu();
    }
  },

  onShareAppMessage: function () {
    return {
      title: this.data.storeName + ' - 在线点餐',
      path: '/pages/menu/menu',
    };
  },

  // ─── 扫码点单 ───

  _initScanOrder: function (tableNo) {
    var self = this;
    self.setData({ loading: true });

    api.scanOrderInit(tableNo).then(function (data) {
      var menuItems = data.menu_items || [];
      var recommendations = data.recommendations || [];

      // 构造分类列表，首项为"推荐"
      var catMap = {};
      var categoryList = [{ id: 'recommend', name: '推荐' }];
      menuItems.forEach(function (d) {
        if (d.category_id && !catMap[d.category_id]) {
          catMap[d.category_id] = true;
          categoryList.push({ id: d.category_id, name: d.category_name || d.category_id });
        }
      });

      // 给推荐菜品打上推荐标签
      var recommendedIds = {};
      recommendations.forEach(function (r) {
        recommendedIds[r.dish_id] = r.reason;
      });

      // 标记菜品的推荐理由
      menuItems.forEach(function (d) {
        d.id = d.dish_id;
        d.name = d.dish_name;
        d.priceFen = d.price_fen;
        d.imageUrl = d.image_url;
        if (recommendedIds[d.dish_id]) {
          d.recommendReason = recommendedIds[d.dish_id];
        }
      });

      self.setData({
        orderId: data.order_id || '',
        orderNo: data.order_no || '',
        isNewOrder: data.is_new_order,
        existingItems: data.existing_items || [],
        recommendations: recommendations,
        categories: categoryList,
        activeCategoryId: 'recommend',
        allDishes: menuItems,
        loading: false,
      });
      self._filterDishes();
    }).catch(function (err) {
      self.setData({ loading: false });
      wx.showToast({ title: err.message || '加载失败', icon: 'none' });
      // 降级到普通菜单模式
      self.setData({ scanOrderMode: false });
      self._loadMenu();
    });
  },

  _submitToKitchen: function () {
    var self = this;
    if (!self.data.orderId) {
      wx.showToast({ title: '请先点菜', icon: 'none' });
      return;
    }

    wx.showLoading({ title: '提交中...' });
    api.scanOrderSubmit(self.data.orderId).then(function (data) {
      wx.hideLoading();
      wx.showToast({ title: '已提交厨房', icon: 'success' });
      // 清空购物车（已提交的菜品不可修改）
      self.clearCart();
    }).catch(function (err) {
      wx.hideLoading();
      wx.showToast({ title: err.message || '提交失败', icon: 'none' });
    });
  },

  _checkOrderStatus: function () {
    var self = this;
    if (!self.data.orderId) return;

    api.scanOrderStatus(self.data.orderId).then(function (data) {
      self.setData({
        orderStatus: data,
        showStatusPopup: true,
      });
    }).catch(function (err) {
      wx.showToast({ title: err.message || '查询失败', icon: 'none' });
    });
  },

  closeStatusPopup: function () {
    this.setData({ showStatusPopup: false });
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
    if (catId === 'recommend') {
      // 推荐分类：推荐菜品置顶
      var recommendedIds = {};
      self.data.recommendations.forEach(function (r) {
        recommendedIds[r.dish_id] = true;
      });
      var recommended = filtered.filter(function (d) {
        return recommendedIds[d.dish_id || d.id];
      });
      var others = filtered.filter(function (d) {
        return !recommendedIds[d.dish_id || d.id];
      });
      filtered = recommended.concat(others);
    } else if (catId) {
      filtered = filtered.filter(function (d) {
        return d.category === catId || d.category_name === catId || d.category_id === catId;
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
    var self = this;
    var cart = self.data.cartItems.slice();
    var idx = -1;
    for (var i = 0; i < cart.length; i++) {
      if (cart[i].dish.id === dish.id) { idx = i; break; }
    }

    if (idx >= 0) {
      cart[idx] = { dish: cart[idx].dish, quantity: cart[idx].quantity + 1 };
    } else {
      cart.push({ dish: dish, quantity: 1 });
    }

    self._updateCart(cart);

    // 扫码点单模式：同步加菜到服务端
    if (self.data.scanOrderMode && self.data.orderId) {
      api.scanOrderAddItem(
        self.data.orderId,
        dish.dish_id || dish.id,
        1,
        ''
      ).catch(function (err) {
        wx.showToast({ title: err.message || '加菜失败', icon: 'none' });
      });
    }
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

    // 扫码点单模式：提交到厨房
    if (this.data.scanOrderMode) {
      this._submitToKitchen();
      return;
    }

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

  // ─── 出餐进度 ───

  viewOrderStatus: function () {
    this._checkOrderStatus();
  },
});
