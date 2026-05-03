/**
 * H5 சுய-ஆர்டர் தமிழ் மொழிபெயர்ப்புகள் (Tamil H5 self-order translations)
 */
import type { zh } from './zh';

export const ta: Record<keyof typeof zh, string> = {
  // ScanEntry
  scanTitle: 'QR குறியீடு ஸ்கேன் செய்து ஆர்டர் செய்',
  scanHint: 'மேஜையில் உள்ள QR குறியீட்டை ஸ்கேன் செய்யவும்',
  scanPermissionDenied: 'ஸ்கேன் செய்ய கேமரா அனுமதி தேவை',
  selectLanguage: 'மொழியைத் தேர்ந்தெடு',
  storeInfo: 'கடை தகவல்',
  tableNo: 'மேஜை எண்',
  startOrder: 'ஆர்டர் செய்யத் தொடங்கு',

  // MenuBrowse
  menuTitle: 'உணவு பட்டியல்',
  search: 'உணவு தேடு',
  voiceSearch: 'குரல் தேடல்',
  recommended: 'உங்களுக்கான பரிந்துரைகள்',
  signature: 'சிறப்பு',
  newDish: 'புதியது',
  seasonal: 'சந்தை விலை',
  soldOut: 'தீர்ந்துவிட்டது',
  spicy1: 'லேசான காரம்',
  spicy2: 'மிதமான காரம்',
  spicy3: 'அதிக காரம்',
  addToCart: 'வண்டியில் சேர்',
  viewCart: 'வண்டியைப் பார்',
  totalItems: '{count} பொருட்கள்',
  aiRecommend: 'AI பரிந்துரை',

  // DishDetail
  traceability: 'உணவு தடமறிதல்',
  origin: 'தோற்றம்',
  supplier: 'சப்ளையர்',
  arrivalDate: 'வந்தடைந்த தேதி',
  nutrition: 'ஊட்டச்சத்து தகவல்',
  calories: 'கலோரிகள்',
  protein: 'புரதம்',
  fat: 'கொழுப்பு',
  allergens: 'ஒவ்வாமை எச்சரிக்கை',
  customize: 'தனிப்பயனாக்கு',
  spicyLevel: 'கார அளவு',
  portion: 'அளவு',
  sideDish: 'துணை உணவு',
  cookMethod: 'சமைக்கும் முறை',

  // Cart
  cartTitle: 'வண்டி',
  cartEmpty: 'வண்டி காலியாக உள்ளது',
  cartEmptyHint: 'சுவையான உணவுகளைத் தேர்ந்தெடுக்கவும்',
  dealRecommend: 'சேர்த்து சேமி',
  aaSplit: 'பில் பகிர்வு',
  aaPeople: '{count} நபர்கள்',
  aaPerPerson: 'ஒரு நபர்',
  remark: 'குறிப்பு',
  remarkPlaceholder: 'ஒவ்வாமை அல்லது சிறப்பு கோரிக்கைகள் இருந்தால் குறிப்பிடவும்...',
  total: 'மொத்தம்',
  submitOrder: 'ஆர்டர் சமர்ப்பி',

  // Checkout
  checkoutTitle: 'செக்அவுட்',
  payMethod: 'செலுத்தும் முறை',
  wechatPay: 'WeChat Pay',
  alipay: 'Alipay',
  unionPay: 'UnionPay',
  coupon: 'கூப்பன்',
  selectCoupon: 'கூப்பன் தேர்ந்தெடு',
  noCoupon: 'கூப்பன் இல்லை',
  memberPrice: 'உறுப்பினர் விலை பயன்படுத்தப்பட்டது',
  discount: 'தள்ளுபடி',
  payNow: 'இப்போது செலுத்து',
  phoneRequired: 'செல்பேசி எண் தேவை',
  phonePlaceholder: 'செல்பேசி எண்ணை உள்ளிடுக',
  getVerifyCode: 'குறியீடு பெற',

  // OrderTrack
  trackTitle: 'ஆர்டர் கண்காணிப்பு',
  stepReceived: 'பெறப்பட்டது',
  stepCooking: 'சமைக்கிறது',
  stepReady: 'தயார்',
  stepPickup: 'எடுக்க தயார்',
  estimatedTime: 'மதிப்பிடப்பட்ட நேரம் {min} நிமிடங்கள்',
  currentDish: 'தற்போது சமைக்கிறது',
  rushOrder: 'அவசரம்',
  rushCooldown: 'காத்திருக்கவும் ({sec} வினாடிகள்)',
  notifyWechat: 'WeChat அறிவிப்பு',
  notifySms: 'SMS அறிவிப்பு',

  // FeedbackPage
  feedbackTitle: 'கருத்து',
  rateDish: 'உணவு மதிப்பீடு',
  rateService: 'சேவை மதிப்பீடு',
  rateEnvironment: 'சூழல் மதிப்பீடு',
  feedbackPlaceholder: 'உங்கள் அனுபவத்தைப் பகிரவும்...',
  uploadPhoto: 'புகைப்படம் பதிவேற்று',
  submitFeedback: 'கருத்து சமர்ப்பி',
  feedbackReward: 'சமர்ப்பித்ததும் {points} புள்ளிகள் பெறுக',

  // PayResult
  payResultSuccess: 'செலுத்தம் வெற்றி',
  payResultFailed: 'செலுத்தம் தோல்வி',
  payResultRetryHint: 'தயவுசெய்து மீண்டும் முயற்சிக்கவும்',
  payResultOrderNo: 'ஆர்டர் எண்',
  payResultAmount: 'செலுத்தப்பட்ட தொகை',
  payResultEstTime: 'மதிப்பிடப்பட்ட நேரம்',
  payResultMinutes: 'நிமிடங்கள்',
  payResultProgress: 'முன்னேற்றம்',
  payResultViewOrder: 'ஆர்டரைப் பார்',
  payResultContinue: 'தொடர்ந்து ஆர்டர் செய்',

  // AddMorePage
  addMoreTitle: 'மேலும் சேர்',
  addMoreExisting: 'இருக்கும்',
  addMoreDishUnit: 'உணவுகள்',
  addMoreBadge: 'புதிய',
  addMoreSubmit: 'ஆர்டரில் சேர்',

  // OrderConfirmPage
  orderConfirmTitle: 'ஆர்டரை உறுதிப்படுத்து',
  orderConfirmItemCount: 'பொருட்கள்',
  orderConfirmItems: 'தேர்ந்தெடுக்கப்பட்ட உணவுகள்',
  orderConfirmDelete: 'நீக்கு',
  orderConfirmPoints: 'புள்ளிகள் மாற்று',
  orderConfirmSubtotal: 'துணை மொத்தம்',
  orderConfirmDiscount: 'தள்ளுபடி',
  orderConfirmPayable: 'செலுத்த வேண்டியது',

  // DemoEntry
  demoMode: 'டெமோ முறை',
  demoWelcome: 'வரவேற்கிறோம்',
  demoLoadingHint: 'உணவு பட்டியலுக்குச் செல்கிறது...',
  cashPay: 'கவுண்டரில் செலுத்து',

  // Common
  back: 'பின்',
  confirm: 'உறுதிப்படுத்து',
  cancel: 'ரத்து',
  loading: 'ஏற்றுகிறது...',
  retry: 'மீண்டும் முயற்சி',
  yuan: 'RM',
};
