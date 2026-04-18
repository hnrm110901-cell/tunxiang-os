export default defineAppConfig({
  pages: [
    'pages/index/index',
    'pages/menu/index',
    'pages/order/index',
    'pages/mine/index',
    'pages/login/index',
    'pages/error/index',
  ],
  subPackages: [
    {
      root: 'subpages/order-flow',
      pages: [
        'cart/index',
        'checkout/index',
        'pay-result/index',
        'scan-order/index',
        'payment/index',
        'refund/index',
      ],
    },
    {
      root: 'subpages/order-detail',
      pages: [
        'detail/index',
        'track/index',
        'review/index',
        'invoice/index',
      ],
    },
    {
      root: 'subpages/member',
      pages: [
        'level/index',
        'points/index',
        'stored-value/index',
        'preferences/index',
        'subscription/index',
        'taste-profile/index',
        'cross-brand/index',
        'insights/index',
      ],
    },
    {
      root: 'subpages/marketing',
      pages: [
        'coupon/index',
        'stamp-card/index',
        'group-buy/index',
        'points-mall/index',
      ],
    },
    {
      root: 'subpages/queue',
      pages: [
        'index/index',
      ],
    },
    {
      root: 'subpages/reservation',
      pages: [
        'index/index',
      ],
    },
    {
      root: 'subpages/special',
      pages: [
        'chef-at-home/index',
        'corporate/index',
        'banquet/index',
        'retail-mall/index',
      ],
    },
    {
      root: 'subpages/social',
      pages: [
        'invite/index',
        'share/index',
        'gift-card/index',
        'group-order/index',
      ],
    },
    // ─── Wave 1C: 已开发未注册分包 ───
    {
      root: 'subpages/address',
      pages: ['index'],
    },
    {
      root: 'subpages/city-picker',
      pages: ['index'],
    },
    {
      root: 'subpages/dish-detail',
      pages: ['index'],
    },
    {
      root: 'subpages/feedback',
      pages: ['index'],
    },
    {
      root: 'subpages/search',
      pages: ['index'],
    },
    {
      root: 'subpages/settings',
      pages: ['index'],
    },
    {
      root: 'subpages/takeaway',
      pages: ['index'],
    },
    {
      root: 'subpages/retail-mall',
      pages: ['index'],
    },
    // ─── 体验创新模块 ───
    {
      root: 'subpages/queue-game',
      pages: ['index'],
    },
    {
      root: 'subpages/review-reward',
      pages: ['index'],
    },
    {
      root: 'subpages/family-mode',
      pages: ['index'],
    },
    // ─── Wave 1A/1B: 集团化+预点餐 ───
    {
      root: 'subpages/brand-picker',
      pages: ['index'],
    },
    {
      root: 'subpages/pre-order',
      pages: ['index'],
    },
  ],
  tabBar: {
    color: '#9EB5C0',
    selectedColor: '#FF6B35',
    backgroundColor: '#0B1A20',
    borderStyle: 'black',
    list: [
      {
        pagePath: 'pages/index/index',
        text: '首页',
        iconPath: 'assets/tabbar/home.png',
        selectedIconPath: 'assets/tabbar/home-active.png',
      },
      {
        pagePath: 'pages/menu/index',
        text: '菜单',
        iconPath: 'assets/tabbar/menu.png',
        selectedIconPath: 'assets/tabbar/menu-active.png',
      },
      {
        pagePath: 'pages/order/index',
        text: '订单',
        iconPath: 'assets/tabbar/order.png',
        selectedIconPath: 'assets/tabbar/order-active.png',
      },
      {
        pagePath: 'pages/mine/index',
        text: '我的',
        iconPath: 'assets/tabbar/mine.png',
        selectedIconPath: 'assets/tabbar/mine-active.png',
      },
    ],
  },
  preloadRule: {
    'pages/index/index': {
      network: 'all',
      packages: ['src/subpages/order-flow', 'src/subpages/order-detail'],
    },
    'pages/menu/index': {
      network: 'all',
      packages: ['src/subpages/order-flow'],
    },
    'pages/mine/index': {
      network: 'wifi',
      packages: ['src/subpages/member', 'src/subpages/marketing'],
    },
  },
  permission: {
    'scope.userLocation': {
      desc: '用于推荐附近门店',
    },
  },
  requiredPrivateInfos: ['getLocation'],
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#0B1A20',
    navigationBarTitleText: '屯象OS',
    navigationBarTextStyle: 'white',
    backgroundColor: '#0B1A20',
  },
})
