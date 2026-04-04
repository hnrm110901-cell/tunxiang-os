// 企业挂账记录页
// GET /api/v1/trade/enterprise/orders?company_id=&month=YYYY-MM — 企业历史订单（挂账记录）

var api = require('../../../utils/api.js');

// Mock数据（API失败时降级）
function buildMockRecords(month) {
  return [
    {
      id: 'm1', order_no: 'ENT2026' + month.replace('-', '') + '001',
      summary: '红烧牛肉套餐 企业午餐',
      status: 'settled', total_fen: 4600,
      items: [
        { dish_id: 'd4', dish_name: '红烧牛肉', qty: 1 },
        { dish_id: 'd8', dish_name: '例汤', qty: 1 },
        { dish_id: 'd1', dish_name: '扬州炒饭', qty: 1 },
      ],
      created_at: month + '-08T12:30:00',
    },
    {
      id: 'm2', order_no: 'ENT2026' + month.replace('-', '') + '002',
      summary: '清蒸鲈鱼 工作餐',
      status: 'pending', total_fen: 5400,
      items: [
        { dish_id: 'd5', dish_name: '清蒸鲈鱼', qty: 1 },
        { dish_id: 'd7', dish_name: '蒜蓉炒时蔬', qty: 1 },
      ],
      created_at: month + '-15T11:45:00',
    },
    {
      id: 'm3', order_no: 'ENT2026' + month.replace('-', '') + '003',
      summary: '部门聚餐',
      status: 'pending', total_fen: 12800,
      items: [
        { dish_id: 'd4', dish_name: '红烧牛肉', qty: 2 },
        { dish_id: 'd6', dish_name: '宫保鸡丁', qty: 2 },
        { dish_id: 'd8', dish_name: '例汤', qty: 2 },
      ],
      created_at: month + '-20T18:20:00',
    },
  ];
}

Page({
  data: {
    companyId: '',

    // 月份选择
    currentMonth: '',       // YYYY-MM
    currentMonthDisplay: '',// 2026年04月
    isCurrentMonth: true,

    // 月度汇总
    summary: {
      totalYuan: '0.00',
      settledYuan: '0.00',
      pendingYuan: '0.00',
      count: 0,
      settledCount: 0,
    },

    // 记录列表
    records: [],
    page: 1,
    hasMore: false,
    loading: false,
  },

  onLoad: function (options) {
    var companyId = options.company_id || wx.getStorageSync('tx_company_id') || '';
    this.setData({ companyId: companyId });

    var now = new Date();
    var month = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');
    this._setMonth(month);
    this.loadRecords(true);
  },

  onPullDownRefresh: function () {
    this.loadRecords(true);
    wx.stopPullDownRefresh();
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
    var val = e.detail.value; // YYYY-MM
    this._setMonth(val);
    this.loadRecords(true);
  },

  prevMonth: function () {
    var parts = this.data.currentMonth.split('-');
    var y = Number(parts[0]);
    var m = Number(parts[1]) - 1;
    if (m < 1) { m = 12; y -= 1; }
    this._setMonth(y + '-' + String(m).padStart(2, '0'));
    this.loadRecords(true);
  },

  nextMonth: function () {
    if (this.data.isCurrentMonth) return;
    var parts = this.data.currentMonth.split('-');
    var y = Number(parts[0]);
    var m = Number(parts[1]) + 1;
    if (m > 12) { m = 1; y += 1; }
    this._setMonth(y + '-' + String(m).padStart(2, '0'));
    this.loadRecords(true);
  },

  // ─── 加载记录 ───

  loadRecords: function (reset) {
    var self = this;
    var page = reset ? 1 : self.data.page;
    if (reset) self.setData({ records: [], page: 1, hasMore: false });
    self.setData({ loading: true });

    api.fetchEnterpriseOrders(self.data.companyId, {
      month: self.data.currentMonth,
      page: page,
      size: 20,
    }).then(function (data) {
      self._applyRecords(data.items || [], data.total || 0, data.summary || {}, page, reset);
    }).catch(function () {
      // 降级Mock
      var mockItems = buildMockRecords(self.data.currentMonth);
      self._applyRecords(mockItems, mockItems.length, null, page, reset);
    });
  },

  _applyRecords: function (items, total, summaryData, page, reset) {
    var formatted = items.map(function (r) {
      var dt = r.created_at ? r.created_at.slice(0, 16).replace('T', ' ') : '';
      return Object.assign({}, r, {
        amountYuan: ((r.total_fen || 0) / 100).toFixed(2),
        dateDisplay: dt,
        items: r.items || [],
      });
    });

    var existing = reset ? [] : this.data.records;
    var all = existing.concat(formatted);

    // 计算汇总（若API未返回summary则前端算）
    var summary;
    if (summaryData && summaryData.total_fen !== undefined) {
      summary = {
        totalYuan: (summaryData.total_fen / 100).toFixed(2),
        settledYuan: (summaryData.settled_fen / 100).toFixed(2),
        pendingYuan: (summaryData.pending_fen / 100).toFixed(2),
        count: summaryData.count || all.length,
        settledCount: summaryData.settled_count || 0,
      };
    } else {
      var totalFen = 0, settledFen = 0, pendingFen = 0, settledCount = 0;
      all.forEach(function (r) {
        totalFen += r.total_fen || 0;
        if (r.status === 'settled') { settledFen += r.total_fen || 0; settledCount++; }
        else pendingFen += r.total_fen || 0;
      });
      summary = {
        totalYuan: (totalFen / 100).toFixed(2),
        settledYuan: (settledFen / 100).toFixed(2),
        pendingYuan: (pendingFen / 100).toFixed(2),
        count: all.length,
        settledCount: settledCount,
      };
    }

    this.setData({
      records: all,
      page: page + 1,
      hasMore: all.length < total && items.length >= 20,
      loading: false,
      summary: summary,
    });
  },

  loadMore: function () {
    if (!this.data.hasMore || this.data.loading) return;
    this.loadRecords(false);
  },

  // ─── 导出账单 ───

  exportRecords: function () {
    var self = this;
    if (self.data.records.length === 0) {
      wx.showToast({ title: '本月暂无记录', icon: 'none' });
      return;
    }

    // 生成账单文本摘要用于分享
    var text = self.data.currentMonthDisplay + ' 企业挂账账单\n';
    text += '总计：¥' + self.data.summary.totalYuan + '\n';
    text += '已结算：¥' + self.data.summary.settledYuan + '\n';
    text += '待结算：¥' + self.data.summary.pendingYuan + '\n\n';
    self.data.records.forEach(function (r, i) {
      text += (i + 1) + '. ' + r.dateDisplay + ' ' + (r.summary || '企业用餐') + ' ¥' + r.amountYuan + ' [' + (r.status === 'settled' ? '已结算' : '待结算') + ']\n';
    });

    wx.showActionSheet({
      itemList: ['转发给同事', '截图保存'],
      success: function (res) {
        if (res.tapIndex === 0) {
          // 触发分享
          wx.showShareMenu({ withShareTicket: false });
          wx.showToast({ title: '请点击右上角分享', icon: 'none' });
        } else {
          // 截图提示
          wx.showToast({ title: '请截屏保存', icon: 'none' });
        }
      },
    });
  },

  onShareAppMessage: function () {
    return {
      title: this.data.currentMonthDisplay + ' 企业挂账账单 共' + this.data.summary.count + '笔',
      path: '/pages/corporate-dining/records/records?company_id=' + encodeURIComponent(this.data.companyId),
    };
  },
});
