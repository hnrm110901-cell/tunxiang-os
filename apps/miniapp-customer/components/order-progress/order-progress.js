/**
 * Order Progress Component -- Domino's-style 4-step cooking tracker
 * Steps: Accepted -> Cooking -> Plating -> Ready
 */
Component({
  properties: {
    /** Current step index (1-4), 0 = not started */
    currentStep: {
      type: Number,
      value: 0,
    },
    /** Array of step objects: [{step, key, label, state}] */
    steps: {
      type: Array,
      value: [],
    },
    /** Remaining seconds until estimated ready */
    remainingSeconds: {
      type: Number,
      value: 0,
    },
    /** ISO string of estimated ready time */
    estimatedReadyAt: {
      type: String,
      value: '',
    },
    /** Whether to show the rush (催菜) button */
    showRush: {
      type: Boolean,
      value: true,
    },
    /** Name of the dish currently being prepared */
    currentDish: {
      type: String,
      value: '',
    },
  },

  data: {
    countdownText: '',
    _timer: null,
    _remaining: 0,
  },

  lifetimes: {
    attached: function () {
      this._startCountdown();
    },
    detached: function () {
      this._stopCountdown();
    },
  },

  observers: {
    remainingSeconds: function (val) {
      this.setData({ _remaining: val });
      this._startCountdown();
    },
  },

  methods: {
    _startCountdown: function () {
      this._stopCountdown();
      var self = this;
      self._formatCountdown();

      var timer = setInterval(function () {
        var remaining = self.data._remaining;
        if (remaining <= 0) {
          self._stopCountdown();
          self.setData({ countdownText: '即将出餐' });
          return;
        }
        self.setData({ _remaining: remaining - 1 });
        self._formatCountdown();
      }, 1000);

      self.setData({ _timer: timer });
    },

    _stopCountdown: function () {
      if (this.data._timer) {
        clearInterval(this.data._timer);
        this.setData({ _timer: null });
      }
    },

    _formatCountdown: function () {
      var secs = this.data._remaining;
      if (secs <= 0) {
        this.setData({ countdownText: '即将出餐' });
        return;
      }
      var mins = Math.floor(secs / 60);
      var s = secs % 60;
      this.setData({
        countdownText: '预计 ' + mins + ':' + (s < 10 ? '0' : '') + s + ' 后出餐',
      });
    },

    onRush: function () {
      this.triggerEvent('rush');
    },
  },
});
