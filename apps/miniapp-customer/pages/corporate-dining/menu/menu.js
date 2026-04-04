// 企业专属菜单页
// GET /api/v1/trade/enterprise/{company_id}/menu  — 企业协议菜单
// GET /api/v1/trade/enterprise/{company_id}/credit — 企业账户余额
// POST /api/v1/trade/orders — 创建订单（payment_method: "enterprise_credit"）

var api = require('../../../utils/api.js');

// Mock数据（API失败时降级使用）
var MOCK_MENU = {
  categories: [
    { id: 'c1', name: '精选主食', count: 3 },
    { id: 'c2', name: '招牌菜品', count: 4 },
    { id: 'c3', name: '汤品饮品', count: 2 },
  ],
  dishes: [
    { id: 'd1', category_id: 'c1', name: '扬州炒饭', description: '蛋炒饭配时蔬', image: '', price_fen: 2800, enterprise_price_fen: 2200 },
    { id: 'd2', category_id: 'c1', name: '红烧猪蹄盖饭', description: '软糯入味，米饭任添', image: '', price_fen: 3800, enterprise_price_fen: 3000 },
    { id: 'd3', category_id: 'c1', name: '鸡肉时蔬炒饭', description: '清淡健康，低卡优选', image: '', price_fen: 2600, enterprise_price_fen: 2000 },
    { id: 'd4', category_id: 'c2', name: '红烧牛肉', description: '慢炖4小时，酥烂可口', image: '', price_fen: 5800, enterprise_price_fen: 4600 },
    { id: 'd5', category_id: 'c2', name: '清蒸鲈鱼', description: '当日新鲜，细嫩鲜甜', image: '', price_fen: 6800, enterprise_price_fen: 5400 },
    { id: 'd6', category_id: 'c2', name: '宫保鸡丁', description: '花生香脆，经典川味', image: '', price_fen: 3600, enterprise_price_fen: 2800 },
    { id: 'd7', category_id: 'c2', name: '蒜蓉炒时蔬', description: '新鲜时令蔬菜', image: '', price_fen: 1800, enterprise_price_fen: 1400 },
    { id: 'd8', category_id: 'c3', name: '例汤', description: '每日例汤，营养滋补', image: '', price_fen: 1200, enterprise_price_fen: 900 },
    { id: 'd9', category_id: 'c3', name: '无糖饮料', description: '可选绿茶/矿泉水/乌龙茶', image: '', price_fen: 800, enterprise_price_fen: 600 },
  ],
};

Page({
  data: {
    companyId: '',
    companyName: '',
    balanceYuan: '0.00',
    monthSpentYuan: '0.00',
    balanceFen: 0,
    balanceLow: false,   // 余额低于100元时提示

    loading: true,
    categories: [],
    allDishes: [],        // 全量菜品（含 qty 字段）
    currentCatId: '',
    currentCatName: '',
    filteredDishes: [],   // 当前分类菜品

    // 购物车
    cartItems: [],        // 已加入购物车的菜品（qty>0）
    cartCount: 0,
    cartTotalYuan: '0.00',
    cartTotalFen: 0,
    cartSavingYuan: '0.00',
    showCart: false,

    balanceTooLow: false, // 结算时余额不足
  },

  onLoad: function (options) {
    var companyId = options.company_id || wx.getStorageSync('tx_company_id') || '';
    var companyName = options.company_name || wx.getStorageSync('tx_company_name') || '企业用餐';
    this.setData({ companyId: companyId, companyName: companyName });

    if (!companyId) {
      wx.showModal({
        title: '未认证',
        content: '请先完成企业身份认证',
        showCancel: false,
        confirmText: '去认证',
        confirmColor: '#FF6B2C',
        success: function () {
          wx.navigateTo({ url: '/pages/corporate/verify/verify' });
        },
      });
      return;
    }

    this.loadCredit();
    this.loadMenu();
  },

  onShow: function () {
    // 每次显示时刷新余额（防止余额变化）
    if (this.data.companyId) this.loadCredit();
  },

  // ─── 加载企业余额 ───

  loadCredit: function () {
    var self = this;
    api.fetchEnterpriseCredit(self.data.companyId).then(function (data) {
      var balanceFen = data.balance_fen || 0;
      var monthSpentFen = data.month_spent_fen || 0;
      self.setData({
        balanceFen: balanceFen,
        balanceYuan: (balanceFen / 100).toFixed(2),
        monthSpentYuan: (monthSpentFen / 100).toFixed(2),
        balanceLow: balanceFen < 10000, // 余额低于100元提示
      });
      self._updateBalanceTooLow();
    }).catch(function () {
      // 降级：从storage读取
      var creditLimitFen = wx.getStorageSync('tx_credit_limit_fen') || 0;
      self.setData({
        balanceFen: creditLimitFen,
        balanceYuan: (creditLimitFen / 100).toFixed(2),
      });
    });
  },

  // ─── 加载企业菜单 ───

  loadMenu: function () {
    var self = this;
    self.setData({ loading: true });

    api.fetchEnterpriseMenu(self.data.companyId).then(function (data) {
      self._buildMenu(data.categories || [], data.dishes || []);
    }).catch(function () {
      // API失败降级Mock
      self._buildMenu(MOCK_MENU.categories, MOCK_MENU.dishes);
    });
  },

  _buildMenu: function (categories, dishes) {
    // 计算每分类菜品数
    var countMap = {};
    dishes.forEach(function (d) {
      countMap[d.category_id] = (countMap[d.category_id] || 0) + 1;
    });
    var cats = categories.map(function (c) {
      return Object.assign({}, c, { count: countMap[c.id] || 0 });
    }).filter(function (c) { return c.count > 0; });

    // 格式化价格，初始化数量
    var formatted = dishes.map(function (d) {
      return Object.assign({}, d, {
        qty: 0,
        enterprise_price_yuan: (d.enterprise_price_fen / 100).toFixed(2),
        origin_price_yuan: d.price_fen ? (d.price_fen / 100).toFixed(2) : '',
      });
    });

    var firstCat = cats.length > 0 ? cats[0] : null;
    this.setData({
      loading: false,
      categories: cats,
      allDishes: formatted,
      currentCatId: firstCat ? firstCat.id : '',
      currentCatName: firstCat ? firstCat.name : '',
    });
    this._filterDishes(firstCat ? firstCat.id : '');
  },

  // ─── 切换分类 ───

  switchCategory: function (e) {
    var id = e.currentTarget.dataset.id;
    var cats = this.data.categories;
    var cat = cats.find(function (c) { return c.id === id; });
    this.setData({
      currentCatId: id,
      currentCatName: cat ? cat.name : '',
    });
    this._filterDishes(id);
  },

  _filterDishes: function (catId) {
    var all = this.data.allDishes;
    var filtered = catId ? all.filter(function (d) { return d.category_id === catId; }) : all;
    this.setData({ filteredDishes: filtered });
  },

  // ─── 购物车操作 ───

  addDish: function (e) {
    var id = e.currentTarget.dataset.id;
    var dish = e.currentTarget.dataset.dish;
    var all = this.data.allDishes;

    // 找到现有item
    var idx = all.findIndex(function (d) { return d.id === id; });
    if (idx < 0) {
      // 从dataset取完整dish信息
      if (dish) {
        dish = Object.assign({}, dish, { qty: 1 });
        all.push(dish);
      }
    } else {
      all[idx] = Object.assign({}, all[idx], { qty: (all[idx].qty || 0) + 1 });
    }

    this.setData({ allDishes: all });
    this._syncFilteredDishes();
    this._calcCart();
  },

  minusDish: function (e) {
    var id = e.currentTarget.dataset.id;
    var all = this.data.allDishes;
    var idx = all.findIndex(function (d) { return d.id === id; });
    if (idx < 0) return;
    var newQty = Math.max(0, (all[idx].qty || 0) - 1);
    all[idx] = Object.assign({}, all[idx], { qty: newQty });
    this.setData({ allDishes: all });
    this._syncFilteredDishes();
    this._calcCart();
  },

  clearCart: function () {
    var all = this.data.allDishes.map(function (d) {
      return Object.assign({}, d, { qty: 0 });
    });
    this.setData({ allDishes: all, showCart: false });
    this._syncFilteredDishes();
    this._calcCart();
  },

  // 同步 filteredDishes 中的数量
  _syncFilteredDishes: function () {
    var all = this.data.allDishes;
    var catId = this.data.currentCatId;
    var filtered = catId ? all.filter(function (d) { return d.category_id === catId; }) : all;
    this.setData({ filteredDishes: filtered });
  },

  _calcCart: function () {
    var all = this.data.allDishes;
    var items = all.filter(function (d) { return d.qty > 0; });
    var totalFen = 0;
    var savingFen = 0;
    items.forEach(function (d) {
      totalFen += d.enterprise_price_fen * d.qty;
      if (d.price_fen) savingFen += (d.price_fen - d.enterprise_price_fen) * d.qty;
    });
    var count = items.reduce(function (s, d) { return s + d.qty; }, 0);
    this.setData({
      cartItems: items,
      cartCount: count,
      cartTotalFen: totalFen,
      cartTotalYuan: (totalFen / 100).toFixed(2),
      cartSavingYuan: (savingFen / 100).toFixed(2),
    });
    this._updateBalanceTooLow();
  },

  _updateBalanceTooLow: function () {
    var tooLow = this.data.cartTotalFen > 0 && this.data.balanceFen < this.data.cartTotalFen;
    this.setData({ balanceTooLow: tooLow });
  },

  showCartDetail: function () {
    if (this.data.cartCount > 0) this.setData({ showCart: true });
  },

  hideCartDetail: function () {
    this.setData({ showCart: false });
  },

  // ─── 去结算 ───

  goCheckout: function () {
    if (this.data.balanceTooLow) {
      wx.showToast({ title: '企业账户余额不足', icon: 'none' });
      return;
    }
    if (this.data.cartCount === 0) return;

    // 前端余额校验：订单总额 > 余额时拒绝提交
    if (this.data.cartTotalFen > this.data.balanceFen) {
      wx.showModal({
        title: '余额不足',
        content: '当前订单金额（¥' + this.data.cartTotalYuan + '）超出企业账户余额（¥' + this.data.balanceYuan + '），无法提交。',
        showCancel: false,
        confirmText: '知道了',
        confirmColor: '#FF6B2C',
      });
      return;
    }

    // 构建订单items
    var items = this.data.cartItems.map(function (d) {
      return {
        dish_id: d.id,
        dish_name: d.name,
        qty: d.qty,
        unit_price_fen: d.enterprise_price_fen,
      };
    });

    // 跳转到确认页面，传递必要信息
    var params = encodeURIComponent(JSON.stringify({
      company_id: this.data.companyId,
      company_name: this.data.companyName,
      items: items,
      total_fen: this.data.cartTotalFen,
      balance_fen: this.data.balanceFen,
    }));
    wx.navigateTo({
      url: '/pages/order/order?mode=enterprise_credit&checkout_data=' + params,
    });
  },
});
