/**
 * 套餐N选M点餐页
 * 路由参数：
 *   combo_id    - 套餐ID
 *   combo_name  - 套餐名称（可选，URL编码）
 *   base_price  - 套餐底价（分，可选）
 *   serve_count - 人数（可选）
 *   table       - 桌号（可选）
 */

var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    // 套餐基础信息
    comboId: '',
    comboName: '套餐',
    basePriceFen: 0,
    basePriceYuan: '0',
    serveCount: 0,
    tableNo: '',

    loading: true,

    // 分组数据：每个group追加 _selectedCount / _isComplete / _itemSelections
    groups: [],
    activeGroupIndex: 0,
    currentGroup: null,
    currentItems: [],  // 当前分组的菜品列表（带_selectedCount）

    // 汇总
    totalSelectedCount: 0,   // 已完成（满足必选）的分组数
    totalRequiredCount: 0,   // 必选分组数
    totalItemCount: 0,       // 已选菜品总件数
    totalPriceFen: 0,
    totalPriceYuan: '0',
    progressPercent: 0,
    isSelectionComplete: false,
    incompleteTip: '',
  },

  onLoad: function (options) {
    var comboId = options.combo_id || '';
    var comboName = options.combo_name ? decodeURIComponent(options.combo_name) : '套餐';
    var basePriceFen = parseInt(options.base_price || '0', 10);
    var serveCount = parseInt(options.serve_count || '0', 10);
    var tableNo = options.table || '';

    var basePriceYuan = (basePriceFen / 100).toFixed(basePriceFen % 100 === 0 ? 0 : 2);

    this.setData({
      comboId: comboId,
      comboName: comboName,
      basePriceFen: basePriceFen,
      basePriceYuan: basePriceYuan,
      serveCount: serveCount,
      tableNo: tableNo,
    });

    wx.setNavigationBarTitle({ title: comboName });

    if (comboId) {
      this._loadGroups(comboId);
    } else {
      this.setData({ loading: false });
      wx.showToast({ title: '套餐ID缺失', icon: 'none' });
    }
  },

  onShareAppMessage: function () {
    return {
      title: this.data.comboName + ' - 套餐点餐',
      path: '/pages/combo-detail/combo-detail?combo_id=' + this.data.comboId,
    };
  },

  // ─── 数据加载 ───

  _loadGroups: function (comboId) {
    var self = this;
    self.setData({ loading: true });

    api.txRequest('/menu/combos/' + comboId + '/groups').then(function (data) {
      var groups = (data.groups || data || []).map(function (g) {
        return Object.assign({}, g, {
          _selectedCount: 0,
          _isComplete: !g.is_required, // 非必选默认算完成
          _itemSelections: {},  // { item_id: count }
        });
      });

      var totalRequiredCount = groups.filter(function (g) { return g.is_required; }).length;

      self.setData({
        groups: groups,
        activeGroupIndex: 0,
        totalRequiredCount: totalRequiredCount,
        loading: false,
      });

      // 加载第一个分组的菜品
      if (groups.length > 0) {
        self._loadGroupItems(0);
      }
    }).catch(function (err) {
      self.setData({ loading: false });
      wx.showToast({ title: err.message || '加载套餐失败', icon: 'none' });
    });
  },

  _loadGroupItems: function (groupIndex) {
    var self = this;
    var group = self.data.groups[groupIndex];
    if (!group) return;

    // 如果已经加载过，直接渲染
    if (group._items) {
      self._renderCurrentGroup(groupIndex);
      return;
    }

    var groupId = group.group_id;
    api.txRequest('/menu/combo-groups/' + groupId + '/items').then(function (data) {
      var items = (data.items || data || []).map(function (item) {
        return Object.assign({}, item, { _selectedCount: 0 });
      });

      // 写入缓存
      var groups = self.data.groups.slice();
      groups[groupIndex] = Object.assign({}, groups[groupIndex], { _items: items });
      self.setData({ groups: groups });
      self._renderCurrentGroup(groupIndex);
    }).catch(function (err) {
      wx.showToast({ title: err.message || '加载菜品失败', icon: 'none' });
      self._renderCurrentGroup(groupIndex);
    });
  },

  _renderCurrentGroup: function (groupIndex) {
    var groups = this.data.groups;
    var group = groups[groupIndex];
    if (!group) return;

    // 把已选数量同步到items
    var selections = group._itemSelections || {};
    var items = (group._items || []).map(function (item) {
      var id = item.item_id || item.id;
      return Object.assign({}, item, { _selectedCount: selections[id] || 0 });
    });

    this.setData({
      activeGroupIndex: groupIndex,
      currentGroup: group,
      currentItems: items,
    });
  },

  // ─── Tab 切换 ───

  switchGroup: function (e) {
    var index = e.currentTarget.dataset.index;
    if (index === this.data.activeGroupIndex && this.data.currentItems.length > 0) return;
    this._loadGroupItems(index);
  },

  // ─── 菜品选择 ───

  onItemAdd: function (e) {
    var item = e.detail.item;
    var itemId = item.item_id || item.id;
    var groupIndex = this.data.activeGroupIndex;
    var groups = this.data.groups.slice();
    var group = Object.assign({}, groups[groupIndex]);
    var selections = Object.assign({}, group._itemSelections || {});

    // 检查是否已达当前分组上限
    if (group._selectedCount >= group.max_select) {
      wx.showToast({ title: '已达该分组最大选择数', icon: 'none' });
      return;
    }

    selections[itemId] = (selections[itemId] || 0) + 1;
    var newGroupSelected = 0;
    Object.keys(selections).forEach(function (k) { newGroupSelected += selections[k]; });

    var isComplete = group.is_required
      ? (newGroupSelected >= group.min_select)
      : true;

    group._itemSelections = selections;
    group._selectedCount = newGroupSelected;
    group._isComplete = isComplete;
    groups[groupIndex] = group;

    this.setData({ groups: groups });
    this._updateCurrentItems(groupIndex, selections);
    this._recalcTotal(groups);
  },

  onItemRemove: function (e) {
    var item = e.detail.item;
    var itemId = item.item_id || item.id;
    var groupIndex = this.data.activeGroupIndex;
    var groups = this.data.groups.slice();
    var group = Object.assign({}, groups[groupIndex]);
    var selections = Object.assign({}, group._itemSelections || {});

    if (!selections[itemId] || selections[itemId] <= 0) return;

    selections[itemId] -= 1;
    if (selections[itemId] === 0) delete selections[itemId];

    var newGroupSelected = 0;
    Object.keys(selections).forEach(function (k) { newGroupSelected += selections[k]; });

    var isComplete = group.is_required
      ? (newGroupSelected >= group.min_select)
      : true;

    group._itemSelections = selections;
    group._selectedCount = newGroupSelected;
    group._isComplete = isComplete;
    groups[groupIndex] = group;

    this.setData({ groups: groups });
    this._updateCurrentItems(groupIndex, selections);
    this._recalcTotal(groups);
  },

  _updateCurrentItems: function (groupIndex, selections) {
    var group = this.data.groups[groupIndex];
    var items = (group._items || []).map(function (item) {
      var id = item.item_id || item.id;
      return Object.assign({}, item, { _selectedCount: selections[id] || 0 });
    });
    this.setData({ currentItems: items });
  },

  // ─── 汇总计算 ───

  _recalcTotal: function (groups) {
    var self = this;
    var totalItemCount = 0;
    var extraPriceFen = 0;
    var completedRequiredCount = 0;
    var totalRequiredCount = 0;

    groups.forEach(function (group) {
      var selections = group._itemSelections || {};
      var items = group._items || [];
      if (group.is_required) {
        totalRequiredCount += 1;
        if (group._isComplete) completedRequiredCount += 1;
      }

      // 计算附加价格
      Object.keys(selections).forEach(function (itemId) {
        var qty = selections[itemId];
        totalItemCount += qty;
        var found = null;
        for (var i = 0; i < items.length; i++) {
          if ((items[i].item_id || items[i].id) === itemId) {
            found = items[i];
            break;
          }
        }
        if (found && found.extra_price_fen > 0) {
          extraPriceFen += found.extra_price_fen * qty;
        }
      });
    });

    var totalPriceFen = self.data.basePriceFen + extraPriceFen;
    var totalPriceYuan = (totalPriceFen / 100).toFixed(totalPriceFen % 100 === 0 ? 0 : 2);
    var isSelectionComplete = completedRequiredCount >= totalRequiredCount;
    var progressPercent = totalRequiredCount > 0
      ? Math.round((completedRequiredCount / totalRequiredCount) * 100)
      : 100;

    // 找出未完成的必选分组
    var incompleteTip = '';
    if (!isSelectionComplete) {
      var incompleteGroups = groups.filter(function (g) {
        return g.is_required && !g._isComplete;
      });
      if (incompleteGroups.length > 0) {
        incompleteTip = '请完成：' + incompleteGroups.map(function (g) {
          return g.group_name + '（至少选' + g.min_select + '个）';
        }).join('、');
      }
    }

    this.setData({
      totalItemCount: totalItemCount,
      totalPriceFen: totalPriceFen,
      totalPriceYuan: totalPriceYuan,
      totalSelectedCount: completedRequiredCount,
      totalRequiredCount: totalRequiredCount,
      isSelectionComplete: isSelectionComplete,
      progressPercent: progressPercent,
      incompleteTip: incompleteTip,
    });
  },

  // ─── 校验与加入购物车 ───

  onAddToCart: function () {
    if (!this.data.isSelectionComplete) {
      wx.showToast({ title: this.data.incompleteTip || '请完成必选分组', icon: 'none' });
      return;
    }

    var self = this;
    // 构造选择数据用于校验
    var groupSelections = self.data.groups.map(function (group) {
      return {
        group_id: group.group_id,
        item_ids: Object.keys(group._itemSelections || {}).filter(function (id) {
          return group._itemSelections[id] > 0;
        }),
        quantities: group._itemSelections || {},
      };
    });

    wx.showLoading({ title: '校验中...' });

    api.txRequest('/menu/combo-groups/validate-selection', 'POST', {
      combo_id: self.data.comboId,
      group_selections: groupSelections,
    }).then(function () {
      wx.hideLoading();
      self._doAddToCart();
    }).catch(function (err) {
      wx.hideLoading();
      // 校验失败也允许加入（降级处理，避免后端未上线时阻断流程）
      wx.showModal({
        title: '提示',
        content: err.message || '校验失败，是否仍加入购物车？',
        success: function (res) {
          if (res.confirm) self._doAddToCart();
        },
      });
    });
  },

  _doAddToCart: function () {
    var self = this;
    var groups = self.data.groups;

    // 汇总所有已选菜品
    var selectedItems = [];
    groups.forEach(function (group) {
      var selections = group._itemSelections || {};
      var items = group._items || [];
      Object.keys(selections).forEach(function (itemId) {
        var qty = selections[itemId];
        if (qty <= 0) return;
        var found = null;
        for (var i = 0; i < items.length; i++) {
          if ((items[i].item_id || items[i].id) === itemId) {
            found = items[i];
            break;
          }
        }
        if (found) {
          selectedItems.push({
            item_id: itemId,
            item_name: found.item_name || found.name,
            group_id: group.group_id,
            group_name: group.group_name,
            quantity: qty,
            extra_price_fen: (found.extra_price_fen || 0) * qty,
          });
        }
      });
    });

    var cartItem = {
      type: 'combo',
      combo_id: self.data.comboId,
      combo_name: self.data.comboName,
      base_price_fen: self.data.basePriceFen,
      total_price_fen: self.data.totalPriceFen,
      serve_count: self.data.serveCount,
      selected_items: selectedItems,
      quantity: 1,
      // 用于购物车显示
      id: 'combo_' + self.data.comboId + '_' + Date.now(),
      name: self.data.comboName,
      priceFen: self.data.totalPriceFen,
      imageUrl: '',
    };

    // 通知购物车（通过全局或事件通道）
    if (app.globalData.cartItems) {
      app.globalData.cartItems.push(cartItem);
    } else {
      app.globalData.cartItems = [cartItem];
    }

    wx.showToast({ title: '已加入购物车', icon: 'success' });
    setTimeout(function () {
      wx.navigateBack();
    }, 800);
  },
});
