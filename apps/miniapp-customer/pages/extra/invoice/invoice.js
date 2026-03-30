// 自助开票页面 — 调用 invoice_service 已有接口
var app = getApp();
var api = require('../../../utils/api.js');

Page({
  data: {
    orderId: '',
    amountYuan: '0.00',
    invoiceType: 'personal',  // personal / company
    title: '',
    taxId: '',
    email: '',
    submitting: false,
  },

  onLoad: function (options) {
    this.setData({
      orderId: options.order_id || '',
      amountYuan: options.amount || '0.00',
    });

    // 尝试从缓存读取上次填写的信息
    var cached = wx.getStorageSync('tx_invoice_info');
    if (cached) {
      this.setData({
        invoiceType: cached.invoiceType || 'personal',
        title: cached.title || '',
        taxId: cached.taxId || '',
        email: cached.email || '',
      });
    }
  },

  selectType: function (e) {
    this.setData({ invoiceType: e.currentTarget.dataset.type });
  },

  onTitleInput: function (e) { this.setData({ title: e.detail.value }); },
  onTaxIdInput: function (e) { this.setData({ taxId: e.detail.value }); },
  onEmailInput: function (e) { this.setData({ email: e.detail.value }); },

  submitInvoice: function () {
    var self = this;
    if (self.data.submitting) return;

    // 校验
    if (!self.data.title.trim()) {
      wx.showToast({ title: '请输入发票抬头', icon: 'none' });
      return;
    }
    if (self.data.invoiceType === 'company' && !self.data.taxId.trim()) {
      wx.showToast({ title: '请输入税号', icon: 'none' });
      return;
    }
    if (!self.data.email.trim() || self.data.email.indexOf('@') < 0) {
      wx.showToast({ title: '请输入有效邮箱', icon: 'none' });
      return;
    }

    self.setData({ submitting: true });

    // 缓存开票信息方便下次复用
    wx.setStorageSync('tx_invoice_info', {
      invoiceType: self.data.invoiceType,
      title: self.data.title,
      taxId: self.data.taxId,
      email: self.data.email,
    });

    // 调用后端开票接口
    api.request({
      url: '/api/v1/invoice/request',
      method: 'POST',
      data: {
        order_id: self.data.orderId,
        invoice_type: self.data.invoiceType === 'company' ? 'vat_normal' : 'personal',
        title: self.data.title,
        tax_id: self.data.invoiceType === 'company' ? self.data.taxId : undefined,
        email: self.data.email,
      },
    }).then(function (res) {
      wx.showToast({ title: '开票申请已提交', icon: 'success' });
      setTimeout(function () {
        wx.navigateBack();
      }, 1500);
    }).catch(function (err) {
      wx.showToast({ title: err.message || '开票失败', icon: 'none' });
      self.setData({ submitting: false });
    });
  },
});
