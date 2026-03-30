// 宴席首页 — 婚宴/生日/商务/年会 四大宴席类型入口
// 不同于普通预订，宴席有专属流程：选类型→选菜单→选场地→确认(订金+合同)

var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    // ─── 宴席类型 ───
    banquetTypes: [
      {
        key: 'wedding',
        label: '婚宴',
        icon: '/assets/icon-wedding.png',
        desc: '浪漫婚宴定制',
        color: '#FF4D6A',
        minPerson: 10,
        maxPerson: 50,
      },
      {
        key: 'birthday',
        label: '生日宴',
        icon: '/assets/icon-birthday.png',
        desc: '生日寿宴定制',
        color: '#FF6B2C',
        minPerson: 6,
        maxPerson: 30,
      },
      {
        key: 'business',
        label: '商务宴',
        icon: '/assets/icon-business.png',
        desc: '商务接待定制',
        color: '#3B82F6',
        minPerson: 4,
        maxPerson: 20,
      },
      {
        key: 'annual',
        label: '年会',
        icon: '/assets/icon-annual.png',
        desc: '企业年会定制',
        color: '#8B5CF6',
        minPerson: 20,
        maxPerson: 100,
      },
    ],

    // ─── 热门宴席套餐 ───
    hotPackages: [],
    loadingPackages: false,

    // ─── 宴席案例展示 ───
    cases: [],

    // ─── 预约咨询 ───
    consultPhone: '400-888-8888',
  },

  onLoad: function () {
    this.loadHotPackages();
    this.loadCases();
  },

  // ─── 加载热门套餐 ───
  loadHotPackages: function () {
    var self = this;
    self.setData({ loadingPackages: true });
    api.get('/api/v1/banquet/hot-packages').then(function (res) {
      if (res.ok) {
        self.setData({ hotPackages: res.data.items || [], loadingPackages: false });
      } else {
        self.setData({ loadingPackages: false });
      }
    });
  },

  // ─── 加载宴席案例 ───
  loadCases: function () {
    var self = this;
    api.get('/api/v1/banquet/cases').then(function (res) {
      if (res.ok) {
        self.setData({ cases: res.data.items || [] });
      }
    });
  },

  // ─── 选择宴席类型 → 进入菜单选择 ───
  selectType: function (e) {
    var type = e.currentTarget.dataset.type;
    wx.navigateTo({
      url: '/pages/banquet-booking/menu-select?type=' + type.key +
           '&min=' + type.minPerson + '&max=' + type.maxPerson,
    });
  },

  // ─── 选择热门套餐 ───
  selectPackage: function (e) {
    var pkg = e.currentTarget.dataset.pkg;
    wx.navigateTo({
      url: '/pages/banquet-booking/menu-select?package_id=' + pkg.id + '&type=' + pkg.type,
    });
  },

  // ─── 电话咨询 ───
  callConsult: function () {
    wx.makePhoneCall({ phoneNumber: this.data.consultPhone });
  },

  // ─── 查看案例详情 ───
  viewCase: function (e) {
    var caseId = e.currentTarget.dataset.id;
    wx.navigateTo({ url: '/pages/banquet-booking/index?case_id=' + caseId });
  },
});
