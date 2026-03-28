// 企业团餐页
var app = getApp();
var api = require('../../../utils/api.js');

Page({
  data: {
    activeTab: 'overview',
    account: {
      balanceYuan: '0.00',
      companyName: '',
      monthSpentYuan: '0.00',
      monthCount: 0,
      monthHeadcount: 0,
      dailyQuotaYuan: '',
      todayUsedYuan: '0.00',
    },
    records: [],
    recordPage: 1,
    hasMoreRecords: false,

    // 预订团餐
    today: '',
    mealDate: '',
    mealTypes: [
      { label: '午餐', value: 'lunch' },
      { label: '晚餐', value: 'dinner' },
      { label: '茶歇', value: 'tea_break' },
    ],
    mealType: '',
    headcount: '',
    budgetOptions: [30, 50, 80, 100, 150],
    budget: '',
    mealRemark: '',
    submitting: false,
  },

  onLoad: function () {
    var now = new Date();
    var today = now.getFullYear() + '-' +
      String(now.getMonth() + 1).padStart(2, '0') + '-' +
      String(now.getDate()).padStart(2, '0');
    this.setData({ today: today });
    this.loadAccount();
  },

  switchTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    this.setData({ activeTab: tab });
    if (tab === 'overview') this.loadAccount();
    if (tab === 'records') {
      this.setData({ records: [], recordPage: 1 });
      this.loadRecords();
    }
  },

  loadAccount: function () {
    var self = this;
    api.fetchCorporateAccount()
      .then(function (d) {
        self.setData({
          account: {
            balanceYuan: ((d.balance_fen || 0) / 100).toFixed(2),
            companyName: d.company_name || '',
            monthSpentYuan: ((d.month_spent_fen || 0) / 100).toFixed(2),
            monthCount: d.month_count || 0,
            monthHeadcount: d.month_headcount || 0,
            dailyQuotaYuan: d.daily_quota_fen ? (d.daily_quota_fen / 100).toFixed(0) : '',
            todayUsedYuan: d.today_used_fen ? (d.today_used_fen / 100).toFixed(2) : '0.00',
          },
        });
      })
      .catch(function (err) {
        console.error('loadAccount failed', err);
      });
  },

  loadRecords: function () {
    var self = this;
    api.fetchCorporateRecords(self.data.recordPage)
      .then(function (data) {
        var items = (data.items || []).map(function (r) {
          return {
            id: r.id,
            description: r.description || '',
            absAmountYuan: (Math.abs(r.amount_fen || 0) / 100).toFixed(2),
            amountFen: r.amount_fen || 0,
            headcount: r.headcount || 0,
            createdAt: r.created_at ? r.created_at.slice(0, 16).replace('T', ' ') : '',
          };
        });
        self.setData({
          records: self.data.records.concat(items),
          hasMoreRecords: items.length >= 20,
        });
      })
      .catch(function (err) {
        console.error('loadRecords failed', err);
      });
  },

  loadMoreRecords: function () {
    this.setData({ recordPage: this.data.recordPage + 1 });
    this.loadRecords();
  },

  onMealDateChange: function (e) {
    this.setData({ mealDate: e.detail.value });
  },

  selectMealType: function (e) {
    this.setData({ mealType: e.currentTarget.dataset.value });
  },

  onHeadcountInput: function (e) {
    this.setData({ headcount: e.detail.value });
  },

  selectBudget: function (e) {
    this.setData({ budget: e.currentTarget.dataset.budget });
  },

  onMealRemarkInput: function (e) {
    this.setData({ mealRemark: e.detail.value });
  },

  submitMealBooking: function () {
    var self = this;
    var data = self.data;

    if (!data.mealDate) { wx.showToast({ title: '请选择日期', icon: 'none' }); return; }
    if (!data.mealType) { wx.showToast({ title: '请选择用餐类型', icon: 'none' }); return; }
    if (!data.headcount || Number(data.headcount) < 1) { wx.showToast({ title: '请输入人数', icon: 'none' }); return; }
    if (!data.budget) { wx.showToast({ title: '请选择预算', icon: 'none' }); return; }

    self.setData({ submitting: true });

    api.submitMealBooking({
      customer_id: wx.getStorageSync('tx_customer_id') || '',
      store_id: app.globalData.storeId,
      date: data.mealDate,
      meal_type: data.mealType,
      headcount: Number(data.headcount),
      budget_per_person_fen: data.budget * 100,
      remark: data.mealRemark,
    }).then(function () {
      wx.showToast({ title: '预订成功', icon: 'success' });
      self.setData({
        mealDate: '',
        mealType: '',
        headcount: '',
        budget: '',
        mealRemark: '',
        submitting: false,
      });
    }).catch(function (err) {
      console.error('submitMealBooking failed', err);
      wx.showToast({ title: err.message || '预订失败', icon: 'none' });
      self.setData({ submitting: false });
    });
  },
});
