// 大厨到家首页 — 地址/搜索 + 日期筛选 + 菜系筛选 + 厨师列表
var api = require('../../utils/api.js');

Page({
  data: {
    // 服务地址
    serviceAddress: '',

    // 日期筛选（展示最近7天）
    dateList: [],
    selectedDate: '',

    // 菜系筛选
    cuisineTypes: ['全部', '湘菜', '粤菜', '海鲜', '川菜', '淮扬菜', '家常菜'],
    selectedCuisine: '全部',

    // 厨师列表
    chefs: [],
    loadingChefs: false,
    loadError: false,
  },

  onLoad: function () {
    this._buildDateList();
    this._loadSavedAddress();
  },

  onShow: function () {
    // 如果从chef-profile返回时地址可能更新
    var saved = wx.getStorageSync('chef_service_address');
    if (saved) {
      this.setData({ serviceAddress: saved });
    }
    this.loadChefs();
  },

  onShareAppMessage: function () {
    return { title: '专业大厨，到家烹制 — 大厨到家', path: '/pages/chef-at-home/index' };
  },

  onShareTimeline: function () {
    return { title: '大厨到家 — 专业大厨上门烹制' };
  },

  // ─── 构建7天日期列表 ───

  _buildDateList: function () {
    var weekdays = ['日', '一', '二', '三', '四', '五', '六'];
    var list = [];
    var now = new Date();

    for (var i = 0; i < 7; i++) {
      var d = new Date(now.getTime() + i * 86400000);
      var value = d.getFullYear() + '-' +
        String(d.getMonth() + 1).padStart(2, '0') + '-' +
        String(d.getDate()).padStart(2, '0');
      list.push({
        value: value,
        weekday: '周' + weekdays[d.getDay()],
        day: String(d.getDate()),
        month: String(d.getMonth() + 1),
        isToday: i === 0,
      });
    }

    // 默认选明天（最早可预约）
    var defaultDate = list.length > 1 ? list[1].value : list[0].value;
    this.setData({ dateList: list, selectedDate: defaultDate });
  },

  _loadSavedAddress: function () {
    var saved = wx.getStorageSync('chef_service_address');
    if (saved) {
      this.setData({ serviceAddress: saved });
    }
  },

  // ─── 选择服务地址 ───

  chooseServiceAddress: function () {
    var self = this;
    wx.chooseLocation({
      success: function (res) {
        var addr = (res.address || '') + (res.name ? ' ' + res.name : '');
        self.setData({ serviceAddress: addr });
        wx.setStorageSync('chef_service_address', addr);
        self.loadChefs();
      },
      fail: function () {
        // 允许手动输入
      },
    });
  },

  // ─── 日期切换 ───

  selectDate: function (e) {
    var value = e.currentTarget.dataset.value;
    this.setData({ selectedDate: value });
    this.loadChefs();
  },

  // ─── 菜系切换 ───

  selectCuisine: function (e) {
    var type = e.currentTarget.dataset.type;
    this.setData({ selectedCuisine: type });
    this.loadChefs();
  },

  // ─── 加载厨师列表 ───

  loadChefs: function () {
    var self = this;
    var date = self.data.selectedDate;
    var cuisineParam = self.data.selectedCuisine === '全部' ? '' : self.data.selectedCuisine;
    var area = '长沙';

    self.setData({ loadingChefs: true, loadError: false });

    var url = '/api/v1/chef-at-home/chefs?date=' + encodeURIComponent(date) +
      '&area=' + encodeURIComponent(area);
    if (cuisineParam) {
      url += '&cuisine_type=' + encodeURIComponent(cuisineParam);
    }

    api.txRequest(url)
      .then(function (data) {
        self.setData({ chefs: data || [], loadingChefs: false });
      })
      .catch(function (err) {
        console.error('loadChefs failed', err);
        self.setData({ loadingChefs: false, loadError: true });
      });
  },

  // ─── 跳转厨师详情 ───

  goToChefProfile: function (e) {
    var chefId = e.currentTarget.dataset.id;
    wx.navigateTo({
      url: '/pages/chef-at-home/chef-profile?chef_id=' + chefId +
        '&date=' + encodeURIComponent(this.data.selectedDate),
    });
  },
});
