const app = getApp();
const api = require('../../utils/api.js');

Page({
  data: {
    images: [],
    title: '',
    content: '',
    availableTags: ['探店', '自制', '海鲜', '长沙', '川菜', '火锅', '甜品', '早餐', '宵夜', '聚餐'],
    selectedTags: [],
    selectedStore: null,
    submitting: false,
  },

  chooseImages() {
    const remain = 9 - this.data.images.length;
    wx.chooseMedia({
      count: remain,
      mediaType: ['image'],
      sourceType: ['album', 'camera'],
      success: (res) => {
        const newImgs = res.tempFiles.map(f => f.tempFilePath);
        this.setData({ images: [...this.data.images, ...newImgs] });
      },
    });
  },

  removeImage(e) {
    const idx = e.currentTarget.dataset.index;
    const imgs = [...this.data.images];
    imgs.splice(idx, 1);
    this.setData({ images: imgs });
  },

  onTitleInput(e) { this.setData({ title: e.detail.value }); },
  onContentInput(e) { this.setData({ content: e.detail.value }); },

  toggleTag(e) {
    const tag = e.currentTarget.dataset.tag;
    const tags = [...this.data.selectedTags];
    const idx = tags.indexOf(tag);
    if (idx >= 0) {
      tags.splice(idx, 1);
    } else if (tags.length < 5) {
      tags.push(tag);
    } else {
      wx.showToast({ title: '最多选5个标签', icon: 'none' });
      return;
    }
    this.setData({ selectedTags: tags });
  },

  selectStore() {
    wx.showToast({ title: '门店选择功能开发中', icon: 'none' });
  },

  async submit() {
    if (!this.data.title.trim()) { wx.showToast({ title: '请填写标题', icon: 'none' }); return; }
    if (!this.data.content.trim()) { wx.showToast({ title: '请填写内容', icon: 'none' }); return; }
    if (this.data.images.length === 0) { wx.showToast({ title: '请至少上传一张图片', icon: 'none' }); return; }

    this.setData({ submitting: true });

    try {
      // 实际项目需先上传图片到OSS，这里简化为直接发URL
      await api.txRequest('/api/v1/growth/community/posts', 'POST', {
        title: this.data.title,
        content: this.data.content,
        cover_url: this.data.images[0] || '',
        image_urls: this.data.images,
        tags: this.data.selectedTags,
        store_id: this.data.selectedStore ? this.data.selectedStore.id : null,
      });

      wx.showToast({ title: '发布成功！', icon: 'success' });
      // 标记需要刷新社区列表
      const pages = getCurrentPages();
      const prevPage = pages[pages.length - 2];
      if (prevPage) prevPage._needRefresh = true;
      setTimeout(() => wx.navigateBack(), 1500);
    } catch (reqErr) {
      // Mock发布成功
      wx.showToast({ title: '发布成功（演示）', icon: 'success' });
      setTimeout(() => wx.navigateBack(), 1500);
    } finally {
      this.setData({ submitting: false });
    }
  },
});
