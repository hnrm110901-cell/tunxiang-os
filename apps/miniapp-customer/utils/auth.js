/**
 * miniapp-customer 微信登录 + Token 管理
 * 登录流程: wx.login获取code → 后端换取openId+token → 本地缓存
 */

var config = require('./config.js');

/**
 * 静默登录：获取 code 并换取 token
 * @returns {Promise<{token: string, customerId: string, openId: string}>}
 */
function silentLogin() {
  return new Promise(function (resolve, reject) {
    wx.login({
      success: function (loginRes) {
        if (!loginRes.code) {
          reject(new Error('wx.login 获取 code 失败'));
          return;
        }
        var app = getApp();
        wx.request({
          url: (app.globalData.apiBase || config.apiBase) + '/api/v1/customer/auth/wx-login',
          method: 'POST',
          data: { code: loginRes.code },
          header: {
            'Content-Type': 'application/json',
            'X-Tenant-ID': app.globalData.tenantId || '',
          },
          success: function (res) {
            if (res.data && res.data.ok) {
              var data = res.data.data;
              // 缓存 token
              wx.setStorageSync('tx_token', data.token || '');
              wx.setStorageSync('tx_customer_id', data.customer_id || '');
              wx.setStorageSync('tx_open_id', data.open_id || '');
              // 写入全局
              app.globalData.openId = data.open_id || '';
              app.globalData.customerId = data.customer_id || '';
              app.globalData.token = data.token || '';
              resolve(data);
            } else {
              reject(new Error((res.data && res.data.error && res.data.error.message) || '登录失败'));
            }
          },
          fail: function (err) {
            reject(err);
          },
        });
      },
      fail: function (err) {
        reject(err);
      },
    });
  });
}

/**
 * 获取手机号（需用户授权按钮触发）
 * @param {object} e - getPhoneNumber 事件对象
 * @returns {Promise<{phone: string}>}
 */
function bindPhone(e) {
  return new Promise(function (resolve, reject) {
    if (!e.detail.code) {
      reject(new Error('用户拒绝授权手机号'));
      return;
    }
    var app = getApp();
    wx.request({
      url: (app.globalData.apiBase || config.apiBase) + '/api/v1/customer/auth/bind-phone',
      method: 'POST',
      data: {
        code: e.detail.code,
        customer_id: getCustomerId(),
      },
      header: {
        'Content-Type': 'application/json',
        'X-Tenant-ID': app.globalData.tenantId || '',
        'Authorization': 'Bearer ' + getToken(),
      },
      success: function (res) {
        if (res.data && res.data.ok) {
          resolve(res.data.data);
        } else {
          reject(new Error((res.data && res.data.error && res.data.error.message) || '绑定手机号失败'));
        }
      },
      fail: function (err) {
        reject(err);
      },
    });
  });
}

/**
 * 获取缓存的 token
 */
function getToken() {
  return wx.getStorageSync('tx_token') || '';
}

/**
 * 获取缓存的 customerId
 */
function getCustomerId() {
  return wx.getStorageSync('tx_customer_id') || '';
}

/**
 * 检查是否已登录
 */
function isLoggedIn() {
  return !!getToken();
}

/**
 * 清除登录态
 */
function logout() {
  wx.removeStorageSync('tx_token');
  wx.removeStorageSync('tx_customer_id');
  wx.removeStorageSync('tx_open_id');
  var app = getApp();
  app.globalData.token = '';
  app.globalData.customerId = '';
  app.globalData.openId = '';
}

/**
 * 确保已登录，未登录则自动静默登录
 */
function ensureLogin() {
  if (isLoggedIn()) {
    return Promise.resolve();
  }
  return silentLogin();
}

module.exports = {
  silentLogin: silentLogin,
  bindPhone: bindPhone,
  getToken: getToken,
  getCustomerId: getCustomerId,
  isLoggedIn: isLoggedIn,
  logout: logout,
  ensureLogin: ensureLogin,
};
