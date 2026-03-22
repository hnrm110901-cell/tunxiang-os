// 点餐首页
const app = getApp();

Page({
  data: {
    storeName: '',
    tableNo: '',
    categories: ['推荐', '热菜', '凉菜', '主食', '饮品'],
    activeCategory: '推荐',
    dishes: [],
    cartItems: [],
    cartCount: 0,
    cartTotal: 0,
  },

  onLoad(options) {
    this.setData({
      tableNo: options.table || '',
      storeName: options.store_name || '屯象点餐',
    });
    this.loadDishes();
  },

  async loadDishes() {
    try {
      const res = await wx.request({
        url: `${app.globalData.apiBase}/api/v1/menu/dishes`,
        data: { store_id: app.globalData.storeId },
        header: { 'X-Tenant-ID': app.globalData.tenantId },
      });
      if (res.data.ok) {
        this.setData({ dishes: res.data.data.items || [] });
      }
    } catch (e) {
      console.error('loadDishes failed', e);
    }
  },

  selectCategory(e) {
    this.setData({ activeCategory: e.currentTarget.dataset.name });
  },

  addToCart(e) {
    const dish = e.currentTarget.dataset.dish;
    const cart = [...this.data.cartItems];
    const existing = cart.find(i => i.id === dish.id);
    if (existing) {
      existing.quantity += 1;
    } else {
      cart.push({ ...dish, quantity: 1 });
    }
    this.setData({
      cartItems: cart,
      cartCount: cart.reduce((s, i) => s + i.quantity, 0),
      cartTotal: cart.reduce((s, i) => s + i.priceFen * i.quantity, 0),
    });
  },

  submitOrder() {
    wx.navigateTo({
      url: `/pages/order/order?items=${encodeURIComponent(JSON.stringify(this.data.cartItems))}`,
    });
  },
});
