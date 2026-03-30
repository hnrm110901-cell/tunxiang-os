// 大厨到家首页 — 选菜 + 选厨师
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    // 厨师列表
    chefs: [],
    loadingChefs: true,
    selectedChefId: '',
    // 菜系筛选
    cuisineTypes: ['全部', '湘菜', '粤菜', '海鲜', '川菜'],
    selectedCuisine: '全部',
    // 菜品选择
    dishes: [
      { dish_id: 'D001', name: '剁椒鱼头', price_fen: 16800, image: '/assets/dish-yutou.jpg', selected: false, quantity: 0 },
      { dish_id: 'D002', name: '清蒸龙虾', price_fen: 28800, image: '/assets/dish-longxia.jpg', selected: false, quantity: 0 },
      { dish_id: 'D003', name: '蒜蓉粉丝蒸扇贝', price_fen: 8800, image: '/assets/dish-shanbei.jpg', selected: false, quantity: 0 },
      { dish_id: 'D004', name: '白灼海虾', price_fen: 12800, image: '/assets/dish-haixia.jpg', selected: false, quantity: 0 },
      { dish_id: 'D005', name: '避风塘炒蟹', price_fen: 19800, image: '/assets/dish-chaoxie.jpg', selected: false, quantity: 0 },
      { dish_id: 'D006', name: '口味虾', price_fen: 13800, image: '/assets/dish-kouweixia.jpg', selected: false, quantity: 0 },
      { dish_id: 'D007', name: '辣椒炒肉', price_fen: 5800, image: '/assets/dish-lajiaochaorou.jpg', selected: false, quantity: 0 },
      { dish_id: 'D008', name: '蒸石斑', price_fen: 32800, image: '/assets/dish-shiban.jpg', selected: false, quantity: 0 },
    ],
    selectedDishCount: 0,
    totalPriceFen: 0,
  },

  onLoad: function () {
    this.loadChefs();
  },

  onShow: function () {
    this.loadChefs();
  },

  onShareAppMessage: function () {
    return { title: '徐记海鲜 · 大厨到家', path: '/pages/chef-at-home/index' };
  },

  loadChefs: function () {
    var self = this;
    var today = self._todayStr();
    var cuisineParam = self.data.selectedCuisine === '全部' ? '' : self.data.selectedCuisine;

    self.setData({ loadingChefs: true });
    api.txRequest('/api/v1/chef-at-home/chefs?date=' + today + '&area=长沙' + (cuisineParam ? '&cuisine_type=' + cuisineParam : ''))
      .then(function (data) {
        self.setData({ chefs: data || [], loadingChefs: false });
      })
      .catch(function (err) {
        console.error('loadChefs failed', err);
        self.setData({ loadingChefs: false });
      });
  },

  selectCuisine: function (e) {
    var type = e.currentTarget.dataset.type;
    this.setData({ selectedCuisine: type });
    this.loadChefs();
  },

  selectChef: function (e) {
    var chefId = e.currentTarget.dataset.id;
    this.setData({ selectedChefId: chefId });
  },

  viewChefProfile: function (e) {
    var chefId = e.currentTarget.dataset.id;
    wx.navigateTo({ url: '/pages/chef-at-home/chef-profile?chef_id=' + chefId });
  },

  addDish: function (e) {
    var index = e.currentTarget.dataset.index;
    var dishes = this.data.dishes;
    dishes[index].quantity += 1;
    dishes[index].selected = true;
    this._updateDishState(dishes);
  },

  removeDish: function (e) {
    var index = e.currentTarget.dataset.index;
    var dishes = this.data.dishes;
    if (dishes[index].quantity > 0) {
      dishes[index].quantity -= 1;
      if (dishes[index].quantity === 0) {
        dishes[index].selected = false;
      }
    }
    this._updateDishState(dishes);
  },

  _updateDishState: function (dishes) {
    var count = 0;
    var total = 0;
    for (var i = 0; i < dishes.length; i++) {
      if (dishes[i].quantity > 0) {
        count += dishes[i].quantity;
        total += dishes[i].price_fen * dishes[i].quantity;
      }
    }
    this.setData({
      dishes: dishes,
      selectedDishCount: count,
      totalPriceFen: total,
    });
  },

  goToBooking: function () {
    var self = this;
    if (!self.data.selectedChefId) {
      wx.showToast({ title: '请选择厨师', icon: 'none' });
      return;
    }
    if (self.data.selectedDishCount === 0) {
      wx.showToast({ title: '请至少选择一道菜', icon: 'none' });
      return;
    }

    // 筛选已选菜品
    var selectedDishes = [];
    for (var i = 0; i < self.data.dishes.length; i++) {
      var d = self.data.dishes[i];
      if (d.quantity > 0) {
        selectedDishes.push({
          dish_id: d.dish_id,
          name: d.name,
          quantity: d.quantity,
          price_fen: d.price_fen,
        });
      }
    }

    // 找到选中厨师信息
    var chef = null;
    for (var j = 0; j < self.data.chefs.length; j++) {
      if (self.data.chefs[j].id === self.data.selectedChefId) {
        chef = self.data.chefs[j];
        break;
      }
    }

    // 存入缓存，传递到预约页
    wx.setStorageSync('chef_at_home_draft', {
      dishes: selectedDishes,
      chef_id: self.data.selectedChefId,
      chef_name: chef ? chef.name : '',
      chef_title: chef ? chef.title : '',
      total_dish_fen: self.data.totalPriceFen,
    });

    wx.navigateTo({ url: '/pages/chef-at-home/booking' });
  },

  _todayStr: function () {
    var now = new Date();
    return now.getFullYear() + '-' +
      String(now.getMonth() + 1).padStart(2, '0') + '-' +
      String(now.getDate()).padStart(2, '0');
  },
});
