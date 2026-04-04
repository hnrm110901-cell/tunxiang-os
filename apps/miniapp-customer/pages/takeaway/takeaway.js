// 外卖点餐首页
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    // 地址
    selectedAddress: null,
    estimatedTime: '',
    // 分类
    categories: [],
    activeCategoryId: '',
    // 菜品
    allDishes: [],
    filteredDishes: [],
    loading: true,
    // 购物车
    cartItems: [],
    cartCount: 0,
    cartTotalFen: 0,
    cartTotalYuan: '0.00',
    showCartPopup: false,
    // 起送
    minDeliveryFen: 2000, // 默认20元起送
    reachedMinAmount: false,
    remainMinYuan: '20.00',
    // 门店
    storeId: '',
  },

  onLoad: function (options) {
    var storeId = options.store_id || app.globalData.storeId || '';
    this.setData({ storeId: storeId });
    this._loadDefaultAddress();
    this._loadMenu(storeId);
  },

  onShow: function () {
    // 从地址选择页返回时检查
    var pages = getCurrentPages();
    var curr = pages[pages.length - 1];
    if (curr._selectedAddress) {
      this.setData({ selectedAddress: curr._selectedAddress });
      this._calcEstimatedTime();
      curr._selectedAddress = null;
    }
  },

  // ─── 地址 ───

  _loadDefaultAddress: function () {
    var self = this;
    api.txRequest('/api/v1/member/addresses', 'GET')
      .then(function (data) {
        var items = data.items || data || [];
        var def = null;
        for (var i = 0; i < items.length; i++) {
          if (items[i].is_default) { def = items[i]; break; }
        }
        if (!def && items.length > 0) def = items[0];
        if (def) {
          self.setData({ selectedAddress: def });
          self._calcEstimatedTime();
        }
      })
      .catch(function () {
        // Mock
        self.setData({
          selectedAddress: {
            id: 'mock1', name: '张三', phone: '138****8888',
            region: '湖南省长沙市岳麓区', detail: '麓谷街道中电软件园1号楼',
            tag: '公司', is_default: true,
          },
        });
        self._calcEstimatedTime();
      });
  },

  chooseAddress: function () {
    wx.navigateTo({ url: '/pages/address/address?select=1' });
  },

  _calcEstimatedTime: function () {
    var now = new Date();
    var min = now.getMinutes() + 35;
    var h = now.getHours();
    if (min >= 60) { h += 1; min -= 60; }
    if (h >= 24) h -= 24;
    var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
    this.setData({ estimatedTime: pad(h) + ':' + pad(min) });
  },

  // ─── 菜单加载 ───

  _loadMenu: function (storeId) {
    var self = this;
    self.setData({ loading: true });

    api.fetchCategories(storeId)
      .then(function (data) {
        var cats = data.items || data || [];
        // 添加推荐/热销分类
        var allCats = [
          { id: 'recommend', name: '推荐' },
          { id: 'hot', name: '热销' },
        ].concat(cats);
        self.setData({ categories: allCats, activeCategoryId: 'recommend' });
        return api.fetchDishes(storeId);
      })
      .then(function (data) {
        var dishes = (data.items || data || []).map(function (d) {
          var priceFen = d.priceFen || d.price_fen || 0;
          return {
            id: d.id,
            name: d.name || d.dish_name || '',
            description: d.description || '',
            imageUrl: d.imageUrl || d.image_url || '',
            priceFen: priceFen,
            displayPrice: (priceFen / 100).toFixed(2),
            categoryId: d.category_id || d.categoryId || '',
            monthlySales: d.monthly_sales || d.monthlySales || 0,
            quantity: 0,
            is_combo: d.is_combo || false,
          };
        });
        self.setData({
          allDishes: dishes,
          loading: false,
        });
        self._filterDishes();
      })
      .catch(function (err) {
        console.warn('外卖菜单加载失败，使用Mock', err);
        self._loadMockMenu();
      });
  },

  _loadMockMenu: function () {
    var cats = [
      { id: 'recommend', name: '推荐' },
      { id: 'hot', name: '热销' },
      { id: 'combo', name: '套餐' },
      { id: 'rice', name: '米饭' },
      { id: 'noodle', name: '面食' },
      { id: 'drink', name: '饮品' },
      { id: 'snack', name: '小食' },
    ];
    var dishes = [
      { id: 'd1', name: '招牌红烧肉套餐', description: '红烧肉+时蔬+米饭', priceFen: 3800, displayPrice: '38.00', categoryId: 'combo', monthlySales: 526, quantity: 0 },
      { id: 'd2', name: '酸菜鱼', description: '新鲜黑鱼片，酸爽开胃', priceFen: 4500, displayPrice: '45.00', categoryId: 'hot', monthlySales: 389, quantity: 0 },
      { id: 'd3', name: '麻辣香锅', description: '多种食材自选，麻辣鲜香', priceFen: 4200, displayPrice: '42.00', categoryId: 'hot', monthlySales: 312, quantity: 0 },
      { id: 'd4', name: '番茄牛腩饭', description: '慢炖牛腩配番茄汤汁', priceFen: 2800, displayPrice: '28.00', categoryId: 'rice', monthlySales: 267, quantity: 0 },
      { id: 'd5', name: '黄焖鸡米饭', description: '经典黄焖鸡，香辣入味', priceFen: 2500, displayPrice: '25.00', categoryId: 'rice', monthlySales: 445, quantity: 0 },
      { id: 'd6', name: '重庆小面', description: '麻辣鲜香，地道重庆味', priceFen: 1800, displayPrice: '18.00', categoryId: 'noodle', monthlySales: 198, quantity: 0 },
      { id: 'd7', name: '冰柠檬茶', description: '鲜榨柠檬，清爽解腻', priceFen: 800, displayPrice: '8.00', categoryId: 'drink', monthlySales: 632, quantity: 0 },
      { id: 'd8', name: '炸鸡翅(4只)', description: '外酥里嫩', priceFen: 1600, displayPrice: '16.00', categoryId: 'snack', monthlySales: 287, quantity: 0 },
    ];
    this.setData({
      categories: cats,
      activeCategoryId: 'recommend',
      allDishes: dishes,
      loading: false,
    });
    this._filterDishes();
  },

  // ─── 分类筛选 ───

  selectCategory: function (e) {
    var id = e.currentTarget.dataset.id;
    this.setData({ activeCategoryId: id });
    this._filterDishes();
  },

  _filterDishes: function () {
    var catId = this.data.activeCategoryId;
    var all = this.data.allDishes;
    var filtered;
    if (catId === 'recommend' || catId === 'hot') {
      // 推荐/热销 → 按销量排序显示全部
      filtered = all.slice().sort(function (a, b) {
        return (b.monthlySales || 0) - (a.monthlySales || 0);
      });
    } else {
      filtered = all.filter(function (d) { return d.categoryId === catId; });
    }
    this.setData({ filteredDishes: filtered });
  },

  // ─── 加减按钮 ───

  plusDish: function (e) {
    var id = e.currentTarget.dataset.id;
    this._updateQuantity(id, 1);
  },

  minusDish: function (e) {
    var id = e.currentTarget.dataset.id;
    this._updateQuantity(id, -1);
  },

  _updateQuantity: function (dishId, delta) {
    var all = this.data.allDishes;
    var cartItems = [];
    var cartCount = 0;
    var cartTotalFen = 0;

    for (var i = 0; i < all.length; i++) {
      if (all[i].id === dishId) {
        all[i].quantity = Math.max(0, (all[i].quantity || 0) + delta);
      }
      if (all[i].quantity > 0) {
        cartItems.push(all[i]);
        cartCount += all[i].quantity;
        cartTotalFen += all[i].priceFen * all[i].quantity;
      }
    }

    var minFen = this.data.minDeliveryFen;
    var reached = cartTotalFen >= minFen;
    var remainFen = reached ? 0 : (minFen - cartTotalFen);

    this.setData({
      allDishes: all,
      cartItems: cartItems,
      cartCount: cartCount,
      cartTotalFen: cartTotalFen,
      cartTotalYuan: (cartTotalFen / 100).toFixed(2),
      reachedMinAmount: reached,
      remainMinYuan: (remainFen / 100).toFixed(2),
    });
    // 重新过滤（保持数量同步）
    this._filterDishes();
  },

  // ─── 购物车弹层 ───

  toggleCartPopup: function () {
    if (this.data.cartCount === 0) return;
    this.setData({ showCartPopup: !this.data.showCartPopup });
  },

  clearCart: function () {
    var all = this.data.allDishes;
    for (var i = 0; i < all.length; i++) {
      all[i].quantity = 0;
    }
    this.setData({
      allDishes: all,
      cartItems: [],
      cartCount: 0,
      cartTotalFen: 0,
      cartTotalYuan: '0.00',
      showCartPopup: false,
      reachedMinAmount: false,
      remainMinYuan: (this.data.minDeliveryFen / 100).toFixed(2),
    });
    this._filterDishes();
  },

  // ─── 去结算 ───

  goCheckout: function () {
    if (!this.data.reachedMinAmount) {
      wx.showToast({ title: '未达起送金额', icon: 'none' });
      return;
    }
    if (!this.data.selectedAddress) {
      wx.showToast({ title: '请先选择配送地址', icon: 'none' });
      return;
    }
    // 存购物车数据到全局
    app.globalData.takeawayCart = {
      items: this.data.cartItems,
      totalFen: this.data.cartTotalFen,
      address: this.data.selectedAddress,
      storeId: this.data.storeId,
    };
    wx.navigateTo({ url: '/pages/takeaway-checkout/takeaway-checkout' });
  },

  onShareAppMessage: function () {
    return {
      title: '屯象外卖 - 美味送到家',
      path: '/pages/takeaway/takeaway',
    };
  },
});
