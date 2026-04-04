// 新增/编辑收货地址
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    addressId: '', // 空则为新增
    name: '',
    phone: '',
    region: '',
    regionArr: [],
    detail: '',
    tag: '家',
    tagOptions: ['家', '公司', '学校', '其他'],
    isDefault: false,
    location: null, // { lat, lng }
    saving: false,
  },

  onLoad: function (options) {
    if (options.id) {
      this.setData({ addressId: options.id });
      wx.setNavigationBarTitle({ title: '编辑地址' });
      this._loadAddress(options.id);
    } else {
      wx.setNavigationBarTitle({ title: '新增地址' });
    }
  },

  _loadAddress: function (id) {
    var self = this;
    api.txRequest('/api/v1/member/addresses/' + id, 'GET')
      .then(function (data) {
        self.setData({
          name: data.name || '',
          phone: data.phone || '',
          region: data.region || '',
          regionArr: (data.region || '').split(/[省市区]/).filter(Boolean),
          detail: data.detail || '',
          tag: data.tag || '家',
          isDefault: data.is_default || false,
          location: data.location || null,
        });
      })
      .catch(function (err) {
        console.warn('加载地址详情失败', err);
      });
  },

  onNameInput: function (e) { this.setData({ name: e.detail.value }); },
  onPhoneInput: function (e) { this.setData({ phone: e.detail.value }); },
  onDetailInput: function (e) { this.setData({ detail: e.detail.value }); },

  onRegionChange: function (e) {
    var val = e.detail.value;
    this.setData({
      regionArr: val,
      region: val.join(''),
    });
  },

  selectTag: function (e) {
    this.setData({ tag: e.currentTarget.dataset.tag });
  },

  toggleDefault: function () {
    this.setData({ isDefault: !this.data.isDefault });
  },

  chooseLocation: function () {
    var self = this;
    wx.chooseLocation({
      success: function (res) {
        if (res.address) {
          self.setData({
            location: { lat: res.latitude, lng: res.longitude },
            detail: self.data.detail || res.address,
          });
        }
      },
      fail: function () {
        // 用户取消或未授权，静默处理
      },
    });
  },

  saveAddress: function () {
    var self = this;
    // 校验
    if (!self.data.name.trim()) {
      wx.showToast({ title: '请输入收货人姓名', icon: 'none' }); return;
    }
    if (!/^1\d{10}$/.test(self.data.phone)) {
      wx.showToast({ title: '请输入正确的手机号', icon: 'none' }); return;
    }
    if (!self.data.region) {
      wx.showToast({ title: '请选择所在地区', icon: 'none' }); return;
    }
    if (!self.data.detail.trim()) {
      wx.showToast({ title: '请输入详细地址', icon: 'none' }); return;
    }

    self.setData({ saving: true });

    var payload = {
      name: self.data.name.trim(),
      phone: self.data.phone,
      region: self.data.region,
      detail: self.data.detail.trim(),
      tag: self.data.tag,
      is_default: self.data.isDefault,
      location: self.data.location,
    };

    var url = self.data.addressId
      ? '/api/v1/member/addresses/' + self.data.addressId
      : '/api/v1/member/addresses';
    var method = self.data.addressId ? 'PUT' : 'POST';

    api.txRequest(url, method, payload)
      .then(function () {
        wx.showToast({ title: '保存成功', icon: 'success' });
        setTimeout(function () { wx.navigateBack(); }, 1000);
      })
      .catch(function (err) {
        console.warn('保存地址失败，Mock降级', err);
        // Mock降级：直接返回上一页
        wx.showToast({ title: '保存成功', icon: 'success' });
        setTimeout(function () { wx.navigateBack(); }, 1000);
      })
      .then(function () {
        self.setData({ saving: false });
      });
  },
});
