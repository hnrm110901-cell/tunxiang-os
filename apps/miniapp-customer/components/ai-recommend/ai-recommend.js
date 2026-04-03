/**
 * AI Recommend Component -- "为你推荐" 4-grid personalized recommendations
 * Based on cart contents and user preferences, shows smart dish pairings.
 */
var api = require('../../utils/api.js');

Component({
  properties: {
    /** Array of recommendation items (external data) */
    items: {
      type: Array,
      value: [],
    },
    /** Currently selected dish IDs in cart, for context-aware recs */
    cartDishIds: {
      type: Array,
      value: [],
    },
    /** Store ID for fetching recommendations */
    storeId: {
      type: String,
      value: '',
    },
    /** Title text */
    title: {
      type: String,
      value: '为你推荐',
    },
    /** Whether to show the AI badge */
    showAiBadge: {
      type: Boolean,
      value: true,
    },
    /** Loading state */
    loading: {
      type: Boolean,
      value: false,
    },
    /** Max items to display */
    maxItems: {
      type: Number,
      value: 4,
    },
    /** Auto-fetch recommendations if storeId provided */
    autoFetch: {
      type: Boolean,
      value: false,
    },
  },

  data: {
    displayItems: [],
    _fetching: false,
  },

  observers: {
    'items': function (val) {
      if (val && val.length > 0) {
        this.setData({ displayItems: val.slice(0, this.data.maxItems) });
      }
    },
    'cartDishIds, storeId': function () {
      if (this.data.autoFetch && this.data.storeId) {
        this._fetchRecommendations();
      }
    },
  },

  lifetimes: {
    attached: function () {
      if (this.data.autoFetch && this.data.storeId) {
        this._fetchRecommendations();
      } else if (this.data.items && this.data.items.length > 0) {
        this.setData({ displayItems: this.data.items.slice(0, this.data.maxItems) });
      }
    },
  },

  methods: {
    _fetchRecommendations: function () {
      if (this.data._fetching) return;
      var self = this;
      self.setData({ _fetching: true });

      var customerId = wx.getStorageSync('tx_customer_id') || '';
      api.fetchRecommendations(self.data.storeId, customerId, 1)
        .then(function (data) {
          var rawItems = data.items || data || [];
          var items = rawItems.slice(0, self.data.maxItems).map(function (item) {
            return {
              dish_id: item.dish_id || item.id,
              dish_name: item.dish_name || item.name,
              name: item.dish_name || item.name,
              image_url: item.image_url || item.imageUrl || '',
              price_fen: item.price_fen || item.priceFen || 0,
              reason: item.reason || item.recommend_reason || '',
              order_count: item.order_count || 0,
            };
          });
          self.setData({ displayItems: items, _fetching: false });
        })
        .catch(function () {
          self.setData({ _fetching: false });
        });
    },

    onTapItem: function (e) {
      var item = e.currentTarget.dataset.item;
      this.triggerEvent('select', { dish: item });
    },

    onTapAdd: function (e) {
      var item = e.currentTarget.dataset.item;
      this.triggerEvent('add', { dish: item });
      // Brief visual feedback
      wx.vibrateShort({ type: 'light' });
    },

    /** One-tap add all recommendations to cart */
    onAddAll: function () {
      var items = this.data.displayItems;
      for (var i = 0; i < items.length; i++) {
        this.triggerEvent('add', { dish: items[i] });
      }
      wx.showToast({ title: '已全部加入', icon: 'success' });
    },
  },
});
