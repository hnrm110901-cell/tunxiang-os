var app = getApp();

Page({
  data: {
    animating: true,
    stampCount: 1,
    currentStamps: 0,
    totalSlots: 9,
    nextPrizeName: '',
    nextPrizeGap: 0,
    hasNextPrize: false,
  },

  onLoad: function (options) {
    var self = this;
    var stampCount = parseInt(options.stamp_count) || 1;
    var currentStamps = parseInt(options.current_stamps) || 0;
    var totalSlots = parseInt(options.total_slots) || 9;
    var nextPrizeName = decodeURIComponent(options.next_prize_name || '');
    var nextPrizeGap = parseInt(options.next_prize_gap) || 0;

    self.setData({
      stampCount: stampCount,
      currentStamps: currentStamps,
      totalSlots: totalSlots,
      nextPrizeName: nextPrizeName,
      nextPrizeGap: nextPrizeGap,
      hasNextPrize: nextPrizeGap > 0 && nextPrizeName,
    });

    // 3秒后自动返回
    self._timer = setTimeout(function () {
      self._goBack();
    }, 3000);
  },

  onUnload: function () {
    if (this._timer) {
      clearTimeout(this._timer);
      this._timer = null;
    }
  },

  _goBack: function () {
    wx.navigateBack({ delta: 1 });
  },

  onTapBack: function () {
    if (this._timer) {
      clearTimeout(this._timer);
      this._timer = null;
    }
    this._goBack();
  },
});
