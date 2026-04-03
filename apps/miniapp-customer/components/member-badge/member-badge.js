/**
 * 会员等级徽章组件
 * 根据等级显示不同颜色和图标
 */
var LEVEL_MAP = {
  normal: { name: '普通会员', icon: '☆' },
  silver: { name: '白银会员', icon: '★' },
  gold: { name: '黄金会员', icon: '✦' },
  platinum: { name: '铂金会员', icon: '✧' },
  diamond: { name: '钻石会员', icon: '◆' },
};

Component({
  properties: {
    level: {
      type: String,
      value: 'normal',
    },
  },

  data: {
    levelName: '普通会员',
    icon: '☆',
  },

  observers: {
    level: function (val) {
      var info = LEVEL_MAP[val] || LEVEL_MAP.normal;
      this.setData({
        levelName: info.name,
        icon: info.icon,
      });
    },
  },
});
