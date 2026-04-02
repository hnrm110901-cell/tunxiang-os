export default defineAppConfig({
  pages: [
    'pages/index/index',
    'pages/menu/index',
    'pages/order/index',
    'pages/mine/index',
  ],
  subPackages: [
    {
      root: 'subpackages/order-flow',
      pages: [
        'cart/index',
        'checkout/index',
        'pay-result/index',
        'scan-order/index',
      ],
    },
    {
      root: 'subpackages/order-detail',
      pages: [
        'detail/index',
        'track/index',
        'review/index',
      ],
    },
    {
      root: 'subpackages/member',
      pages: [
        'level/index',
        'points/index',
        'stored-value/index',
        'preferences/index',
      ],
    },
    {
      root: 'subpackages/marketing',
      pages: [
        'coupon/index',
        'stamp-card/index',
        'group-buy/index',
        'points-mall/index',
      ],
    },
    {
      root: 'subpackages/queue',
      pages: [
        'index/index',
      ],
    },
    {
      root: 'subpackages/reservation',
      pages: [
        'index/index',
      ],
    },
    {
      root: 'subpackages/special',
      pages: [
        'chef-at-home/index',
        'corporate/index',
        'banquet/index',
        'retail-mall/index',
      ],
    },
    {
      root: 'subpackages/social',
      pages: [
        'invite/index',
        'share/index',
        'gift-card/index',
      ],
    },
  ],
  tabBar: {
    color: '#9EB5C0',
    selectedColor: '#FF6B2C',
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
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#0B1A20',
    navigationBarTitleText: '屯象OS',
    navigationBarTextStyle: 'white',
    backgroundColor: '#0B1A20',
  },
})
