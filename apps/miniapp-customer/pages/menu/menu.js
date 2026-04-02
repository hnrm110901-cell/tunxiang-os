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
    // 搜索 (含语音)
    searchKeyword: '',
    isVoiceListening: false,
    // 购物车菜品ID列表 (用于AI推荐)
    cartDishIds: [],
    // 出餐进度
    showStatusPopup: false,
    orderStatus: null,
    // Dish customize popup
    showDishCustomize: false,
    customizeDish: {},
    // Smart addon suggestion
    addonSuggestion: '',
    // Cart-based AI recommendations
    cartRecommendations: [],
    storeId: '',
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
      // 清空购物车（已提交的菜品不可修改）
      self.clearCart();
      // 跳转到等待出餐页
      wx.navigateTo({
        url: '/pages/scan-order/status?order_id=' + encodeURIComponent(self.data.orderId) +
             '&order_no=' + encodeURIComponent(self.data.orderNo) +
             '&table_no=' + encodeURIComponent(self.data.tableNo),
      });
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

  startVoiceSearch: function () {
    var self = this;
    self.setData({ isVoiceListening: true });
    var recManager = wx.getRecorderManager();
    recManager.onStop(function (res) {
      self.setData({ isVoiceListening: false });
      wx.uploadFile({
        url: (app.globalData.apiBase || '') + '/api/v1/self-order/voice-search',
        filePath: res.tempFilePath,
        name: 'audio',
        success: function (uploadRes) {
          try {
            var data = JSON.parse(uploadRes.data);
            if (data.ok && data.data && data.data.text) {
              self.setData({ searchKeyword: data.data.text });
              self._filterDishes();
            }
          } catch (parseErr) {
            wx.showToast({ title: '语音识别失败', icon: 'none' });
          }
        },
        fail: function () {
          wx.showToast({ title: '语音上传失败', icon: 'none' });
        },
      });
    });
    recManager.start({ duration: 10000, format: 'mp3' });
    setTimeout(function () {
      if (self.data.isVoiceListening) {
        recManager.stop();
      }
    }, 5000);
  },

  stopVoiceSearch: function () {
    this.setData({ isVoiceListening: false });
    var recManager = wx.getRecorderManager();
    recManager.stop();
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
    var dishIds = [];
    cart.forEach(function (item) {
      count += item.quantity;
      total += (item.dish.priceFen || item.dish.price_fen || 0) * item.quantity;
      dishIds.push(item.dish.id || item.dish.dish_id);
    });

    this.setData({
      cartItems: cart,
      cartCount: count,
      cartTotalFen: total,
      cartDishIds: dishIds,
    });
    this._updateAddonSuggestion();
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
        notes: item.dish.notes || '',
      };
    });

    // Navigate to smart cart page
    wx.navigateTo({
      url: '/pages/cart/cart?items=' + encodeURIComponent(JSON.stringify(orderItems)) +
           '&total=' + this.data.cartTotalFen +
           '&table=' + (this.data.tableNo || ''),
    });
  },

  // ─── 出餐进度 ───

  viewOrderStatus: function () {
    this._checkOrderStatus();
  },

  // ─── Dish customize popup ───

  onDishDetail: function (e) {
    var dish = e.detail.dish;
    // Fetch full dish detail for customization
    var self = this;
    api.fetchDishDetail(dish.id || dish.dish_id)
      .then(function (detail) {
        self.setData({
          customizeDish: detail,
          showDishCustomize: true,
        });
      })
      .catch(function () {
        // Fallback: use basic dish data
        self.setData({
          customizeDish: dish,
          showDishCustomize: true,
        });
      });
  },

  closeDishCustomize: function () {
    this.setData({ showDishCustomize: false });
  },

  onDishCustomizeConfirm: function (e) {
    var detail = e.detail;
    var dish = detail.dish;
    // Add to cart with customization notes
    var customDish = Object.assign({}, dish, {
      _customSpice: detail.spice,
      _customPortion: detail.portion,
      _customToppings: detail.toppings,
      priceFen: detail.totalPriceFen,
      price_fen: detail.totalPriceFen,
    });
    var qty = detail.quantity || 1;
    for (var i = 0; i < qty; i++) {
      this._addToCart(customDish);
    }
    this.setData({ showDishCustomize: false });
    wx.showToast({ title: '已加入购物车', icon: 'success' });
  },

  // ─── 套餐选择 ───

  onComboSelect: function (e) {
    var dish = e.currentTarget.dataset.dish;
    var comboId = dish.combo_id || dish.id;
    if (!comboId) {
      wx.showToast({ title: '套餐信息缺失', icon: 'none' });
      return;
    }
    wx.navigateTo({
      url: '/pages/combo-detail/combo-detail' +
        '?combo_id=' + encodeURIComponent(comboId) +
        '&combo_name=' + encodeURIComponent(dish.name || dish.dish_name || '套餐') +
        '&base_price=' + (dish.priceFen || dish.price_fen || 0) +
        '&serve_count=' + (dish.serve_count || 0) +
        '&table=' + encodeURIComponent(this.data.tableNo || ''),
    });
  },

  // ─── AI recommendations (cart-context) ───

  onRecommendAdd: function (e) {
    var dish = e.detail.dish;
    this._addToCart(dish);
  },

  onRecommendSelect: function (e) {
    var dish = e.detail.dish;
    this.setData({
      customizeDish: dish,
      showDishCustomize: true,
    });
  },

  // ─── Smart addon suggestion ───

  _updateAddonSuggestion: function () {
    var self = this;
    var total = self.data.cartTotalFen;
    // Check common thresholds
    var thresholds = [5000, 8000, 10000, 15000]; // 50, 80, 100, 150 yuan
    var nearestThreshold = null;
    for (var i = 0; i < thresholds.length; i++) {
      if (total > 0 && total < thresholds[i] && (thresholds[i] - total) <= 2000) {
        nearestThreshold = thresholds[i];
        break;
      }
    }

    if (nearestThreshold) {
      var gap = nearestThreshold - total;
      var gapYuan = (gap / 100).toFixed(0);
      self.setData({
        addonSuggestion: '再点' + gapYuan + '元享满' + (nearestThreshold / 100) + '减优惠',
      });
    } else if (total > 0) {
      // Check if missing category
      var hasDrink = false;
      var hasStaple = false;
      self.data.cartItems.forEach(function (item) {
        var tags = item.dish.tags || [];
        if (tags.indexOf('drink') >= 0 || tags.indexOf('beverage') >= 0) hasDrink = true;
        if (tags.indexOf('staple') >= 0 || tags.indexOf('rice') >= 0 || tags.indexOf('noodle') >= 0) hasStaple = true;
      });
      if (!hasStaple && self.data.cartCount >= 2) {
        self.setData({ addonSuggestion: '还没点主食，建议加一份' });
      } else if (!hasDrink && self.data.cartCount >= 3) {
        self.setData({ addonSuggestion: '来一杯饮品搭配吧' });
      } else {
        self.setData({ addonSuggestion: '' });
      }
    } else {
      self.setData({ addonSuggestion: '' });
    }
  },
});
