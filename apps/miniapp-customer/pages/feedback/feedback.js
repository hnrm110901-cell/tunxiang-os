// 评价反馈 — 五维评分+文字+拍照+匿名
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    activeTab: 'new',
    // --- 五维评分 ---
    dimensions: [
      { key: 'taste', label: '口味', score: 5 },
      { key: 'service', label: '服务', score: 5 },
      { key: 'environment', label: '环境', score: 5 },
      { key: 'value', label: '性价比', score: 5 },
      { key: 'overall', label: '整体', score: 5 },
    ],
    ratingLabels: ['很差', '较差', '一般', '不错', '很棒'],
    // 旧的单一评分（兼容）
    rating: 5,
    ratingLabel: '很棒',
    // --- 评价内容 ---
    content: '',
    images: [],
    maxImages: 6,
    orderId: '',
    isAnonymous: false,
    submitting: false,
    // --- 我的评价 ---
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

  // --- 五维评分 ---

  setDimensionScore: function (e) {
    var dimKey = e.currentTarget.dataset.dim;
    var score = Number(e.currentTarget.dataset.score);
    var dims = this.data.dimensions.slice();
    for (var i = 0; i < dims.length; i++) {
      if (dims[i].key === dimKey) {
        dims[i] = {
          key: dims[i].key,
          label: dims[i].label,
          score: score,
        };
        break;
      }
    }

    // 计算整体平均分（向上取整）
    var total = 0;
    var count = 0;
    for (var j = 0; j < dims.length; j++) {
      if (dims[j].key !== 'overall') {
        total += dims[j].score;
        count++;
      }
    }
    var avgScore = count > 0 ? Math.round(total / count) : 5;
    // 更新整体分
    for (var k = 0; k < dims.length; k++) {
      if (dims[k].key === 'overall') {
        dims[k] = { key: 'overall', label: '整体', score: avgScore };
        break;
      }
    }

    this.setData({
      dimensions: dims,
      rating: avgScore,
      ratingLabel: this.data.ratingLabels[avgScore - 1],
    });
  },

  // --- 兼容旧单一评分 ---
  setRating: function (e) {
    var score = Number(e.currentTarget.dataset.score);
    this.setData({
      rating: score,
      ratingLabel: this.data.ratingLabels[score - 1],
    });
  },

  // --- 匿名 ---

  toggleAnonymous: function () {
    this.setData({ isAnonymous: !this.data.isAnonymous });
  },

  // --- 内容 ---

  onContentInput: function (e) {
    this.setData({ content: e.detail.value });
  },

  // --- 图片 ---

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

  // --- 提交 ---

  submitFeedback: function () {
    var self = this;
    if (!self.data.content.trim()) {
      wx.showToast({ title: '请填写评价内容', icon: 'none' });
      return;
    }

    self.setData({ submitting: true });

    // 构造五维评分数据
    var dimensionScores = {};
    self.data.dimensions.forEach(function (d) {
      dimensionScores[d.key] = d.score;
    });

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
        dimension_scores: dimensionScores,
        content: self.data.content,
        image_urls: imageUrls,
        is_anonymous: self.data.isAnonymous,
      });
    }).then(function () {
      wx.showToast({ title: '评价成功', icon: 'success' });
      self.setData({
        dimensions: [
          { key: 'taste', label: '口味', score: 5 },
          { key: 'service', label: '服务', score: 5 },
          { key: 'environment', label: '环境', score: 5 },
          { key: 'value', label: '性价比', score: 5 },
          { key: 'overall', label: '整体', score: 5 },
        ],
        rating: 5,
        ratingLabel: '很棒',
        content: '',
        images: [],
        orderId: '',
        isAnonymous: false,
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

  // --- 我的评价 ---

  _loadFeedbacks: function () {
    var self = this;
    self.setData({ loadingFeedbacks: true });

    api.fetchMyFeedbacks()
      .then(function (data) {
        var items = (data.items || []).map(function (f) {
          return {
            id: f.id,
            rating: f.rating || 5,
            dimensionScores: f.dimension_scores || {},
            content: f.content || '',
            imageUrls: f.image_urls || [],
            createdAt: (f.created_at || '').slice(0, 10),
            reply: f.reply || '',
            isAnonymous: f.is_anonymous || false,
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
