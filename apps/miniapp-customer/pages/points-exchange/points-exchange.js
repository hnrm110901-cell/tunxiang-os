// 我的兑换记录
var api = require('../../utils/api.js');

var STATUS_MAP = {
  pending: '待使用',
  used: '已使用',
  expired: '已过期',
};

// Mock兑换记录
var MOCK_RECORDS = {
  pending: [
    {
      id: 'r-1', name: '满50减10优惠券', pointsCost: 200,
      redeemTime: '2026-03-28 14:30', status: 'pending', statusText: '待使用',
      verifyCode: 'TX20260328001', expireTime: '2026-04-28',
      imageUrl: '',
    },
    {
      id: 'r-2', name: '9折全场折扣券', pointsCost: 300,
      redeemTime: '2026-03-25 10:15', status: 'pending', statusText: '待使用',
      verifyCode: 'TX20260325002', expireTime: '2026-04-25',
      imageUrl: '',
    },
  ],
  used: [
    {
      id: 'r-3', name: '免配送费券', pointsCost: 150,
      redeemTime: '2026-03-20 09:00', status: 'used', statusText: '已使用',
      verifyCode: 'TX20260320003', expireTime: '2026-04-20',
      imageUrl: '',
    },
  ],
  expired: [
    {
      id: 'r-4', name: '招牌红烧肉兑换券', pointsCost: 500,
      redeemTime: '2026-02-10 16:20', status: 'expired', statusText: '已过期',
      verifyCode: 'TX20260210004', expireTime: '2026-03-10',
      imageUrl: '',
    },
  ],
};

Page({
  data: {
    activeTab: 'pending',
    records: [],
    loading: false,
    page: 1,
    hasMore: false,
    // 核销码弹窗
    showCode: false,
    codeRecord: {},
  },

  onLoad: function () {
    this._loadRecords();
  },

  onPullDownRefresh: function () {
    var self = this;
    self.setData({ page: 1, records: [] });
    self._loadRecords().then(function () {
      wx.stopPullDownRefresh();
    }).catch(function () {
      wx.stopPullDownRefresh();
    });
  },

  onReachBottom: function () {
    if (this.data.hasMore && !this.data.loading) {
      this.setData({ page: this.data.page + 1 });
      this._loadRecords();
    }
  },

  // ─── Tab切换 ───

  switchTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    if (tab === this.data.activeTab) return;
    this.setData({ activeTab: tab, page: 1, records: [] });
    this._loadRecords();
  },

  // ─── 数据加载 ───

  _loadRecords: function () {
    var self = this;
    self.setData({ loading: true });

    return api.fetchMyRedemptions(self.data.page)
      .then(function (data) {
        var allItems = (data.items || []).map(function (r) {
          var status = r.status || 'pending';
          return {
            id: r.redemption_id || r.id,
            name: r.item_name || r.name || '',
            pointsCost: r.points_cost || 0,
            redeemTime: (r.redeemed_at || r.created_at || '').slice(0, 16).replace('T', ' '),
            status: status,
            statusText: STATUS_MAP[status] || status,
            verifyCode: r.verify_code || r.code || '',
            expireTime: (r.expire_at || '').slice(0, 10),
            imageUrl: r.image_url || '',
          };
        });
        // 按当前Tab过滤
        var filtered = allItems.filter(function (item) {
          return item.status === self.data.activeTab;
        });
        if (filtered.length === 0 && allItems.length === 0 && self.data.page === 1) {
          // 降级Mock
          filtered = MOCK_RECORDS[self.data.activeTab] || [];
        }
        var merged = self.data.page > 1 ? self.data.records.concat(filtered) : filtered;
        self.setData({
          records: merged,
          hasMore: allItems.length >= 20,
          loading: false,
        });
      })
      .catch(function () {
        // 降级Mock
        var mockItems = MOCK_RECORDS[self.data.activeTab] || [];
        self.setData({
          records: mockItems,
          hasMore: false,
          loading: false,
        });
      });
  },

  // ─── 核销码 ───

  showCodePopup: function (e) {
    var record = e.currentTarget.dataset.record;
    this.setData({ showCode: true, codeRecord: record });
    this._drawQR(record.verifyCode || '');
  },

  closeCodePopup: function () {
    this.setData({ showCode: false });
  },

  _drawQR: function (code) {
    // 简化版：用Canvas画一个"模拟二维码"占位
    // 实际项目可接入 weapp-qrcode 等库
    var ctx = wx.createCanvasContext('qrCanvas', this);
    var size = 200;
    ctx.setFillStyle('#FFFFFF');
    ctx.fillRect(0, 0, size, size);

    // 画网格模拟QR码
    ctx.setFillStyle('#000000');
    var cellSize = 8;
    var codeHash = 0;
    for (var i = 0; i < code.length; i++) {
      codeHash = ((codeHash << 5) - codeHash + code.charCodeAt(i)) | 0;
    }
    var seed = Math.abs(codeHash);
    for (var row = 2; row < 23; row++) {
      for (var col = 2; col < 23; col++) {
        seed = (seed * 1103515245 + 12345) & 0x7fffffff;
        if (seed % 3 !== 0) {
          ctx.fillRect(col * cellSize, row * cellSize, cellSize - 1, cellSize - 1);
        }
      }
    }
    // 三个定位点
    var positions = [[2, 2], [2, 17], [17, 2]];
    for (var p = 0; p < positions.length; p++) {
      var px = positions[p][0] * cellSize;
      var py = positions[p][1] * cellSize;
      ctx.setFillStyle('#000000');
      ctx.fillRect(px, py, cellSize * 5, cellSize * 5);
      ctx.setFillStyle('#FFFFFF');
      ctx.fillRect(px + cellSize, py + cellSize, cellSize * 3, cellSize * 3);
      ctx.setFillStyle('#000000');
      ctx.fillRect(px + cellSize * 2, py + cellSize * 2, cellSize, cellSize);
    }

    ctx.draw();
  },

  copyCode: function () {
    var code = this.data.codeRecord.verifyCode || '';
    if (!code) return;
    wx.setClipboardData({
      data: code,
      success: function () {
        wx.showToast({ title: '已复制', icon: 'success' });
      },
    });
  },

  // ─── 导航 ───

  goMall: function () {
    wx.navigateBack({ delta: 1 });
  },
});
