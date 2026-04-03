// 桌台菜单 — 浏览菜品 + 购物车 + 同桌共享点餐
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    storeId: '',
    tableId: '',
    storeName: '屯象点餐',
    orderId: '',
    orderNo: '',
    isNewOrder: true,
    // 菜单
    categories: [],
    activeCategoryId: 'recommend',
    allDishes: [],
    filteredDishes: [],
    recommendations: [],
    loading: true,
    // 已点菜品（同桌共享）
    existingItems: [],
    // 购物车（本人当前批次）
    cartItems: [],
    cartCount: 0,
    cartTotalFen: 0,
    showCartPopup: false,
    // 搜索
    searchKeyword: '',
    // 轮询定时器
    _pollTimer: null,
  },

  onLoad: function (options) {
    var storeId = options.store_id || app.globalData.storeId;
    var tableId = options.table_id || '';

    if (!storeId || !tableId) {
      wx.showToast({ title: '参数错误', icon: 'none' });
      return;
    }

    this.setData({ storeId: storeId, tableId: tableId });
    this._initTableOrder();
  },

  onUnload: function () {
    if (this.data._pollTimer) {
      clearInterval(this.data._pollTimer);
    }
  },

  onShareAppMessage: function () {
    return {
      title: this.data.storeName + ' - ' + this.data.tableId + '号桌点餐',
      path: '/pages/scan-order/table-menu?store_id=' +
        this.data.storeId + '&table_id=' + this.data.tableId,
    };
  },

  // ─── 初始化 ───

  _initTableOrder: function () {
    var self = this;
    self.setData({ loading: true });

    api.scanOrderInit(self.data.tableId, self.data.storeId).then(function (data) {
      var menuItems = data.menu_items || [];
      var recommendations = data.recommendations || [];

      // 构造分类
      var catMap = {};
      var categoryList = [{ id: 'recommend', name: '推荐' }];
      menuItems.forEach(function (d) {
        if (d.category_id && !catMap[d.category_id]) {
          catMap[d.category_id] = true;
          categoryList.push({ id: d.category_id, name: d.category_name || d.category_id });
        }
      });

      // 推荐标记
      var recommendedIds = {};
      recommendations.forEach(function (r) {
        recommendedIds[r.dish_id] = r.reason;
      });

      menuItems.forEach(function (d) {
        d.id = d.dish_id;
        d.name = d.dish_name;
        d.priceFen = d.price_fen;
        d.priceYuan = (d.price_fen / 100).toFixed(2);
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

      // 启动轮询（同桌共享：定期刷新已点菜品）
      self._startPolling();
    }).catch(function (err) {
      self.setData({ loading: false });
      wx.showToast({ title: err.message || '加载失败', icon: 'none' });
    });
  },

  // ─── 同桌共享轮询 ───

  _startPolling: function () {
    var self = this;
    if (self.data._pollTimer) clearInterval(self.data._pollTimer);

    var timer = setInterval(function () {
      self._refreshTableOrder();
    }, 15000); // 每15秒刷新
    self.setData({ _pollTimer: timer });
  },

  _refreshTableOrder: function () {
    var self = this;
    if (!self.data.storeId || !self.data.tableId) return;

    api.txRequest(
      '/api/v1/scan-order/table-order?store_id=' +
      encodeURIComponent(self.data.storeId) +
      '&table_id=' + encodeURIComponent(self.data.tableId)
    ).then(function (data) {
      if (data && data.items) {
        self.setData({ existingItems: data.items });
      }
    }).catch(function () {
      // 静默失败
    });
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

  // ─── 筛选菜品 ───

  _filterDishes: function () {
    var self = this;
    var dishes = self.data.allDishes;
    var catId = self.data.activeCategoryId;
    var keyword = self.data.searchKeyword.toLowerCase();
    var filtered = dishes;

    if (catId === 'recommend') {
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
        return d.category_id === catId;
      });
    }

    if (keyword) {
      filtered = filtered.filter(function (d) {
        return (d.name || '').toLowerCase().indexOf(keyword) >= 0;
      });
    }

    self.setData({ filteredDishes: filtered });
  },

  // ─── 购物车操作 ───

  addToCart: function (e) {
    var dish = e.currentTarget.dataset.dish;
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

  minusFromCart: function (e) {
    var dishId = e.currentTarget.dataset.dishid;
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
      total += (item.dish.priceFen || 0) * item.quantity;
    });

    this.setData({
      cartItems: cart,
      cartCount: count,
      cartTotalFen: total,
    });
  },

  getCartQty: function (dishId) {
    var items = this.data.cartItems;
    for (var i = 0; i < items.length; i++) {
      if (items[i].dish.id === dishId) return items[i].quantity;
    }
    return 0;
  },

  // ─── 购物车弹层 ───

  showCart: function () {
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

  // ─── 去确认下单 ───

  goToConfirm: function () {
    if (this.data.cartCount === 0) return;

    var items = this.data.cartItems.map(function (item) {
      return {
        dishId: item.dish.id || item.dish.dish_id,
        dishName: item.dish.name || item.dish.dish_name,
        quantity: item.quantity,
        unitPriceFen: item.dish.priceFen || item.dish.price_fen || 0,
        imageUrl: item.dish.imageUrl || item.dish.image_url || '',
      };
    });

    wx.navigateTo({
      url: '/pages/scan-order/confirm?store_id=' + this.data.storeId +
        '&table_id=' + this.data.tableId +
        '&order_id=' + this.data.orderId +
        '&items=' + encodeURIComponent(JSON.stringify(items)) +
        '&total=' + this.data.cartTotalFen,
    });
  },

  // ─── 查看订单状态 ───

  viewStatus: function () {
    if (!this.data.orderId) return;
    wx.navigateTo({
      url: '/pages/scan-order/status?order_id=' + this.data.orderId +
        '&order_no=' + this.data.orderNo,
    });
  },

  // ─── 查看已点菜品 ───

  viewExistingItems: function () {
    this.setData({ showCartPopup: false });
    this.viewStatus();
  },
});
