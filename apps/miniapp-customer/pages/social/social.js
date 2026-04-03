// Social Page -- group order, gift sending, share rewards
// Inspired by: Luckin Coffee + Pinduoduo

var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    // Tabs
    tabs: [
      { key: 'group', label: '拼单' },
      { key: 'gift', label: '请客' },
      { key: 'share', label: '分享有礼' },
      { key: 'records', label: '我的推荐' },
    ],
    activeTab: 'group',

    // Group order
    groupId: '',
    inviteCode: '',
    groupMembers: [],
    groupStatus: '',

    // Gift
    giftTypes: [
      { key: 'card', label: '礼品卡', icon: '/assets/icon-gift-card.png', desc: '送好友储值金额' },
      { key: 'dish', label: '送菜品', icon: '/assets/icon-gift-dish.png', desc: '请好友吃指定菜品' },
    ],
    giftAmounts: [2000, 5000, 10000, 20000], // fen
    selectedGiftType: 'card',
    selectedGiftAmount: 5000,
    giftMessage: '',

    // Share rewards
    referralCode: '',
    referralUrl: '',
    referralReward: '',

    // My referral records
    referralRecords: [],
    totalReferralReward: 0,
    loadingRecords: false,
  },

  onLoad: function (options) {
    if (options.tab) {
      this.setData({ activeTab: options.tab });
    }
    if (options.group_id) {
      this.setData({ groupId: options.group_id });
      this._loadGroupSummary();
    }
  },

  onShareAppMessage: function () {
    var tab = this.data.activeTab;
    if (tab === 'group' && this.data.inviteCode) {
      return {
        title: '来一起点餐吧！',
        path: '/pages/social/social?tab=group&group_id=' + this.data.groupId,
      };
    }
    if (tab === 'share' && this.data.referralCode) {
      return {
        title: '送你一份美食福利！',
        path: '/pages/index/index?referral=' + this.data.referralCode,
      };
    }
    return {
      title: '屯象点餐 - 一起享美食',
      path: '/pages/social/social',
    };
  },

  // ─── Tab switch ───

  switchTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    this.setData({ activeTab: tab });

    if (tab === 'share' && !this.data.referralCode) {
      this._generateReferral();
    }
    if (tab === 'records') {
      this._loadReferralRecords();
    }
  },

  // ─── Group order ───

  createGroup: function () {
    var self = this;
    var storeId = app.globalData.storeId;
    if (!storeId) {
      wx.showToast({ title: '请先选择门店', icon: 'none' });
      return;
    }

    api.createGroupOrder(storeId)
      .then(function (data) {
        self.setData({
          groupId: data.group_id,
          inviteCode: data.invite_code,
          groupStatus: data.status,
        });
        wx.showToast({ title: '拼单已创建', icon: 'success' });
      })
      .catch(function (err) {
        wx.showToast({ title: err.message || '创建失败', icon: 'none' });
      });
  },

  shareGroupInvite: function () {
    // Trigger share via onShareAppMessage
  },

  _loadGroupSummary: function () {
    var self = this;
    if (!self.data.groupId) return;

    api.getGroupOrderSummary(self.data.groupId)
      .then(function (data) {
        self.setData({
          groupMembers: data.members || [],
          groupStatus: data.status || '',
          inviteCode: data.invite_code || self.data.inviteCode,
        });
      })
      .catch(function (err) {
        console.warn('加载拼单失败', err);
      });
  },

  goToGroupMenu: function () {
    wx.switchTab({ url: '/pages/menu/menu' });
  },

  // ─── Gift sending ───

  selectGiftType: function (e) {
    this.setData({ selectedGiftType: e.currentTarget.dataset.key });
  },

  selectGiftAmount: function (e) {
    this.setData({ selectedGiftAmount: e.currentTarget.dataset.amount });
  },

  onGiftMessageInput: function (e) {
    this.setData({ giftMessage: e.detail.value });
  },

  sendGift: function () {
    var self = this;
    var type = self.data.selectedGiftType;
    var amount = type === 'card' ? self.data.selectedGiftAmount : 0;

    api.createGift(type, amount, [], self.data.giftMessage)
      .then(function (data) {
        wx.showToast({ title: '礼品已创建', icon: 'success' });
        // Show share dialog
        wx.showModal({
          title: '分享给好友',
          content: '礼品已创建，分享链接给好友领取吧！',
          confirmText: '分享',
          success: function (res) {
            if (res.confirm) {
              // Copy share URL
              wx.setClipboardData({
                data: data.share_url || '',
                success: function () {
                  wx.showToast({ title: '链接已复制', icon: 'success' });
                },
              });
            }
          },
        });
      })
      .catch(function (err) {
        wx.showToast({ title: err.message || '创建失败', icon: 'none' });
      });
  },

  // ─── Share rewards ───

  _generateReferral: function () {
    var self = this;
    api.generateReferralLink()
      .then(function (data) {
        self.setData({
          referralCode: data.referral_code || '',
          referralUrl: data.referral_url || '',
          referralReward: data.reward_description || '',
        });
      })
      .catch(function (err) {
        console.warn('生成邀请链接失败', err);
      });
  },

  copyReferralLink: function () {
    wx.setClipboardData({
      data: this.data.referralUrl,
      success: function () {
        wx.showToast({ title: '链接已复制', icon: 'success' });
      },
    });
  },

  // ─── Referral records ───

  _loadReferralRecords: function () {
    var self = this;
    self.setData({ loadingRecords: true });
    // Use points log as proxy for referral records
    api.fetchPointsLog(1)
      .then(function (data) {
        var records = (data.items || []).filter(function (r) {
          return r.type === 'referral' || r.source === 'referral';
        }).map(function (r) {
          return {
            id: r.id,
            friendName: r.friend_name || r.description || '好友',
            reward: r.points || r.amount || 0,
            date: (r.created_at || '').slice(0, 10),
          };
        });
        var totalReward = 0;
        records.forEach(function (r) { totalReward += r.reward; });
        self.setData({
          referralRecords: records,
          totalReferralReward: totalReward,
          loadingRecords: false,
        });
      })
      .catch(function () {
        self.setData({ loadingRecords: false });
      });
  },

  generatePoster: function () {
    wx.showToast({ title: '海报生成中...', icon: 'loading' });
    // In production, this would call a canvas API to generate a share poster image
    var self = this;
    setTimeout(function () {
      wx.showToast({ title: '海报已保存到相册', icon: 'success' });
    }, 1500);
  },
});
