/**
 * miniapp-customer 统一 API 客户端
 * 所有页面通过此文件调用后端，自动处理 token 和租户隔离。
 */

var config = require('./config.js');

/**
 * 统一请求封装
 * - 自动带 token (wx.getStorageSync)
 * - 自动带 X-Tenant-ID
 * - 请求/响应拦截
 * - 统一错误处理
 *
 * @param {string} path - API 路径，如 /menu/dishes
 * @param {string} [method] - HTTP 方法，默认 GET
 * @param {object} [data] - 请求体数据
 * @returns {Promise<any>} 响应中的 data 字段
 */
function txRequest(path, method, data) {
  if (method === undefined) method = 'GET';
  if (data === undefined) data = {};

  var app = getApp();
  var baseUrl = app.globalData.apiBase || config.apiBase;
  var token = wx.getStorageSync('tx_token') || '';

  // 如果路径不以 / 开头，自动加上 customer API 前缀
  var fullPath = path;
  if (path.indexOf('/api/') !== 0) {
    fullPath = config.apiPrefix + path;
  }

  return new Promise(function (resolve, reject) {
    wx.request({
      url: baseUrl + fullPath,
      method: method,
      data: data,
      header: {
        'X-Tenant-ID': app.globalData.tenantId || '',
        'Content-Type': 'application/json',
        'Authorization': token ? 'Bearer ' + token : '',
      },
      success: function (res) {
        // 401 未授权：清除 token，跳登录
        if (res.statusCode === 401) {
          wx.removeStorageSync('tx_token');
          wx.removeStorageSync('tx_customer_id');
          reject(new Error('登录已过期，请重新登录'));
          return;
        }

        if (res.data && res.data.ok) {
          resolve(res.data.data);
        } else {
          var errMsg = (res.data && res.data.error && res.data.error.message) || '请求失败';
          reject(new Error(errMsg));
        }
      },
      fail: function (err) {
        reject(new Error(err.errMsg || '网络错误'));
      },
    });
  });
}

// ─── 门店 ───

function fetchNearbyStores(lat, lng) {
  return txRequest('/api/v1/customer/stores/nearby?lat=' + lat + '&lng=' + lng);
}

function fetchStoreDetail(storeId) {
  return txRequest('/api/v1/customer/stores/' + encodeURIComponent(storeId));
}

// ─── 菜单 ───

function fetchCategories(storeId) {
  return txRequest('/api/v1/menu/categories?store_id=' + encodeURIComponent(storeId));
}

function fetchDishes(storeId, category) {
  var url = '/api/v1/menu/dishes?store_id=' + encodeURIComponent(storeId);
  if (category) url += '&category=' + encodeURIComponent(category);
  return txRequest(url);
}

// ─── 订单 ───

function createOrder(data) {
  return txRequest('/api/v1/trade/orders', 'POST', data);
}

function fetchOrderDetail(orderId) {
  return txRequest('/api/v1/trade/orders/' + encodeURIComponent(orderId));
}

function fetchMyOrders(page, size) {
  var customerId = wx.getStorageSync('tx_customer_id') || '';
  return txRequest('/api/v1/trade/orders?customer_id=' + encodeURIComponent(customerId) + '&page=' + (page || 1) + '&size=' + (size || 20));
}

// ─── 支付 ───

function createPayment(orderId, method, amountFen) {
  return txRequest('/api/v1/trade/orders/' + encodeURIComponent(orderId) + '/payments', 'POST', {
    method: method,
    amount_fen: amountFen,
  });
}

// ─── 排队 ───

function fetchQueueSummary(storeId) {
  return txRequest('/api/v1/queue/summary?store_id=' + encodeURIComponent(storeId));
}

function takeQueue(storeId, guestRange) {
  return txRequest('/api/v1/queue/take', 'POST', {
    store_id: storeId,
    customer_id: wx.getStorageSync('tx_customer_id') || '',
    guest_range: guestRange,
  });
}

function fetchMyTicket(storeId) {
  return txRequest('/api/v1/queue/my-ticket?store_id=' + encodeURIComponent(storeId) + '&customer_id=' + encodeURIComponent(wx.getStorageSync('tx_customer_id') || ''));
}

function cancelQueueTicket(ticketId) {
  return txRequest('/api/v1/queue/' + encodeURIComponent(ticketId) + '/cancel', 'POST');
}

// ─── 预订 ───

function createBooking(data) {
  return txRequest('/api/v1/booking/create', 'POST', data);
}

function fetchBookings() {
  var customerId = wx.getStorageSync('tx_customer_id') || '';
  var app = getApp();
  return txRequest('/api/v1/booking/list?store_id=' + encodeURIComponent(app.globalData.storeId) + '&customer_id=' + encodeURIComponent(customerId));
}

function cancelBooking(bookingId) {
  return txRequest('/api/v1/booking/' + encodeURIComponent(bookingId) + '/cancel', 'POST');
}

// ─── 会员 ───

function fetchMemberProfile() {
  var customerId = wx.getStorageSync('tx_customer_id') || '';
  return txRequest('/api/v1/member/customers/' + encodeURIComponent(customerId));
}

function fetchPointsLog(page) {
  var customerId = wx.getStorageSync('tx_customer_id') || '';
  return txRequest('/api/v1/member/customers/' + encodeURIComponent(customerId) + '/points?page=' + (page || 1));
}

function fetchBalanceLog(page) {
  var customerId = wx.getStorageSync('tx_customer_id') || '';
  return txRequest('/api/v1/member/customers/' + encodeURIComponent(customerId) + '/balance?page=' + (page || 1));
}

// ─── 优惠券 ───

function fetchCoupons(status) {
  var customerId = wx.getStorageSync('tx_customer_id') || '';
  return txRequest('/api/v1/coupon/my-list?customer_id=' + encodeURIComponent(customerId) + '&status=' + encodeURIComponent(status || 'available'));
}

// ─── 评价 ───

function submitFeedback(data) {
  return txRequest('/api/v1/customer/feedback', 'POST', data);
}

function fetchMyFeedbacks(page) {
  var customerId = wx.getStorageSync('tx_customer_id') || '';
  return txRequest('/api/v1/customer/feedback?customer_id=' + encodeURIComponent(customerId) + '&page=' + (page || 1));
}

// ─── 企业团餐 ───

function fetchCorporateAccount() {
  var customerId = wx.getStorageSync('tx_customer_id') || '';
  return txRequest('/api/v1/corporate/account?customer_id=' + encodeURIComponent(customerId));
}

function fetchCorporateRecords(page) {
  var customerId = wx.getStorageSync('tx_customer_id') || '';
  return txRequest('/api/v1/corporate/records?customer_id=' + encodeURIComponent(customerId) + '&page=' + (page || 1) + '&size=20');
}

function submitMealBooking(data) {
  return txRequest('/api/v1/corporate/meal-booking', 'POST', data);
}

module.exports = {
  txRequest: txRequest,
  // 门店
  fetchNearbyStores: fetchNearbyStores,
  fetchStoreDetail: fetchStoreDetail,
  // 菜单
  fetchCategories: fetchCategories,
  fetchDishes: fetchDishes,
  // 订单
  createOrder: createOrder,
  fetchOrderDetail: fetchOrderDetail,
  fetchMyOrders: fetchMyOrders,
  // 支付
  createPayment: createPayment,
  // 排队
  fetchQueueSummary: fetchQueueSummary,
  takeQueue: takeQueue,
  fetchMyTicket: fetchMyTicket,
  cancelQueueTicket: cancelQueueTicket,
  // 预订
  createBooking: createBooking,
  fetchBookings: fetchBookings,
  cancelBooking: cancelBooking,
  // 会员
  fetchMemberProfile: fetchMemberProfile,
  fetchPointsLog: fetchPointsLog,
  fetchBalanceLog: fetchBalanceLog,
  // 优惠券
  fetchCoupons: fetchCoupons,
  // 评价
  submitFeedback: submitFeedback,
  fetchMyFeedbacks: fetchMyFeedbacks,
  // 企业团餐
  fetchCorporateAccount: fetchCorporateAccount,
  fetchCorporateRecords: fetchCorporateRecords,
  submitMealBooking: submitMealBooking,
};
