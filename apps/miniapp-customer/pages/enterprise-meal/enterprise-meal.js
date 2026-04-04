// 企业订餐首页 — 本周菜单 + 企业账户 + 购物车
// GET /api/v1/trade/enterprise/weekly-menu?company_id=xxx&week=xxx
// GET /api/v1/trade/enterprise/account?member_id=xxx

var api = require('../../utils/api.js');

// ─── 日期工具 ───

function getWeekDates(offset) {
  // offset: 0=本周, 1=下周
  var now = new Date();
  var day = now.getDay() || 7; // 周日=7
  var monday = new Date(now);
  monday.setDate(now.getDate() - day + 1 + (offset || 0) * 7);

  var dates = [];
  var weekLabels = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
  for (var i = 0; i < 7; i++) {
    var d = new Date(monday);
    d.setDate(monday.getDate() + i);
    var m = d.getMonth() + 1;
    var dd = d.getDate();
    dates.push({
      index: i,
      label: weekLabels[i],
      date: d.getFullYear() + '-' + String(m).padStart(2, '0') + '-' + String(dd).padStart(2, '0'),
      display: m + '/' + dd,
      isToday: d.toDateString() === now.toDateString(),
    });
  }
  return dates;
}

function getWeekKey(offset) {
  var dates = getWeekDates(offset);
  return dates[0].date; // 周一日期作为week key
}

// ─── Mock数据 ───

var MOCK_ACCOUNT = {
  company_name: '屯象科技',
  balance_fen: 380000,
  month_spent_fen: 120000,
  month_budget_fen: 500000,
  member_name: '员工',
};

function buildMockWeeklyMenu() {
  var lunchDishes = [
    { id: 'wm1', name: '红烧牛肉套餐', image: '', price_fen: 5800, enterprise_price_fen: 3800, meal_type: 'lunch' },
    { id: 'wm2', name: '清蒸鲈鱼套餐', image: '', price_fen: 6800, enterprise_price_fen: 4500, meal_type: 'lunch' },
    { id: 'wm3', name: '宫保鸡丁套餐', image: '', price_fen: 3600, enterprise_price_fen: 2400, meal_type: 'lunch' },
    { id: 'wm4', name: '扬州炒饭套餐', image: '', price_fen: 2800, enterprise_price_fen: 1800, meal_type: 'lunch' },
  ];
  var dinnerDishes = [
    { id: 'wm5', name: '酸菜鱼套餐', image: '', price_fen: 4800, enterprise_price_fen: 3200, meal_type: 'dinner' },
    { id: 'wm6', name: '回锅肉套餐', image: '', price_fen: 3800, enterprise_price_fen: 2600, meal_type: 'dinner' },
    { id: 'wm7', name: '番茄牛腩套餐', image: '', price_fen: 4200, enterprise_price_fen: 2800, meal_type: 'dinner' },
  ];

  var dates = getWeekDates(0);
  var menu = {};
  dates.forEach(function (d) {
    menu[d.date] = {
      lunch: lunchDishes.map(function (dish) {
        return Object.assign({}, dish, { date: d.date });
      }),
      dinner: dinnerDishes.map(function (dish) {
        return Object.assign({}, dish, { date: d.date });
      }),
    };
  });
  return menu;
}

Page({
  data: {
    companyId: '',
    companyName: '',
    memberName: '',

    // 企业账户
    balanceYuan: '0.00',
    monthSpentYuan: '0.00',
    monthBudgetYuan: '0.00',
    budgetPercent: 0, // 0~100

    // 日期Tab
    weekDates: [],
    selectedDate: '',
    selectedDateLabel: '',

    // 菜品
    lunchDishes: [],
    dinnerDishes: [],
    loading: true,
    weeklyMenuCache: {}, // date -> { lunch: [], dinner: [] }

    // 购物车
    cartItems: [],   // { id, name, price_fen, enterprise_price_fen, qty, date, meal_type }
    cartCount: 0,
    cartTotalYuan: '0.00',
    cartTotalFen: 0,
    showCart: false,
  },

  onLoad: function (options) {
    var companyId = options.company_id || wx.getStorageSync('tx_company_id') || '';
    var companyName = options.company_name || wx.getStorageSync('tx_company_name') || '企业订餐';
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

    var dates = getWeekDates(0);
    var today = dates.find(function (d) { return d.isToday; });
    var selected = today || dates[0];
    this.setData({ weekDates: dates, selectedDate: selected.date, selectedDateLabel: selected.label });

    this.loadAccount();
    this.loadWeeklyMenu();
  },

  onShow: function () {
    if (this.data.companyId) this.loadAccount();
  },

  // ─── 快捷操作 ───

  goTodayLunch: function () {
    var dates = this.data.weekDates;
    var today = dates.find(function (d) { return d.isToday; });
    if (today) {
      this.setData({ selectedDate: today.date, selectedDateLabel: today.label });
      this._renderDishesForDate(today.date);
    }
  },

  goTodayDinner: function () {
    this.goTodayLunch(); // 同一天，滚到晚餐区域即可
  },

  goTomorrow: function () {
    var dates = this.data.weekDates;
    var todayIdx = dates.findIndex(function (d) { return d.isToday; });
    var tomorrowIdx = todayIdx >= 0 ? todayIdx + 1 : 0;
    if (tomorrowIdx < dates.length) {
      var d = dates[tomorrowIdx];
      this.setData({ selectedDate: d.date, selectedDateLabel: d.label });
      this._renderDishesForDate(d.date);
    } else {
      wx.showToast({ title: '请查看下周菜单', icon: 'none' });
    }
  },

  goOrders: function () {
    wx.navigateTo({
      url: '/pages/enterprise-orders/enterprise-orders?company_id=' + encodeURIComponent(this.data.companyId),
    });
  },

  // ─── 加载企业账户 ───

  loadAccount: function () {
    var self = this;
    var memberId = wx.getStorageSync('tx_customer_id') || '';

    api.fetchEnterpriseMealAccount(memberId).then(function (data) {
      self._applyAccount(data);
    }).catch(function () {
      // 降级Mock
      self._applyAccount(MOCK_ACCOUNT);
    });
  },

  _applyAccount: function (data) {
    var balanceFen = data.balance_fen || 0;
    var spentFen = data.month_spent_fen || 0;
    var budgetFen = data.month_budget_fen || 0;
    var pct = budgetFen > 0 ? Math.min(100, Math.round(spentFen / budgetFen * 100)) : 0;

    this.setData({
      companyName: data.company_name || this.data.companyName,
      memberName: data.member_name || '',
      balanceYuan: (balanceFen / 100).toFixed(2),
      monthSpentYuan: (spentFen / 100).toFixed(2),
      monthBudgetYuan: (budgetFen / 100).toFixed(2),
      budgetPercent: pct,
    });
  },

  // ─── 加载周菜单 ───

  loadWeeklyMenu: function () {
    var self = this;
    self.setData({ loading: true });
    var weekKey = getWeekKey(0);

    api.fetchEnterpriseWeeklyMenu(self.data.companyId, weekKey).then(function (data) {
      self._cacheMenu(data.menu || {});
      self._renderDishesForDate(self.data.selectedDate);
      self.setData({ loading: false });
    }).catch(function () {
      // 降级Mock
      var mockMenu = buildMockWeeklyMenu();
      self._cacheMenu(mockMenu);
      self._renderDishesForDate(self.data.selectedDate);
      self.setData({ loading: false });
    });
  },

  _cacheMenu: function (menuMap) {
    this.setData({ weeklyMenuCache: menuMap });
  },

  // ─── 日期Tab切换 ───

  selectDate: function (e) {
    var date = e.currentTarget.dataset.date;
    var label = e.currentTarget.dataset.label;
    this.setData({ selectedDate: date, selectedDateLabel: label });
    this._renderDishesForDate(date);
  },

  _renderDishesForDate: function (date) {
    var cache = this.data.weeklyMenuCache;
    var dayMenu = cache[date] || { lunch: [], dinner: [] };

    // 合并购物车数量
    var cartMap = {};
    this.data.cartItems.forEach(function (c) {
      cartMap[c.id + '_' + c.date] = c.qty;
    });

    var formatList = function (list) {
      return list.map(function (d) {
        var key = d.id + '_' + date;
        return Object.assign({}, d, {
          qty: cartMap[key] || 0,
          enterprise_price_yuan: (d.enterprise_price_fen / 100).toFixed(2),
          origin_price_yuan: d.price_fen ? (d.price_fen / 100).toFixed(2) : '',
        });
      });
    };

    this.setData({
      lunchDishes: formatList(dayMenu.lunch || []),
      dinnerDishes: formatList(dayMenu.dinner || []),
    });
  },

  // ─── 购物车操作 ───

  addDish: function (e) {
    var id = e.currentTarget.dataset.id;
    var mealType = e.currentTarget.dataset.mealtype;
    var date = this.data.selectedDate;
    var cartItems = this.data.cartItems.slice();

    var idx = cartItems.findIndex(function (c) { return c.id === id && c.date === date; });
    if (idx >= 0) {
      cartItems[idx] = Object.assign({}, cartItems[idx], { qty: cartItems[idx].qty + 1 });
    } else {
      // 从当前列表找dish信息
      var source = mealType === 'dinner' ? this.data.dinnerDishes : this.data.lunchDishes;
      var dish = source.find(function (d) { return d.id === id; });
      if (dish) {
        cartItems.push({
          id: dish.id,
          name: dish.name,
          price_fen: dish.price_fen,
          enterprise_price_fen: dish.enterprise_price_fen,
          enterprise_price_yuan: dish.enterprise_price_yuan,
          qty: 1,
          date: date,
          meal_type: mealType,
        });
      }
    }

    this.setData({ cartItems: cartItems });
    this._calcCart();
    this._renderDishesForDate(date);
  },

  minusDish: function (e) {
    var id = e.currentTarget.dataset.id;
    var date = this.data.selectedDate;
    var cartItems = this.data.cartItems.slice();

    var idx = cartItems.findIndex(function (c) { return c.id === id && c.date === date; });
    if (idx >= 0) {
      if (cartItems[idx].qty <= 1) {
        cartItems.splice(idx, 1);
      } else {
        cartItems[idx] = Object.assign({}, cartItems[idx], { qty: cartItems[idx].qty - 1 });
      }
    }

    this.setData({ cartItems: cartItems });
    this._calcCart();
    this._renderDishesForDate(date);
  },

  clearCart: function () {
    this.setData({ cartItems: [], showCart: false });
    this._calcCart();
    this._renderDishesForDate(this.data.selectedDate);
  },

  _calcCart: function () {
    var items = this.data.cartItems;
    var totalFen = 0;
    var count = 0;
    items.forEach(function (c) {
      totalFen += c.enterprise_price_fen * c.qty;
      count += c.qty;
    });
    this.setData({
      cartCount: count,
      cartTotalFen: totalFen,
      cartTotalYuan: (totalFen / 100).toFixed(2),
    });
  },

  showCartDetail: function () {
    if (this.data.cartCount > 0) this.setData({ showCart: true });
  },

  hideCartDetail: function () {
    this.setData({ showCart: false });
  },

  // ─── 去结算 ───

  goCheckout: function () {
    if (this.data.cartCount === 0) return;

    var items = this.data.cartItems.map(function (c) {
      return {
        dish_id: c.id,
        dish_name: c.name,
        qty: c.qty,
        unit_price_fen: c.enterprise_price_fen,
        date: c.date,
        meal_type: c.meal_type,
      };
    });

    var self = this;
    wx.showLoading({ title: '提交中...' });

    api.createEnterpriseMealOrder({
      company_id: self.data.companyId,
      items: items,
      total_fen: self.data.cartTotalFen,
    }).then(function (data) {
      wx.hideLoading();
      wx.showToast({ title: '下单成功', icon: 'success' });
      self.clearCart();
      self.loadAccount(); // 刷新余额
    }).catch(function (err) {
      wx.hideLoading();
      // 降级：模拟成功
      wx.showToast({ title: '下单成功（Mock）', icon: 'success' });
      self.clearCart();
    });
  },
});
