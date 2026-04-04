// 个人资料编辑页
var app = getApp();
var api = require('../../utils/api.js');
var auth = require('../../utils/auth.js');

Page({
  data: {
    avatarUrl: '',
    nickname: '',
    gender: 0, // 0未知 1男 2女
    genderOptions: ['未知', '男', '女'],
    birthday: '',
    phone: '',
    phoneMasked: '',
    // 口味偏好
    flavorTags: ['辣', '不辣', '清淡', '重口', '甜', '酸'],
    selectedFlavors: [],
    // 过敏原
    allergenTags: ['花生', '海鲜', '乳制品', '麸质', '坚果'],
    selectedAllergens: [],
    saving: false,
  },

  onLoad: function () {
    this._loadProfile();
  },

  _loadProfile: function () {
    var self = this;
    api.fetchMemberProfile()
      .then(function (data) {
        var phone = data.phone || '';
        var phoneMasked = phone.length >= 7
          ? phone.slice(0, 3) + '****' + phone.slice(-4)
          : phone;
        self.setData({
          avatarUrl: data.avatar_url || '',
          nickname: data.nickname || '',
          gender: data.gender || 0,
          birthday: data.birthday || '',
          phone: phone,
          phoneMasked: phoneMasked,
          selectedFlavors: data.flavor_preferences || [],
          selectedAllergens: data.allergens || [],
        });
      })
      .catch(function (err) {
        console.warn('加载个人资料失败', err);
        // 降级：使用本地缓存
        var cached = wx.getStorageSync('tx_profile_cache') || {};
        if (cached.nickname) {
          self.setData({
            avatarUrl: cached.avatar_url || '',
            nickname: cached.nickname || '',
            gender: cached.gender || 0,
            birthday: cached.birthday || '',
            phone: cached.phone || '',
            phoneMasked: cached.phone
              ? cached.phone.slice(0, 3) + '****' + cached.phone.slice(-4)
              : '',
          });
        }
      });
  },

  // 选择头像
  chooseAvatar: function () {
    var self = this;
    wx.chooseImage({
      count: 1,
      sizeType: ['compressed'],
      sourceType: ['album', 'camera'],
      success: function (res) {
        var tempPath = res.tempFilePaths[0];
        self.setData({ avatarUrl: tempPath });
      },
    });
  },

  // 昵称输入
  onNicknameInput: function (e) {
    this.setData({ nickname: e.detail.value });
  },

  // 性别选择
  onGenderChange: function (e) {
    this.setData({ gender: parseInt(e.detail.value, 10) });
  },

  // 生日选择
  onBirthdayChange: function (e) {
    this.setData({ birthday: e.detail.value });
  },

  // 口味偏好标签切换
  toggleFlavor: function (e) {
    var tag = e.currentTarget.dataset.tag;
    var selected = this.data.selectedFlavors.slice();
    var idx = selected.indexOf(tag);
    if (idx >= 0) {
      selected.splice(idx, 1);
    } else {
      selected.push(tag);
    }
    this.setData({ selectedFlavors: selected });
  },

  // 过敏原标签切换
  toggleAllergen: function (e) {
    var tag = e.currentTarget.dataset.tag;
    var selected = this.data.selectedAllergens.slice();
    var idx = selected.indexOf(tag);
    if (idx >= 0) {
      selected.splice(idx, 1);
    } else {
      selected.push(tag);
    }
    this.setData({ selectedAllergens: selected });
  },

  // 更换手机号（跳转或弹窗）
  changePhone: function () {
    wx.showToast({ title: '请联系客服更换手机号', icon: 'none' });
  },

  // 保存
  saveProfile: function () {
    var self = this;
    if (self.data.saving) return;

    var nickname = (self.data.nickname || '').trim();
    if (!nickname) {
      wx.showToast({ title: '请输入昵称', icon: 'none' });
      return;
    }

    self.setData({ saving: true });
    wx.showLoading({ title: '保存中...' });

    var customerId = wx.getStorageSync('tx_customer_id') || '';
    if (!customerId) {
      wx.hideLoading();
      wx.showToast({ title: '请先登录', icon: 'none' });
      self.setData({ saving: false });
      return;
    }

    // 如果有新头像需要先上传
    var avatarUrl = self.data.avatarUrl;
    var uploadPromise;
    if (avatarUrl && avatarUrl.indexOf('tmp') >= 0) {
      // 临时文件，需要上传
      uploadPromise = self._uploadAvatar(avatarUrl);
    } else {
      uploadPromise = Promise.resolve(avatarUrl);
    }

    uploadPromise
      .then(function (finalAvatarUrl) {
        return api.txRequest(
          '/api/v1/member/customers/' + encodeURIComponent(customerId),
          'PUT',
          {
            nickname: nickname,
            avatar_url: finalAvatarUrl,
            gender: self.data.gender,
            birthday: self.data.birthday,
            flavor_preferences: self.data.selectedFlavors,
            allergens: self.data.selectedAllergens,
          }
        );
      })
      .then(function () {
        wx.hideLoading();
        wx.showToast({ title: '保存成功', icon: 'success' });
        self.setData({ saving: false });
        setTimeout(function () {
          wx.navigateBack();
        }, 1000);
      })
      .catch(function (err) {
        wx.hideLoading();
        wx.showToast({ title: err.message || '保存失败', icon: 'none' });
        self.setData({ saving: false });
      });
  },

  _uploadAvatar: function (tempPath) {
    var baseUrl = app.globalData.apiBase || require('../../utils/config.js').apiBase;
    return new Promise(function (resolve, reject) {
      wx.uploadFile({
        url: baseUrl + '/api/v1/member/upload/avatar',
        filePath: tempPath,
        name: 'file',
        header: {
          'Authorization': 'Bearer ' + (wx.getStorageSync('tx_token') || ''),
          'X-Tenant-ID': app.globalData.tenantId || '',
        },
        success: function (res) {
          try {
            var data = JSON.parse(res.data);
            if (data.ok && data.data && data.data.url) {
              resolve(data.data.url);
            } else {
              resolve(tempPath); // 降级使用本地路径
            }
          } catch (e) {
            resolve(tempPath);
          }
        },
        fail: function () {
          resolve(tempPath); // 降级
        },
      });
    });
  },
});
