// 在线预订页
const app = getApp();
const { txRequest } = require('../../utils/api');

Page({
  data: {
    activeTab: 'new',
    today: '',
    date: '',
    timeSlots: ['11:00-12:00', '12:00-13:00', '17:00-18:00', '18:00-19:00', '19:00-20:00'],
    selectedSlot: '',
    guests: 2,
    roomOptions: [
      { label: '不限', value: 'any' },
      { label: '大厅', value: 'hall' },
      { label: '小包间', value: 'small' },
      { label: '大包间', value: 'large' },
    ],
    selectedRoom: 'any',
    remark: '',
    submitting: false,
    bookings: [],
  },

  onLoad() {
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
    this.setData({ today });
  },

  onShow() {
    if (this.data.activeTab === 'list') {
      this.loadBookings();
    }
  },

  switchTab(e) {
    const tab = e.currentTarget.dataset.tab;
    this.setData({ activeTab: tab });
    if (tab === 'list') {
      this.loadBookings();
    }
  },

  onDateChange(e) {
    this.setData({ date: e.detail.value });
  },

  selectSlot(e) {
    this.setData({ selectedSlot: e.currentTarget.dataset.slot });
  },

  changeGuests(e) {
    const delta = Number(e.currentTarget.dataset.delta);
    const guests = Math.max(1, Math.min(30, this.data.guests + delta));
    this.setData({ guests });
  },

  selectRoom(e) {
    this.setData({ selectedRoom: e.currentTarget.dataset.room });
  },

  onRemarkInput(e) {
    this.setData({ remark: e.detail.value });
  },

  async submitBooking() {
    const { date, selectedSlot, guests, selectedRoom, remark } = this.data;
    if (!date) { wx.showToast({ title: '请选择日期', icon: 'none' }); return; }
    if (!selectedSlot) { wx.showToast({ title: '请选择时段', icon: 'none' }); return; }

    this.setData({ submitting: true });
    try {
      await txRequest('/api/v1/booking/create', 'POST', {
        store_id: app.globalData.storeId,
        customer_id: app.globalData.customerId,
        date,
        time_slot: selectedSlot,
        guests,
        room_preference: selectedRoom,
        remark,
      });
      wx.showToast({ title: '预订成功', icon: 'success' });
      this.setData({ date: '', selectedSlot: '', guests: 2, selectedRoom: 'any', remark: '', activeTab: 'list' });
      this.loadBookings();
    } catch (err) {
      console.error('submitBooking failed', err);
      wx.showToast({ title: (err && err.message) || '预订失败', icon: 'none' });
    } finally {
      this.setData({ submitting: false });
    }
  },

  async loadBookings() {
    try {
      const d = await txRequest(
        '/api/v1/booking/list?store_id=' + encodeURIComponent(app.globalData.storeId)
          + '&customer_id=' + encodeURIComponent(app.globalData.customerId),
        'GET',
      );
      const statusMap = { confirmed: '已确认', pending: '待确认', cancelled: '已取消', completed: '已完成' };
      const roomMap = { any: '不限', hall: '大厅', small: '小包间', large: '大包间' };
      const bookings = (d.items || []).map(b => ({
        ...b,
        statusText: statusMap[b.status] || b.status,
        roomLabel: roomMap[b.room_preference] || b.room_preference,
      }));
      this.setData({ bookings });
    } catch (err) {
      console.error('loadBookings failed', err);
    }
  },

  async cancelBooking(e) {
    const id = e.currentTarget.dataset.id;
    const confirmRes = await new Promise(resolve => {
      wx.showModal({ title: '提示', content: '确定取消此预订？', success: resolve });
    });
    if (!confirmRes.confirm) return;

    try {
      await txRequest('/api/v1/booking/' + encodeURIComponent(id) + '/cancel', 'POST');
      wx.showToast({ title: '已取消', icon: 'success' });
      this.loadBookings();
    } catch (err) {
      console.error('cancelBooking failed', err);
      wx.showToast({ title: '取消失败', icon: 'none' });
    }
  },
});
