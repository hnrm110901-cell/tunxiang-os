// 企业团餐页
const app = getApp();
const { txRequest } = require('../../utils/api');

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

  onLoad() {
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    this.setData({ today });
    this.loadAccount();
  },

  switchTab(e) {
    const tab = e.currentTarget.dataset.tab;
    this.setData({ activeTab: tab });
    if (tab === 'overview') this.loadAccount();
    if (tab === 'records') { this.setData({ records: [], recordPage: 1 }); this.loadRecords(); }
  },

  async loadAccount() {
    try {
      const d = await txRequest(
        '/api/v1/corporate/account?customer_id=' + encodeURIComponent(app.globalData.customerId),
        'GET',
      );
      this.setData({
        account: {
          balanceYuan: (d.balance_fen / 100).toFixed(2),
          companyName: d.company_name || '',
          monthSpentYuan: (d.month_spent_fen / 100).toFixed(2),
          monthCount: d.month_count || 0,
          monthHeadcount: d.month_headcount || 0,
          dailyQuotaYuan: d.daily_quota_fen ? (d.daily_quota_fen / 100).toFixed(0) : '',
          todayUsedYuan: d.today_used_fen ? (d.today_used_fen / 100).toFixed(2) : '0.00',
        },
      });
    } catch (err) {
      console.error('loadAccount failed', err);
    }
  },

  async loadRecords() {
    try {
      const d = await txRequest(
        '/api/v1/corporate/records?customer_id=' + encodeURIComponent(app.globalData.customerId)
          + '&page=' + this.data.recordPage + '&size=20',
        'GET',
      );
      const items = (d.items || []).map(r => ({
        ...r,
        absAmountYuan: (Math.abs(r.amount_fen) / 100).toFixed(2),
        amountFen: r.amount_fen,
        createdAt: r.created_at ? r.created_at.slice(0, 16).replace('T', ' ') : '',
      }));
      this.setData({
        records: [...this.data.records, ...items],
        hasMoreRecords: items.length >= 20,
      });
    } catch (err) {
      console.error('loadRecords failed', err);
    }
  },

  loadMoreRecords() {
    this.setData({ recordPage: this.data.recordPage + 1 });
    this.loadRecords();
  },

  onMealDateChange(e) {
    this.setData({ mealDate: e.detail.value });
  },

  selectMealType(e) {
    this.setData({ mealType: e.currentTarget.dataset.value });
  },

  onHeadcountInput(e) {
    this.setData({ headcount: e.detail.value });
  },

  selectBudget(e) {
    this.setData({ budget: e.currentTarget.dataset.budget });
  },

  onMealRemarkInput(e) {
    this.setData({ mealRemark: e.detail.value });
  },

  async submitMealBooking() {
    const { mealDate, mealType, headcount, budget, mealRemark } = this.data;
    if (!mealDate) { wx.showToast({ title: '请选择日期', icon: 'none' }); return; }
    if (!mealType) { wx.showToast({ title: '请选择用餐类型', icon: 'none' }); return; }
    if (!headcount || Number(headcount) < 1) { wx.showToast({ title: '请输入人数', icon: 'none' }); return; }
    if (!budget) { wx.showToast({ title: '请选择预算', icon: 'none' }); return; }

    this.setData({ submitting: true });
    try {
      await txRequest('/api/v1/corporate/meal-booking', 'POST', {
        customer_id: app.globalData.customerId,
        store_id: app.globalData.storeId,
        date: mealDate,
        meal_type: mealType,
        headcount: Number(headcount),
        budget_per_person_fen: budget * 100,
        remark: mealRemark,
      });
      wx.showToast({ title: '预订成功', icon: 'success' });
      this.setData({ mealDate: '', mealType: '', headcount: '', budget: '', mealRemark: '' });
    } catch (err) {
      console.error('submitMealBooking failed', err);
      wx.showToast({ title: (err && err.message) || '网络错误', icon: 'none' });
    } finally {
      this.setData({ submitting: false });
    }
  },
});
