// 扫码入口 — 识别桌码 → 跳转菜单
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    scanning: false,
    errorMsg: '',
    storeId: '',
    tableId: '',
    qrcode: '',
  },

  onLoad: function (options) {
    // 从桌码二维码扫描结果进入
    if (options.code) {
      this._parseAndRedirect(options.code, options.store_id, options.table_id);
      return;
    }

    // 如果有 store_id 和 table_id 直接跳转
    if (options.store_id && options.table_id) {
      this._goToTableMenu(options.store_id, options.table_id);
      return;
    }

    // 否则启动扫码
    this.startScan();
  },

  startScan: function () {
    var self = this;
    self.setData({ scanning: true, errorMsg: '' });

    wx.scanCode({
      onlyFromCamera: false,
      scanType: ['qrCode'],
      success: function (res) {
        var result = res.result || '';
        self._handleScanResult(result);
      },
      fail: function (err) {
        self.setData({
          scanning: false,
          errorMsg: err.errMsg === 'scanCode:fail cancel' ? '' : '扫码失败，请重试',
        });
      },
    });
  },

  _handleScanResult: function (result) {
    var self = this;
    // 桌码格式: TX-{store简码}-{table_no}
    if (result.indexOf('TX-') === 0) {
      self._parseAndRedirect(result, '', '');
      return;
    }

    // 小程序路径格式（通过小程序码扫入）
    if (result.indexOf('/pages/scan-order/') >= 0) {
      // 从路径中提取参数
      var params = self._parseUrlParams(result);
      if (params.code) {
        self._parseAndRedirect(params.code, params.store_id, params.table_id);
        return;
      }
      if (params.store_id && params.table_id) {
        self._goToTableMenu(params.store_id, params.table_id);
        return;
      }
    }

    // 无法识别
    self.setData({
      scanning: false,
      errorMsg: '无法识别桌码，请对准桌台二维码重新扫描',
    });
  },

  _parseAndRedirect: function (code, storeId, tableId) {
    var self = this;

    // 如果已有 store_id 和 table_id，直接跳转
    if (storeId && tableId) {
      self._goToTableMenu(storeId, tableId);
      return;
    }

    // 解析桌码
    self.setData({ scanning: true });
    api.txRequest('/api/v1/scan-order/qrcode/parse', 'POST', { code: code })
      .then(function (data) {
        // 解析成功，需要通过简码查找门店
        self.setData({
          qrcode: code,
          tableId: data.table_id,
        });
        self._goToTableMenu(data.store_id || app.globalData.storeId, data.table_id);
      })
      .catch(function (err) {
        self.setData({
          scanning: false,
          errorMsg: err.message || '桌码解析失败',
        });
      });
  },

  _goToTableMenu: function (storeId, tableId) {
    wx.redirectTo({
      url: '/pages/scan-order/table-menu?store_id=' +
        encodeURIComponent(storeId) +
        '&table_id=' + encodeURIComponent(tableId),
    });
  },

  _parseUrlParams: function (url) {
    var params = {};
    var queryStart = url.indexOf('?');
    if (queryStart < 0) return params;
    var query = url.substring(queryStart + 1);
    var pairs = query.split('&');
    for (var i = 0; i < pairs.length; i++) {
      var kv = pairs[i].split('=');
      if (kv.length === 2) {
        params[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1]);
      }
    }
    return params;
  },

  retrySccan: function () {
    this.setData({ errorMsg: '' });
    this.startScan();
  },
});
