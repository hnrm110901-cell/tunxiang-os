var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    tab: 'list',
    activities: [],
    myTeams: [],
    teamDetail: null,
    loading: false,
    joining: false,
  },

  onLoad: function (options) {
    if (options.team_id) {
      this._loadTeamDetail(options.team_id);
      this.setData({ tab: 'detail' });
    } else {
      this._loadActivities();
    }
  },

  onShareAppMessage: function () {
    var detail = this.data.teamDetail;
    if (detail) {
      return {
        title: detail.activity_name + ' - 还差' + (detail.target_size - detail.current_size) + '人成团！',
        path: '/pages/group-buy/index?team_id=' + detail.team_id,
        imageUrl: detail.image_url || '',
      };
    }
    return {
      title: '超值拼团，人多更划算！',
      path: '/pages/group-buy/index',
    };
  },

  switchTab: function (e) {
    var tab = e.currentTarget.dataset.tab;
    this.setData({ tab: tab });
    if (tab === 'list') this._loadActivities();
    if (tab === 'mine') this._loadMyTeams();
  },

  _loadActivities: function () {
    var self = this;
    self.setData({ loading: true });
    api.get('/api/v1/group-buy/activities', { status: 'active' }).then(function (res) {
      self.setData({ activities: res.data.items || [], loading: false });
    }).catch(function () {
      self.setData({ loading: false });
      wx.showToast({ title: '加载失败', icon: 'none' });
    });
  },

  _loadMyTeams: function () {
    var self = this;
    self.setData({ loading: true });
    api.get('/api/v1/group-buy/my-teams').then(function (res) {
      self.setData({ myTeams: res.data.items || [], loading: false });
    }).catch(function () {
      self.setData({ loading: false });
    });
  },

  _loadTeamDetail: function (teamId) {
    var self = this;
    api.get('/api/v1/group-buy/teams/' + teamId).then(function (res) {
      self.setData({ teamDetail: res.data, tab: 'detail' });
    }).catch(function () {
      wx.showToast({ title: '团不存在或已过期', icon: 'none' });
    });
  },

  onCreateTeam: function (e) {
    var activityId = e.currentTarget.dataset.id;
    var self = this;

    wx.showLoading({ title: '正在开团...' });
    api.post('/api/v1/group-buy/teams', { activity_id: activityId }).then(function (res) {
      wx.hideLoading();
      self._loadTeamDetail(res.data.team_id);
    }).catch(function () {
      wx.hideLoading();
      wx.showToast({ title: '开团失败', icon: 'none' });
    });
  },

  onJoinTeam: function () {
    var self = this;
    var detail = self.data.teamDetail;
    if (!detail || self.data.joining) return;

    self.setData({ joining: true });
    api.post('/api/v1/group-buy/teams/' + detail.team_id + '/join', {}).then(function (res) {
      self.setData({ joining: false });
      wx.showToast({ title: '加入成功！', icon: 'success' });
      self._loadTeamDetail(detail.team_id);
    }).catch(function (err) {
      self.setData({ joining: false });
      var msg = (err && err.message) || '加入失败';
      wx.showToast({ title: msg, icon: 'none' });
    });
  },

  onShareTeam: function () {
    // triggers onShareAppMessage
  },

  goBack: function () {
    this.setData({ tab: 'list', teamDetail: null });
    this._loadActivities();
  },

  formatFen: function (fen) {
    return '¥' + (fen / 100).toFixed(2);
  },
});
