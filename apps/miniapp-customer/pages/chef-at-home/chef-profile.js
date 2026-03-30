// 厨师详情 — 擅长菜系/评价/作品集
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    chefId: '',
    chef: null,
    loading: true,
    activeTab: 'intro', // intro / portfolio / ratings
  },

  onLoad: function (options) {
    if (options.chef_id) {
      this.setData({ chefId: options.chef_id });
      this.loadChefProfile(options.chef_id);
    }
  },

  onShareAppMessage: function () {
    var chef = this.data.chef;
    var title = chef ? chef.name + ' · 徐记海鲜大厨到家' : '徐记海鲜大厨到家';
    return { title: title, path: '/pages/chef-at-home/chef-profile?chef_id=' + this.data.chefId };
  },

  loadChefProfile: function (chefId) {
    var self = this;
    self.setData({ loading: true });

    api.txRequest('/api/v1/chef-at-home/chefs/' + chefId)
      .then(function (data) {
        self.setData({ chef: data, loading: false });
      })
      .catch(function (err) {
        console.error('loadChefProfile failed', err);
        wx.showToast({ title: '加载失败', icon: 'none' });
        self.setData({ loading: false });
      });
  },

  switchTab: function (e) {
    this.setData({ activeTab: e.currentTarget.dataset.tab });
  },

  selectThisChef: function () {
    var self = this;
    var chef = self.data.chef;
    if (!chef) return;

    // 把厨师信息写入缓存，返回首页时使用
    var draft = wx.getStorageSync('chef_at_home_draft') || {};
    draft.chef_id = chef.id;
    draft.chef_name = chef.name;
    draft.chef_title = chef.title;
    wx.setStorageSync('chef_at_home_draft', draft);

    wx.navigateBack();
  },

  previewImage: function (e) {
    var url = e.currentTarget.dataset.url;
    var urls = (this.data.chef && this.data.chef.portfolio) ? this.data.chef.portfolio.map(function (p) { return p.image; }) : [];
    wx.previewImage({ current: url, urls: urls });
  },

  _formatRatingStars: function (rating) {
    var stars = '';
    for (var i = 0; i < 5; i++) {
      stars += i < rating ? '★' : '☆';
    }
    return stars;
  },
});
