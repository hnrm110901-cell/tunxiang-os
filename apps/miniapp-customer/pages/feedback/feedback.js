// 评价 + 售后 — 打分+文字+拍照
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    activeTab: 'new',
    // ─── 新评价 ───
    rating: 5,
    ratingLabels: ['很差', '较差', '一般', '不错', '很棒'],
    ratingLabel: '很棒',
    content: '',
    images: [],
    maxImages: 6,
    orderId: '',
    submitting: false,
    // ─── 我的评价 ───
    feedbacks: [],
    loadingFeedbacks: false,
  },

  onLoad: function (options) {
    if (options.order_id) {
      this.setData({ orderId: options.order_id, activeTab: 'new' });
    }
  },

  onShow: function () {
    if (this.data.activeTab === 'list') {
      this._loadFeedbacks();
    }
  },

  onShareAppMessage: function () {
    return { title: '屯象点餐 - 评价', path: '/pages/feedback/feedback' };
  },

  switchTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    this.setData({ activeTab: tab });
    if (tab === 'list') {
      this._loadFeedbacks();
    }
  },

  // ─── 新评价 ───

  setRating: function (e) {
    var score = Number(e.currentTarget.dataset.score);
    this.setData({
      rating: score,
      ratingLabel: this.data.ratingLabels[score - 1],
    });
  },

  onContentInput: function (e) {
    this.setData({ content: e.detail.value });
  },

  chooseImage: function () {
    var self = this;
    var remaining = self.data.maxImages - self.data.images.length;
    if (remaining <= 0) {
      wx.showToast({ title: '最多上传' + self.data.maxImages + '张', icon: 'none' });
      return;
    }

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
    wx.previewImage({
      current: url,
      urls: this.data.images,
    });
  },

  submitFeedback: function () {
    var self = this;
    if (!self.data.content.trim()) {
      wx.showToast({ title: '请填写评价内容', icon: 'none' });
      return;
    }

    self.setData({ submitting: true });

    // 先上传图片，再提交评价
    var uploadPromise = self.data.images.length > 0
      ? self._uploadImages(self.data.images)
      : Promise.resolve([]);

    uploadPromise.then(function (imageUrls) {
      return api.submitFeedback({
        store_id: app.globalData.storeId,
        customer_id: wx.getStorageSync('tx_customer_id') || '',
        order_id: self.data.orderId || '',
        rating: self.data.rating,
        content: self.data.content,
        image_urls: imageUrls,
      });
    }).then(function () {
      wx.showToast({ title: '评价成功', icon: 'success' });
      self.setData({
        rating: 5,
        ratingLabel: '很棒',
        content: '',
        images: [],
        orderId: '',
        submitting: false,
        activeTab: 'list',
      });
      self._loadFeedbacks();
    }).catch(function (err) {
      console.error('提交评价失败', err);
      wx.showToast({ title: err.message || '提交失败', icon: 'none' });
      self.setData({ submitting: false });
    });
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
                reject(new Error('上传失败'));
              }
            } catch (e) {
              reject(new Error('上传返回格式错误'));
            }
          },
          fail: function (err) {
            reject(err);
          },
        });
      });
    });

    return Promise.all(promises);
  },

  // ─── 我的评价 ───

  _loadFeedbacks: function () {
    var self = this;
    self.setData({ loadingFeedbacks: true });

    api.fetchMyFeedbacks()
      .then(function (data) {
        var items = (data.items || []).map(function (f) {
          return {
            id: f.id,
            rating: f.rating || 5,
            content: f.content || '',
            imageUrls: f.image_urls || [],
            createdAt: (f.created_at || '').slice(0, 10),
            reply: f.reply || '',
          };
        });
        self.setData({ feedbacks: items, loadingFeedbacks: false });
      })
      .catch(function (err) {
        console.error('加载评价失败', err);
        self.setData({ loadingFeedbacks: false });
      });
  },
});
