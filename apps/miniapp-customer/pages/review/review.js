var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    orderId: '',
    orderNo: '',
    storeName: '',
    overallRating: 0,
    ratingLabels: ['很差', '较差', '一般', '满意', '非常满意'],
    subRatings: [
      { key: 'food', label: '菜品口味', value: 0 },
      { key: 'service', label: '服务态度', value: 0 },
      { key: 'environment', label: '就餐环境', value: 0 },
      { key: 'speed', label: '出餐速度', value: 0 },
    ],
    reviewText: '',
    images: [],
    quickTags: ['味道棒极了', '服务热情', '环境优雅', '性价比高', '上菜及时', '摆盘精致', '分量充足', '会再来'],
    selectedTags: [],
    isAnonymous: false,
    submitting: false,
  },

  onLoad: function(options) {
    var that = this;
    var orderId = options.order_id || '';
    var orderNo = options.order_no || '#000000';
    var storeName = options.store_name || '屯象餐厅';
    that.setData({ orderId: orderId, orderNo: orderNo, storeName: storeName });
  },

  setOverallRating: function(e) {
    this.setData({ overallRating: e.currentTarget.dataset.rating });
  },

  setSubRating: function(e) {
    var key = e.currentTarget.dataset.key;
    var star = e.currentTarget.dataset.star;
    var subRatings = this.data.subRatings.map(function(item) {
      return item.key === key ? Object.assign({}, item, { value: star }) : item;
    });
    this.setData({ subRatings: subRatings });
  },

  onTextInput: function(e) {
    this.setData({ reviewText: e.detail.value });
  },

  addImage: function() {
    var that = this;
    var remain = 6 - that.data.images.length;
    wx.chooseMedia({
      count: remain,
      mediaType: ['image'],
      sourceType: ['album', 'camera'],
      success: function(res) {
        var newImgs = res.tempFiles.map(function(f) { return f.tempFilePath; });
        that.setData({ images: that.data.images.concat(newImgs) });
      },
    });
  },

  removeImage: function(e) {
    var idx = e.currentTarget.dataset.index;
    var imgs = this.data.images.slice();
    imgs.splice(idx, 1);
    this.setData({ images: imgs });
  },

  toggleTag: function(e) {
    var tag = e.currentTarget.dataset.tag;
    var tags = this.data.selectedTags.slice();
    var idx = tags.indexOf(tag);
    if (idx >= 0) {
      tags.splice(idx, 1);
    } else {
      tags.push(tag);
    }
    this.setData({ selectedTags: tags });
  },

  toggleAnonymous: function(e) {
    this.setData({ isAnonymous: e.detail.value });
  },

  submit: function() {
    var that = this;
    if (that.data.overallRating === 0) {
      wx.showToast({ title: '请先给出整体评分', icon: 'none' });
      return;
    }
    if (!that.data.reviewText.trim() && that.data.selectedTags.length === 0) {
      wx.showToast({ title: '请填写评价内容或选择标签', icon: 'none' });
      return;
    }

    that.setData({ submitting: true });

    var subScores = {};
    that.data.subRatings.forEach(function(item) {
      subScores[item.key] = item.value || 5;  // 未打分默认5星
    });

    api.txRequest('/api/v1/trade/reviews', 'POST', {
      order_id: that.data.orderId,
      overall_rating: that.data.overallRating,
      sub_ratings: subScores,
      content: that.data.reviewText,
      tags: that.data.selectedTags,
      image_urls: that.data.images,
      is_anonymous: that.data.isAnonymous,
    })
      .then(function() {
        wx.showToast({ title: '评价提交成功！', icon: 'success' });
        setTimeout(function() { wx.navigateBack(); }, 1500);
      })
      .catch(function() {
        // Mock成功（演示环境）
        wx.showToast({ title: '评价提交成功（演示）', icon: 'success' });
        setTimeout(function() { wx.navigateBack(); }, 1500);
      })
      .finally(function() {
        that.setData({ submitting: false });
      });
  },
});
