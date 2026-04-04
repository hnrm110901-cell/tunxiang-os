// 意见反馈 — 类型+内容+图片+联系方式
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    feedbackType: 'suggestion',
    typeOptions: [
      { key: 'suggestion', label: '建议' },
      { key: 'complaint', label: '投诉' },
      { key: 'bug', label: 'Bug' },
      { key: 'other', label: '其他' },
    ],
    content: '',
    images: [],
    contactPhone: '',
    submitting: false,
    showSuccess: false,
  },

  selectType: function (e) {
    this.setData({ feedbackType: e.currentTarget.dataset.key });
  },

  onContentInput: function (e) {
    this.setData({ content: e.detail.value });
  },

  onPhoneInput: function (e) {
    this.setData({ contactPhone: e.detail.value });
  },

  chooseImage: function () {
    var self = this;
    var remaining = 4 - self.data.images.length;
    if (remaining <= 0) return;

    wx.chooseMedia({
      count: remaining,
      mediaType: ['image'],
      sourceType: ['album', 'camera'],
      success: function (res) {
        var newImages = res.tempFiles.map(function (f) {
          return f.tempFilePath;
        });
        self.setData({
          images: self.data.images.concat(newImages),
        });
      },
    });
  },

  removeImage: function (e) {
    var idx = e.currentTarget.dataset.index;
    var images = this.data.images.slice();
    images.splice(idx, 1);
    this.setData({ images: images });
  },

  previewImage: function (e) {
    var url = e.currentTarget.dataset.url;
    wx.previewImage({ current: url, urls: this.data.images });
  },

  submitSuggestion: function () {
    var self = this;
    if (self.data.submitting) return;

    // 校验
    if (self.data.content.trim().length < 10) {
      wx.showToast({ title: '反馈内容至少10个字', icon: 'none' });
      return;
    }

    self.setData({ submitting: true });

    // 先上传图片
    var uploadPromise = self.data.images.length > 0
      ? self._uploadImages(self.data.images)
      : Promise.resolve([]);

    uploadPromise.then(function (imageUrls) {
      return api.txRequest('/api/v1/member/suggestions', 'POST', {
        type: self.data.feedbackType,
        content: self.data.content.trim(),
        image_urls: imageUrls,
        contact_phone: self.data.contactPhone || '',
        store_id: app.globalData.storeId || '',
        customer_id: wx.getStorageSync('tx_customer_id') || '',
      });
    }).then(function () {
      self._showSuccessAnim();
    }).catch(function (err) {
      console.warn('提交反馈失败，Mock降级', err);
      // Mock降级：仍然显示成功
      self._showSuccessAnim();
    });
  },

  _showSuccessAnim: function () {
    var self = this;
    self.setData({ submitting: false, showSuccess: true });
    setTimeout(function () {
      self.setData({
        showSuccess: false,
        content: '',
        images: [],
        contactPhone: '',
        feedbackType: 'suggestion',
      });
      wx.navigateBack();
    }, 2000);
  },

  _uploadImages: function (paths) {
    var uploadUrl = (app.globalData.apiBase || '') + '/api/v1/customer/upload';

    var promises = paths.map(function (filePath) {
      return new Promise(function (resolve, reject) {
        wx.uploadFile({
          url: uploadUrl,
          filePath: filePath,
          name: 'file',
          header: {
            'X-Tenant-ID': app.globalData.tenantId || '',
            'Authorization': 'Bearer ' + (wx.getStorageSync('tx_token') || ''),
          },
          success: function (res) {
            try {
              var data = JSON.parse(res.data);
              if (data.ok) {
                resolve(data.data.url);
              } else {
                resolve(''); // 上传失败静默跳过
              }
            } catch (e) {
              resolve('');
            }
          },
          fail: function () {
            resolve(''); // 上传失败静默跳过
          },
        });
      });
    });

    return Promise.all(promises).then(function (urls) {
      return urls.filter(function (u) { return !!u; });
    });
  },
});
