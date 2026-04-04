// 企业订餐历史 — 月度汇总 + 按日分组列表
// GET /api/v1/trade/enterprise/orders?company_id=&month=&page=&size=

var api = require('../../utils/api.js');

// Mock数据
function buildMockOrders(month) {
  return {
    summary: {
      order_count: 18,
      month_spent_fen: 68400,
      month_budget_fen: 500000,
    },
    items: [
      {
        id: 'eo1', date: month + '-28', meal_type: 'lunch',
        dishes: [{ name: '红烧牛肉套餐', qty: 1 }],
        total_fen: 3800, status: 'delivered', delivery_status: '已送达',
        created_at: month + '-28T12:05:00',
      },
      {
        id: 'eo2', date: month + '-27', meal_type: 'lunch',
        dishes: [{ name: '宫保鸡丁套餐', qty: 1 }, { name: '例汤', qty: 1 }],
        total_fen: 3300, status: 'delivered', delivery_status: '已送达',
        created_at: month + '-27T11:50:00',
      },
      {
        id: 'eo3', date: month + '-27', meal_type: 'dinner',
        dishes: [{ name: '酸菜鱼套餐', qty: 1 }],
        total_fen: 3200, status: 'delivered', delivery_status: '已送达',
        created_at: month + '-27T17:30:00',
      },
      {
        id: 'eo4', date: month + '-26', meal_type: 'lunch',
        dishes: [{ name: '扬州炒饭套餐', qty: 2 }],
        total_fen: 3600, status: 'preparing', delivery_status: '制作中',
        created_at: month + '-26T12:10:00',
      },
      {
        id: 'eo5', date: month + '-25', meal_type: 'lunch',
        dishes: [{ name: '清蒸鲈鱼套餐', qty: 1 }],
        total_fen: 4500, status: 'delivered', delivery_status: '已送达',
        created_at: month + '-25T12:00:00',
      },
    ],
    total: 5,
  };
}

Page({
  data: {
    companyId: '',

    // 月份
    currentMonth: '',
    currentMonthDisplay: '',
    isCurrentMonth: true,

    // 月度汇总
    orderCount: 0,
    monthSpentYuan: '0.00',
    remainingYuan: '0.00',
    monthBudgetYuan: '0.00',

    // 按日分组的订单列表
    groupedOrders: [], // [{ date: '2026-04-02', dateDisplay: '4月2日 周三', orders: [...] }]
    page: 1,
    hasMore: false,
    loading: false,
    allOrders: [],
  },

  onLoad: function (options) {
    var companyId = options.company_id || wx.getStorageSync('tx_company_id') || '';
    this.setData({ companyId: companyId });

    var now = new Date();
    var month = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');
    this._setMonth(month);
    this.loadOrders(true);
  },

  onPullDownRefresh: function () {
    this.loadOrders(true);
    wx.stopPullDownRefresh();
  },

  onReachBottom: function () {
    if (this.data.hasMore && !this.data.loading) {
      this.loadOrders(false);
    }
  },

  // ─── 月份工具 ───

  _setMonth: function (monthStr) {
    var now = new Date();
    var nowStr = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');
    var parts = monthStr.split('-');
    var display = parts[0] + '年' + String(Number(parts[1])).padStart(2, '0') + '月';
    this.setData({
      currentMonth: monthStr,
      currentMonthDisplay: display,
      isCurrentMonth: monthStr === nowStr,
    });
  },

  onMonthChange: function (e) {
    this._setMonth(e.detail.value);
    this.loadOrders(true);
  },

  prevMonth: function () {
    var parts = this.data.currentMonth.split('-');
    var y = Number(parts[0]);
    var m = Number(parts[1]) - 1;
    if (m < 1) { m = 12; y -= 1; }
    this._setMonth(y + '-' + String(m).padStart(2, '0'));
    this.loadOrders(true);
  },

  nextMonth: function () {
    if (this.data.isCurrentMonth) return;
    var parts = this.data.currentMonth.split('-');
    var y = Number(parts[0]);
    var m = Number(parts[1]) + 1;
    if (m > 12) { m = 1; y += 1; }
    this._setMonth(y + '-' + String(m).padStart(2, '0'));
    this.loadOrders(true);
  },

  // ─── 加载订单 ───

  loadOrders: function (reset) {
    var self = this;
    var page = reset ? 1 : self.data.page;
    if (reset) {
      self.setData({ allOrders: [], groupedOrders: [], page: 1, hasMore: false });
    }
    self.setData({ loading: true });

    api.fetchEnterpriseOrders(self.data.companyId, {
      month: self.data.currentMonth,
      page: page,
      size: 20,
    }).then(function (data) {
      self._applyOrders(data, page, reset);
    }).catch(function () {
      // 降级Mock
      var mock = buildMockOrders(self.data.currentMonth);
      self._applyOrders(mock, page, reset);
    });
  },

  _applyOrders: function (data, page, reset) {
    var items = (data.items || []).map(function (o) {
      var dishText = (o.dishes || []).map(function (d) {
        return d.name + (d.qty > 1 ? ' x' + d.qty : '');
      }).join('、');
      return Object.assign({}, o, {
        amountYuan: ((o.total_fen || 0) / 100).toFixed(2),
        dishText: dishText || '企业用餐',
        mealLabel: o.meal_type === 'dinner' ? '晚餐' : '午餐',
        timeDisplay: o.created_at ? o.created_at.slice(11, 16) : '',
      });
    });

    var existing = reset ? [] : this.data.allOrders;
    var allOrders = existing.concat(items);

    // 按日分组
    var grouped = this._groupByDate(allOrders);

    // 汇总
    var summary = data.summary || {};
    var spentFen = summary.month_spent_fen || 0;
    var budgetFen = summary.month_budget_fen || 0;
    var remainFen = Math.max(0, budgetFen - spentFen);

    this.setData({
      allOrders: allOrders,
      groupedOrders: grouped,
      orderCount: summary.order_count || allOrders.length,
      monthSpentYuan: (spentFen / 100).toFixed(2),
      monthBudgetYuan: (budgetFen / 100).toFixed(2),
      remainingYuan: (remainFen / 100).toFixed(2),
      page: page + 1,
      hasMore: allOrders.length < (data.total || 0) && items.length >= 20,
      loading: false,
    });
  },

  _groupByDate: function (orders) {
    var weekLabels = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
    var map = {};
    var keys = [];

    orders.forEach(function (o) {
      var date = o.date || (o.created_at ? o.created_at.slice(0, 10) : '未知');
      if (!map[date]) {
        map[date] = [];
        keys.push(date);
      }
      map[date].push(o);
    });

    // 按日期倒序
    keys.sort(function (a, b) { return b.localeCompare(a); });

    return keys.map(function (date) {
      var d = new Date(date);
      var m = d.getMonth() + 1;
      var dd = d.getDate();
      var wk = weekLabels[d.getDay()];
      return {
        date: date,
        dateDisplay: m + '月' + dd + '日 ' + wk,
        orders: map[date],
      };
    });
  },
});
