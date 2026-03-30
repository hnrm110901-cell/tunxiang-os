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

function fetchDishDetail(dishId) {
  return txRequest('/api/v1/menu/dishes/' + encodeURIComponent(dishId));
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

// ─── 订单(补充) ───

function cancelOrder(orderId) {
  return txRequest('/api/v1/trade/orders/' + encodeURIComponent(orderId) + '/cancel', 'POST');
}

// ─── 支付 ───

function createPayment(orderId, method, amountFen) {
  return txRequest('/api/v1/trade/orders/' + encodeURIComponent(orderId) + '/payments', 'POST', {
    method: method,
    amount_fen: amountFen,
  });
}

function queryPaymentStatus(orderId) {
  return txRequest('/api/v1/trade/orders/' + encodeURIComponent(orderId) + '/payment-status');
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

function redeemCoupon(couponCode) {
  var customerId = wx.getStorageSync('tx_customer_id') || '';
  return txRequest('/api/v1/coupon/redeem', 'POST', {
    customer_id: customerId,
    coupon_code: couponCode,
  });
}

// ─── 评价 ───

function submitFeedback(data) {
  return txRequest('/api/v1/customer/feedback', 'POST', data);
}

function fetchMyFeedbacks(page) {
  var customerId = wx.getStorageSync('tx_customer_id') || '';
  return txRequest('/api/v1/customer/feedback?customer_id=' + encodeURIComponent(customerId) + '&page=' + (page || 1));
}

// ─── 扫码点单 ───

function scanOrderInit(tableNo, storeId, customerId) {
  return txRequest('/api/v1/scan-order/init', 'POST', {
    table_no: tableNo,
    store_id: storeId || getApp().globalData.storeId,
    customer_id: customerId || wx.getStorageSync('tx_customer_id') || '',
  });
}

function scanOrderAddItem(orderId, dishId, qty, notes) {
  return txRequest('/api/v1/scan-order/add-item', 'POST', {
    order_id: orderId,
    dish_id: dishId,
    qty: qty || 1,
    notes: notes || '',
  });
}

function scanOrderSubmit(orderId) {
  return txRequest('/api/v1/scan-order/submit', 'POST', {
    order_id: orderId,
  });
}

function scanOrderStatus(orderId) {
  return txRequest('/api/v1/scan-order/status/' + encodeURIComponent(orderId));
}

// ─── 扫码点餐（扩展） ───

function scanOrderCreate(storeId, tableId, items, customerId) {
  return txRequest('/api/v1/scan-order/create', 'POST', {
    store_id: storeId || getApp().globalData.storeId,
    table_id: tableId,
    items: items,
    customer_id: customerId || wx.getStorageSync('tx_customer_id') || '',
  });
}

function scanOrderAddItems(orderId, items) {
  return txRequest('/api/v1/scan-order/add-items', 'POST', {
    order_id: orderId,
    items: items,
  });
}

function scanOrderTableOrder(storeId, tableId) {
  return txRequest('/api/v1/scan-order/table-order?store_id=' +
    encodeURIComponent(storeId || getApp().globalData.storeId) +
    '&table_id=' + encodeURIComponent(tableId));
}

function scanOrderCheckout(orderId) {
  return txRequest('/api/v1/scan-order/checkout', 'POST', {
    order_id: orderId,
  });
}

// ─── 自助点餐引擎 ───

function fetchRecommendations(storeId, customerId, partySize) {
  return txRequest('/api/v1/self-order/recommend', 'POST', {
    store_id: storeId || getApp().globalData.storeId,
    customer_id: customerId || wx.getStorageSync('tx_customer_id') || '',
    party_size: partySize || 1,
    hour: new Date().getHours(),
  });
}

function fetchAddonSuggestions(currentTotalFen, thresholdFen, candidateDishes) {
  return txRequest('/api/v1/self-order/addon-suggest', 'POST', {
    current_total_fen: currentTotalFen,
    threshold_fen: thresholdFen,
    candidate_dishes: candidateDishes,
  });
}

function splitBillEvenly(totalFen, numPeople) {
  return txRequest('/api/v1/self-order/aa-split-even', 'POST', {
    total_fen: totalFen,
    num_people: numPeople,
  });
}

function splitBillByItems(items, assignments) {
  return txRequest('/api/v1/self-order/aa-split-items', 'POST', {
    items: items,
    assignments: assignments,
  });
}

function fetchCookingProgress(orderStatus, acceptedAt, estimatedMinutes) {
  return txRequest('/api/v1/self-order/cooking-progress', 'POST', {
    order_status: orderStatus,
    accepted_at: acceptedAt || null,
    estimated_minutes: estimatedMinutes || 15,
  });
}

function rushOrder(orderId) {
  return txRequest('/api/v1/self-order/rush-order', 'POST', {
    order_id: orderId,
    customer_id: wx.getStorageSync('tx_customer_id') || '',
  });
}

function appendOrderItems(orderId, items) {
  return txRequest('/api/v1/self-order/append-items', 'POST', {
    order_id: orderId,
    items: items,
  });
}

// ─── 社交裂变 ───

function createGroupOrder(storeId, tableNo) {
  return txRequest('/api/v1/social/group-order/create', 'POST', {
    store_id: storeId || getApp().globalData.storeId,
    table_no: tableNo || '',
  });
}

function joinGroupOrder(groupId, inviteCode) {
  return txRequest('/api/v1/social/group-order/join', 'POST', {
    group_id: groupId,
    invite_code: inviteCode,
  });
}

function getGroupOrderSummary(groupId) {
  return txRequest('/api/v1/social/group-order/' + encodeURIComponent(groupId) + '/summary');
}

function createGift(giftType, amountFen, dishIds, message) {
  return txRequest('/api/v1/social/gift/create', 'POST', {
    gift_type: giftType,
    amount_fen: amountFen || 0,
    dish_ids: dishIds || [],
    message: message || '',
  });
}

function claimGift(shareCode) {
  return txRequest('/api/v1/social/gift/claim', 'POST', {
    share_code: shareCode,
  });
}

function generateReferralLink() {
  return txRequest('/api/v1/social/referral/generate', 'POST', {});
}

// ─── 积分商城 ───

function fetchMallItems(category, page) {
  var url = '/api/v1/points-mall/items?page=' + (page || 1);
  if (category) url += '&category=' + encodeURIComponent(category);
  return txRequest(url);
}

function redeemMallItem(itemId, quantity) {
  return txRequest('/api/v1/points-mall/redeem', 'POST', {
    item_id: itemId,
    quantity: quantity || 1,
  });
}

function fetchMyRedemptions(page) {
  return txRequest('/api/v1/points-mall/my-redemptions?page=' + (page || 1));
}

function fetchAchievements() {
  return txRequest('/api/v1/points-mall/achievements');
}

// ─── 虚拟排队 ───

function takeVirtualQueue(storeId, guestRange, phone) {
  return txRequest('/api/v1/queue/virtual-take', 'POST', {
    store_id: storeId || getApp().globalData.storeId,
    customer_id: wx.getStorageSync('tx_customer_id') || '',
    guest_range: guestRange,
    phone: phone || '',
    is_virtual: true,
  });
}

function fetchQueueEstimate(storeId, guestRange) {
  return txRequest('/api/v1/queue/estimate?store_id=' +
    encodeURIComponent(storeId || getApp().globalData.storeId) +
    '&guest_range=' + encodeURIComponent(guestRange));
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
  getStores: fetchNearbyStores,
  getStoreDetail: fetchStoreDetail,
  // 菜单
  fetchCategories: fetchCategories,
  fetchDishes: fetchDishes,
  fetchDishDetail: fetchDishDetail,
  getCategories: fetchCategories,
  getDishes: fetchDishes,
  getDishDetail: fetchDishDetail,
  // 订单
  createOrder: createOrder,
  fetchOrderDetail: fetchOrderDetail,
  fetchMyOrders: fetchMyOrders,
  cancelOrder: cancelOrder,
  getOrders: fetchMyOrders,
  getOrderDetail: fetchOrderDetail,
  // 支付
  createPayment: createPayment,
  queryPaymentStatus: queryPaymentStatus,
  // 排队
  fetchQueueSummary: fetchQueueSummary,
  takeQueue: takeQueue,
  fetchMyTicket: fetchMyTicket,
  cancelQueueTicket: cancelQueueTicket,
  getQueueStatus: fetchQueueSummary,
  takeNumber: takeQueue,
  cancelQueue: cancelQueueTicket,
  // 预订
  createBooking: createBooking,
  fetchBookings: fetchBookings,
  cancelBooking: cancelBooking,
  createReservation: createBooking,
  getReservations: fetchBookings,
  cancelReservation: cancelBooking,
  // 会员
  fetchMemberProfile: fetchMemberProfile,
  fetchPointsLog: fetchPointsLog,
  fetchBalanceLog: fetchBalanceLog,
  getMemberInfo: fetchMemberProfile,
  getPointsHistory: fetchPointsLog,
  getBalanceHistory: fetchBalanceLog,
  // 优惠券
  fetchCoupons: fetchCoupons,
  redeemCoupon: redeemCoupon,
  getCoupons: fetchCoupons,
  // 评价
  submitFeedback: submitFeedback,
  fetchMyFeedbacks: fetchMyFeedbacks,
  getMyFeedbacks: fetchMyFeedbacks,
  // 扫码点单
  scanOrderInit: scanOrderInit,
  scanOrderAddItem: scanOrderAddItem,
  scanOrderSubmit: scanOrderSubmit,
  scanOrderStatus: scanOrderStatus,
  // 扫码点餐（扩展）
  scanOrderCreate: scanOrderCreate,
  scanOrderAddItems: scanOrderAddItems,
  scanOrderTableOrder: scanOrderTableOrder,
  scanOrderCheckout: scanOrderCheckout,
  // 企业团餐
  fetchCorporateAccount: fetchCorporateAccount,
  fetchCorporateRecords: fetchCorporateRecords,
  submitMealBooking: submitMealBooking,
  // 自助点餐引擎
  fetchRecommendations: fetchRecommendations,
  fetchAddonSuggestions: fetchAddonSuggestions,
  splitBillEvenly: splitBillEvenly,
  splitBillByItems: splitBillByItems,
  fetchCookingProgress: fetchCookingProgress,
  rushOrder: rushOrder,
  appendOrderItems: appendOrderItems,
  // 社交裂变
  createGroupOrder: createGroupOrder,
  joinGroupOrder: joinGroupOrder,
  getGroupOrderSummary: getGroupOrderSummary,
  createGift: createGift,
  claimGift: claimGift,
  generateReferralLink: generateReferralLink,
  // 积分商城
  fetchMallItems: fetchMallItems,
  redeemMallItem: redeemMallItem,
  fetchMyRedemptions: fetchMyRedemptions,
  fetchAchievements: fetchAchievements,
  // 虚拟排队
  takeVirtualQueue: takeVirtualQueue,
  fetchQueueEstimate: fetchQueueEstimate,
};
