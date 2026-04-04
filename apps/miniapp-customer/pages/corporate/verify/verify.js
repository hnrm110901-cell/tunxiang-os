// 企业员工身份认证页
// POST /api/v1/trade/enterprise/verify
// 成功后存储 company_id / company_name / credit_limit 到 storage

var api = require('../../../utils/api.js');

Page({
  data: {
    corpCode: '',          // 企业码（6-10位数字）
    empNo: '',             // 员工工号
    proofImageUrl: '',     // 在职证明预览图（本地路径）
    proofImagePath: '',    // 上传用原始路径

    // 字段错误提示
    corpCodeError: '',
    empNoError: '',

    submitting: false,
  },

  // ─── 输入事件 ───

  onCorpCodeInput: function (e) {
    this.setData({ corpCode: e.detail.value, corpCodeError: '' });
  },

  onEmpNoInput: function (e) {
    this.setData({ empNo: e.detail.value, empNoError: '' });
  },

  // ─── 上传在职证明 ───

  chooseProofImage: function () {
    var self = this;
    wx.chooseImage({
      count: 1,
      sizeType: ['compressed'],
      sourceType: ['album', 'camera'],
      success: function (res) {
        var path = res.tempFilePaths[0];
        self.setData({
          proofImageUrl: path,
          proofImagePath: path,
        });
      },
    });
  },

  removeProofImage: function () {
    this.setData({ proofImageUrl: '', proofImagePath: '' });
  },

  // ─── 表单校验 ───

  validate: function () {
    var ok = true;
    var corpCode = this.data.corpCode.trim();
    var empNo = this.data.empNo.trim();

    if (!corpCode || !/^\d{6,10}$/.test(corpCode)) {
      this.setData({ corpCodeError: '请输入6-10位数字企业码' });
      ok = false;
    }

    if (!empNo) {
      this.setData({ empNoError: '请输入员工工号' });
      ok = false;
    }

    return ok;
  },

  // ─── 上传图片到服务端（如有） ───

  uploadProofIfNeeded: function () {
    var self = this;
    var path = self.data.proofImagePath;
    if (!path) return Promise.resolve('');

    var app = getApp();
    return new Promise(function (resolve) {
      wx.uploadFile({
        url: (app.globalData.apiBase || '') + '/api/v1/upload/image',
        filePath: path,
        name: 'file',
        header: {
          'X-Tenant-ID': app.globalData.tenantId || '',
          'Authorization': wx.getStorageSync('tx_token') ? 'Bearer ' + wx.getStorageSync('tx_token') : '',
        },
        success: function (res) {
          try {
            var data = JSON.parse(res.data);
            resolve(data.data ? data.data.url || '' : '');
          } catch (err) {
            resolve('');
          }
        },
        fail: function () {
          // 上传失败不阻断主流程
          resolve('');
        },
      });
    });
  },

  // ─── 提交认证 ───

  submitVerify: function () {
    if (!this.validate()) return;
    if (this.data.submitting) return;

    var self = this;
    self.setData({ submitting: true });

    self.uploadProofIfNeeded().then(function (proofUrl) {
      var customerId = wx.getStorageSync('tx_customer_id') || '';
      var payload = {
        corp_code: self.data.corpCode.trim(),
        emp_no: self.data.empNo.trim(),
        customer_id: customerId,
      };
      if (proofUrl) payload.proof_url = proofUrl;

      return api.verifyEmployee(payload);
    }).then(function (data) {
      // 成功：存储企业信息到 storage
      wx.setStorageSync('tx_company_id', data.company_id || '');
      wx.setStorageSync('tx_company_name', data.company_name || '');
      wx.setStorageSync('tx_credit_limit_fen', data.credit_limit_fen || 0);

      wx.showToast({ title: '认证成功', icon: 'success', duration: 1500 });

      // 延迟返回，让用户看到成功提示
      setTimeout(function () {
        // 尝试返回上一页；若为首次进入则跳到企业用餐首页
        var pages = getCurrentPages();
        if (pages.length > 1) {
          wx.navigateBack();
        } else {
          wx.reLaunch({ url: '/pages/corporate-dining/index' });
        }
      }, 1600);
    }).catch(function (err) {
      self.setData({ submitting: false });
      var msg = (err && err.message) ? err.message : '企业码或工号错误，请联系HR';
      wx.showModal({
        title: '认证失败',
        content: msg,
        showCancel: false,
        confirmText: '知道了',
        confirmColor: '#FF6B2C',
      });
    });
  },
});
