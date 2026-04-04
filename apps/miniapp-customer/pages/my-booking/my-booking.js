// 我的预约页 — 即将到来/已完成/已取消 三Tab + 卡片列表 + 下拉刷新
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    tabs: [
      { key: 'upcoming', label: '即将到来' },
      { key: 'completed', label: '已完成' },
      { key: 'cancelled', label: '已取消' },
    ],
    activeTab: 'upcoming',
    bookings: [],
    loading: false,
  },

  onLoad: function () {
    this.loadBookings();
  },

  onShow: function () {
    this.loadBookings();
  },

  onPullDownRefresh: function () {
    var self = this;
    self.loadBookings().then(function () {
      wx.stopPullDownRefresh();
    }).catch(function () {
      wx.stopPullDownRefresh();
    });
  },

  switchTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    this.setData({ activeTab: tab });
    this.loadBookings();
  },

  loadBookings: function () {
    var self = this;
    self.setData({ loading: true });

    return api.fetchBookings()
      .then(function (data) {
        var statusMap = {
          confirmed: '已确认',
          pending: '待确认',
          cancelled: '已取消',
          completed: '已完成',
          no_show: '未到店',
        };
        var roomMap = {
          any: '不限',
          hall: '普通大厅',
          small: '小包厢',
          large: '大包厢',
        };

        var all = (data.items || []).map(function (b) {
          return {
            id: b.id,
            storeName: b.store_name || '门店',
            date: b.date,
            timeSlot: b.time_slot,
            guests: b.guests,
            status: b.status,
            statusText: statusMap[b.status] || b.status,
            roomLabel: roomMap[b.room_preference] || b.room_preference || '',
            remark: b.remark || '',
          };
        });

        // 按Tab过滤
        var tab = self.data.activeTab;
        var filtered = [];
        if (tab === 'upcoming') {
          filtered = all.filter(function (b) {
            return b.status === 'confirmed' || b.status === 'pending';
          });
        } else if (tab === 'completed') {
          filtered = all.filter(function (b) {
            return b.status === 'completed';
          });
        } else {
          filtered = all.filter(function (b) {
            return b.status === 'cancelled' || b.status === 'no_show';
          });
        }

        self.setData({ bookings: filtered, loading: false });
      })
      .catch(function (err) {
        console.error('loadBookings failed', err);
        self.setData({ loading: false });
        // 降级Mock数据
        self._useMockBookings();
      });
  },

  _useMockBookings: function () {
    var tab = this.data.activeTab;
    var mock = [];
    if (tab === 'upcoming') {
      mock = [
        { id: 'mock-1', storeName: '屯象旗舰店', date: '2026-04-05', timeSlot: '18:00', guests: 4, status: 'confirmed', statusText: '已确认', roomLabel: '普通大厅', remark: '' },
        { id: 'mock-2', storeName: '屯象CBD店', date: '2026-04-08', timeSlot: '12:00', guests: 2, status: 'pending', statusText: '待确认', roomLabel: '小包厢', remark: '生日聚会' },
      ];
    } else if (tab === 'completed') {
      mock = [
        { id: 'mock-3', storeName: '屯象旗舰店', date: '2026-03-28', timeSlot: '19:00', guests: 6, status: 'completed', statusText: '已完成', roomLabel: '大包厢', remark: '' },
      ];
    }
    this.setData({ bookings: mock });
  },

  cancelBooking: function (e) {
    var self = this;
    var id = e.currentTarget.dataset.id;

    wx.showModal({
      title: '取消预约',
      content: '确定要取消这个预约吗？',
      confirmColor: '#FF6B35',
      success: function (res) {
        if (!res.confirm) return;

        api.cancelBooking(id)
          .then(function () {
            wx.showToast({ title: '已取消', icon: 'success' });
            self.loadBookings();
          })
          .catch(function (err) {
            wx.showToast({ title: err.message || '取消失败', icon: 'none' });
          });
      },
    });
  },
});
