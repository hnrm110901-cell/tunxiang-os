// 排队取号页
const app = getApp();

Page({
  data: {
    guestOptions: [
      { label: '1-2人', value: '1-2' },
      { label: '3-4人', value: '3-4' },
      { label: '5-6人', value: '5-6' },
      { label: '7人以上', value: '7+' },
    ],
    selectedGuests: '',
    queueSummary: [],
    queueTicket: null,
    submitting: false,
    pollTimer: null,
  },

  onLoad() {
    this.loadQueueSummary();
    this.checkExistingTicket();
  },

  onUnload() {
    if (this.data.pollTimer) {
      clearInterval(this.data.pollTimer);
    }
  },

  selectGuests(e) {
    this.setData({ selectedGuests: e.currentTarget.dataset.value });
  },

  async loadQueueSummary() {
    try {
      const res = await wx.request({
        url: `${app.globalData.apiBase}/api/v1/queue/summary`,
        data: { store_id: app.globalData.storeId },
        header: { 'X-Tenant-ID': app.globalData.tenantId },
      });
      if (res.data.ok) {
        this.setData({ queueSummary: res.data.data.items || [] });
      }
    } catch (err) {
      console.error('loadQueueSummary failed', err);
    }
  },

  async checkExistingTicket() {
    try {
      const res = await wx.request({
        url: `${app.globalData.apiBase}/api/v1/queue/my-ticket`,
        data: {
          store_id: app.globalData.storeId,
          customer_id: app.globalData.customerId,
        },
        header: { 'X-Tenant-ID': app.globalData.tenantId },
      });
      if (res.data.ok && res.data.data) {
        this.setData({ queueTicket: res.data.data });
        this.startPolling();
      }
    } catch (err) {
      console.error('checkExistingTicket failed', err);
    }
  },

  async takeNumber() {
    if (!this.data.selectedGuests) {
      wx.showToast({ title: '请选择用餐人数', icon: 'none' });
      return;
    }
    this.setData({ submitting: true });
    try {
      const res = await wx.request({
        url: `${app.globalData.apiBase}/api/v1/queue/take`,
        method: 'POST',
        header: { 'X-Tenant-ID': app.globalData.tenantId },
        data: {
          store_id: app.globalData.storeId,
          customer_id: app.globalData.customerId,
          guest_range: this.data.selectedGuests,
        },
      });
      if (res.data.ok) {
        wx.showToast({ title: '取号成功', icon: 'success' });
        this.setData({ queueTicket: res.data.data });
        this.startPolling();
      } else {
        wx.showToast({ title: res.data.error?.message || '取号失败', icon: 'none' });
      }
    } catch (err) {
      console.error('takeNumber failed', err);
      wx.showToast({ title: '网络错误', icon: 'none' });
    } finally {
      this.setData({ submitting: false });
    }
  },

  startPolling() {
    if (this.data.pollTimer) clearInterval(this.data.pollTimer);
    const timer = setInterval(() => {
      this.refreshTicketStatus();
    }, 15000);
    this.setData({ pollTimer: timer });
  },

  async refreshTicketStatus() {
    try {
      const res = await wx.request({
        url: `${app.globalData.apiBase}/api/v1/queue/my-ticket`,
        data: {
          store_id: app.globalData.storeId,
          customer_id: app.globalData.customerId,
        },
        header: { 'X-Tenant-ID': app.globalData.tenantId },
      });
      if (res.data.ok && res.data.data) {
        const ticket = res.data.data;
        this.setData({ queueTicket: ticket });
        if (ticket.status === 'called') {
          wx.showModal({
            title: '叫号通知',
            content: `您的号码 ${ticket.ticketNo} 已到，请前往就座！`,
            showCancel: false,
          });
          clearInterval(this.data.pollTimer);
        }
      } else {
        this.setData({ queueTicket: null });
        clearInterval(this.data.pollTimer);
      }
    } catch (err) {
      console.error('refreshTicketStatus failed', err);
    }
  },

  async cancelQueue() {
    const confirmRes = await new Promise(resolve => {
      wx.showModal({ title: '提示', content: '确定取消排队？', success: resolve });
    });
    if (!confirmRes.confirm) return;

    try {
      const ticket = this.data.queueTicket;
      const res = await wx.request({
        url: `${app.globalData.apiBase}/api/v1/queue/${ticket.id}/cancel`,
        method: 'POST',
        header: { 'X-Tenant-ID': app.globalData.tenantId },
      });
      if (res.data.ok) {
        wx.showToast({ title: '已取消', icon: 'success' });
        clearInterval(this.data.pollTimer);
        this.setData({ queueTicket: null, pollTimer: null });
        this.loadQueueSummary();
      }
    } catch (err) {
      console.error('cancelQueue failed', err);
      wx.showToast({ title: '取消失败', icon: 'none' });
    }
  },
});
