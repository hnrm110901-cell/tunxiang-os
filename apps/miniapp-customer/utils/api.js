/**
 * miniapp-customer 统一 API 客户端
 * 微信小程序顾客端所有页面通过此文件调用后端。
 */

const app = getApp();

/**
 * 统一请求封装，基于 wx.request。
 * @param {string} path - API 路径，如 /api/v1/menu/dishes
 * @param {string} method - HTTP 方法，默认 GET
 * @param {object} data - 请求体数据
 * @returns {Promise<any>} 响应中的 data 字段
 */
function txRequest(path, method, data) {
  if (method === undefined) method = 'GET';
  if (data === undefined) data = {};

  return new Promise(function (resolve, reject) {
    wx.request({
      url: (app.globalData.apiBase || '') + path,
      method: method,
      data: data,
      header: {
        'X-Tenant-ID': app.globalData.tenantId || '',
        'Content-Type': 'application/json',
      },
      success: function (res) {
        if (res.data && res.data.ok) {
          resolve(res.data.data);
        } else {
          var errMsg = (res.data && res.data.error && res.data.error.message) || 'API Error';
          reject(new Error(errMsg));
        }
      },
      fail: function (err) {
        reject(err);
      },
    });
  });
}

/**
 * 获取菜品列表
 */
function fetchDishes(storeId) {
  return txRequest('/api/v1/menu/dishes?store_id=' + encodeURIComponent(storeId));
}

/**
 * 创建订单
 */
function createOrder(storeId, items) {
  return txRequest('/api/v1/trade/orders', 'POST', {
    store_id: storeId,
    items: items,
  });
}

/**
 * 获取预订列表
 */
function fetchBookings(customerId) {
  return txRequest('/api/v1/trade/reservations?customer_id=' + encodeURIComponent(customerId));
}

/**
 * 创建预订
 */
function createBooking(data) {
  return txRequest('/api/v1/trade/reservations', 'POST', data);
}

/**
 * 获取排队状态
 */
function fetchQueueStatus(storeId) {
  return txRequest('/api/v1/trade/queue?store_id=' + encodeURIComponent(storeId));
}

/**
 * 取号排队
 */
function takeQueue(storeId, count) {
  return txRequest('/api/v1/trade/queue/take', 'POST', {
    store_id: storeId,
    guest_count: count,
  });
}

/**
 * 获取优惠券列表
 */
function fetchCoupons(customerId) {
  return txRequest('/api/v1/member/coupons?customer_id=' + encodeURIComponent(customerId));
}

/**
 * 获取会员信息
 */
function fetchMemberProfile(customerId) {
  return txRequest('/api/v1/member/customers/' + encodeURIComponent(customerId));
}

/**
 * 创建支付
 */
function createPayment(orderId, method, amount) {
  return txRequest('/api/v1/trade/payments', 'POST', {
    order_id: orderId,
    method: method,
    amount_fen: amount,
  });
}

module.exports = {
  txRequest: txRequest,
  fetchDishes: fetchDishes,
  createOrder: createOrder,
  fetchBookings: fetchBookings,
  createBooking: createBooking,
  fetchQueueStatus: fetchQueueStatus,
  takeQueue: takeQueue,
  fetchCoupons: fetchCoupons,
  fetchMemberProfile: fetchMemberProfile,
  createPayment: createPayment,
};
