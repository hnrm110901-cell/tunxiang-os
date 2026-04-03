/**
 * miniapp-customer 配置文件
 * API 地址、版本号、环境切换
 */

// 环境配置
var ENV = {
  dev: {
    apiBase: 'http://localhost:8000',
    wsBase: 'ws://localhost:8000',
  },
  staging: {
    apiBase: 'https://staging-api.tunxiangos.com',
    wsBase: 'wss://staging-api.tunxiangos.com',
  },
  prod: {
    apiBase: 'https://api.tunxiangos.com',
    wsBase: 'wss://api.tunxiangos.com',
  },
};

// 当前环境（发布前切换为 'prod'）
var CURRENT_ENV = 'prod';

module.exports = {
  // API 基础地址
  apiBase: ENV[CURRENT_ENV].apiBase,
  wsBase: ENV[CURRENT_ENV].wsBase,

  // API 前缀
  apiPrefix: '/api/v1/customer',

  // 版本号
  version: '1.0.0',

  // 小程序 AppId
  appId: '',

  // 品牌配置
  brand: {
    name: '屯象点餐',
    primaryColor: '#FF6B2C',
  },

  // 分页默认值
  pageSize: 20,
};
