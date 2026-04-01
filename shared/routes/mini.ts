/**
 * G. Mini 顾客侧小程序/H5 — 路由清单
 */
import type { RouteNode } from './types';

export const MINI_ROUTES: RouteNode[] = [
  // ── G1 顾客预订 ──
  { path: '/mini/store-select',       name: '选择门店',   nameEn: 'StoreSelect',       moduleId: 'G1' },
  { path: '/mini/reservation',        name: '预订',       nameEn: 'MiniReservation',   moduleId: 'G1' },
  { path: '/mini/reservation/result', name: '预订结果',   nameEn: 'ReservationResult', moduleId: 'G1' },

  // ── G2 顾客等位 ──
  { path: '/mini/waitlist',           name: '线上排号',   nameEn: 'MiniWaitlist',      moduleId: 'G2' },
  { path: '/mini/waitlist/status',    name: '等位进度',   nameEn: 'WaitlistStatus',    moduleId: 'G2' },

  // ── G3 顾客点单 ──
  { path: '/mini/order/:tableToken',  name: '扫码点单',   nameEn: 'ScanOrder',         moduleId: 'G3' },
  { path: '/mini/menu/:storeId',      name: '菜单浏览',   nameEn: 'MiniMenu',          moduleId: 'G3' },
  { path: '/mini/cart',               name: '购物车',     nameEn: 'Cart',              moduleId: 'G3' },
  { path: '/mini/orders/:orderId',    name: '订单详情',   nameEn: 'MiniOrderDetail',   moduleId: 'G3' },

  // ── G4 顾客结账 ──
  { path: '/mini/pay/:orderId',        name: '支付',       nameEn: 'MiniPay',           moduleId: 'G4' },
  { path: '/mini/pay/:orderId/result', name: '支付结果',   nameEn: 'PayResult',         moduleId: 'G4' },

  // ── G5 会员中心 ──
  { path: '/mini/member',             name: '会员中心',   nameEn: 'MiniMember',        moduleId: 'G5' },
  { path: '/mini/member/coupons',     name: '券包',       nameEn: 'MiniCoupons',       moduleId: 'G5' },
  { path: '/mini/member/points',      name: '积分',       nameEn: 'MiniPoints',        moduleId: 'G5' },
  { path: '/mini/member/history',     name: '消费记录',   nameEn: 'MiniHistory',       moduleId: 'G5' },
];
