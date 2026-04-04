// 地址管理 — 列表+默认标记+编辑删除
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    addressList: [],
    loading: false,
    selectMode: false, // 是否从下单页选地址进入
  },

  onLoad: function (options) {
    if (options.select === '1') {
      this.setData({ selectMode: true });
    }
  },

  onShow: function () {
    this._loadAddresses();
  },

  _loadAddresses: function () {
    var self = this;
    self.setData({ loading: true });

    api.txRequest('/api/v1/member/addresses', 'GET')
      .then(function (data) {
        var items = (data.items || data || []).map(function (a) {
          return {
            id: a.id,
            name: a.name || '',
            phone: a.phone || '',
            region: a.region || '',
            detail: a.detail || '',
            tag: a.tag || '',
            is_default: a.is_default || false,
          };
        });
        // 默认地址排最前
        items.sort(function (a, b) {
          return (b.is_default ? 1 : 0) - (a.is_default ? 1 : 0);
        });
        self.setData({ addressList: items, loading: false });
      })
      .catch(function (err) {
        console.warn('加载地址失败，使用Mock数据', err);
        self.setData({
          addressList: [
            { id: 'mock1', name: '张三', phone: '138****8888', region: '湖南省长沙市岳麓区', detail: '麓谷街道中电软件园1号楼', tag: '公司', is_default: true },
            { id: 'mock2', name: '张三', phone: '138****8888', region: '湖南省长沙市天心区', detail: '芙蓉南路某某小区3栋', tag: '家', is_default: false },
          ],
          loading: false,
        });
      });
  },

  addAddress: function () {
    wx.navigateTo({ url: '/pages/address-edit/address-edit' });
  },

  editAddress: function (e) {
    var id = e.currentTarget.dataset.id;
    wx.navigateTo({ url: '/pages/address-edit/address-edit?id=' + id });
  },

  deleteAddress: function (e) {
    var self = this;
    var id = e.currentTarget.dataset.id;

    wx.showModal({
      title: '确认删除',
      content: '确定要删除这个地址吗？',
      confirmColor: '#FF6B2C',
      success: function (res) {
        if (!res.confirm) return;
        api.txRequest('/api/v1/member/addresses/' + id, 'DELETE')
          .then(function () {
            wx.showToast({ title: '已删除', icon: 'success' });
            self._loadAddresses();
          })
          .catch(function (err) {
            // Mock降级：直接从列表中移除
            var list = self.data.addressList.filter(function (a) { return a.id !== id; });
            self.setData({ addressList: list });
            wx.showToast({ title: '已删除', icon: 'success' });
          });
      },
    });
  },

  setDefault: function (e) {
    var self = this;
    var id = e.currentTarget.dataset.id;

    api.txRequest('/api/v1/member/addresses/' + id + '/default', 'PUT')
      .then(function () {
        wx.showToast({ title: '已设为默认', icon: 'success' });
        self._loadAddresses();
      })
      .catch(function () {
        // Mock降级
        var list = self.data.addressList.map(function (a) {
          return {
            id: a.id, name: a.name, phone: a.phone,
            region: a.region, detail: a.detail, tag: a.tag,
            is_default: a.id === id,
          };
        });
        list.sort(function (a, b) {
          return (b.is_default ? 1 : 0) - (a.is_default ? 1 : 0);
        });
        self.setData({ addressList: list });
        wx.showToast({ title: '已设为默认', icon: 'success' });
      });
  },

  onSelectAddress: function (e) {
    if (!this.data.selectMode) return;
    var id = e.currentTarget.dataset.id;
    var addr = null;
    for (var i = 0; i < this.data.addressList.length; i++) {
      if (this.data.addressList[i].id === id) {
        addr = this.data.addressList[i];
        break;
      }
    }
    if (addr) {
      var pages = getCurrentPages();
      var prevPage = pages[pages.length - 2];
      if (prevPage && prevPage.onAddressSelected) {
        prevPage.onAddressSelected(addr);
      }
      wx.navigateBack();
    }
  },
});
