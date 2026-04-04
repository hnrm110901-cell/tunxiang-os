/**
 * @tunxiang/api-types — 屯象OS 统一 TypeScript 类型定义
 *
 * 与 shared/ontology/src/ 下的 Pydantic 模型和 SQLAlchemy 实体一一对应。
 * 所有前端应用从此包引用类型，不手写 interface。
 *
 * 约定：
 * - 金额字段统一 _fen 后缀（分），前端显示时 / 100 转元
 * - 所有 ID 字段用 string（UUID）
 * - 时间字段用 ISO 8601 string
 */

// 通用
export type {
  ApiResponse,
  ApiError,
  PaginatedResponse,
  PaginationParams,
  TenantEntity,
} from './common';

// 枚举
export type {
  OrderStatus,
  StoreStatus,
  InventoryStatus,
  TransactionType,
  ReceivingOrderStatus,
  ReceivingItemStatus,
  TransferOrderStatus,
  EmploymentStatus,
  EmploymentType,
  StorageType,
  RFMLevel,
  OrderType,
  StoreType,
  EmployeeRole,
  PricingMode,
} from './enums';

// 订单
export type {
  Order,
  OrderItem,
  CreateOrderRequest,
  CreateOrderItemRequest,
  UpdateOrderRequest,
  OrderListParams,
  OrderListResponse,
} from './order';

// 菜品
export type {
  Dish,
  DishCategory,
  DishIngredient,
  CreateDishRequest,
  UpdateDishRequest,
  CreateDishCategoryRequest,
  DishListParams,
  DishListResponse,
  DishCategoryListResponse,
} from './dish';

// 会员
export type {
  Member,
  CreateMemberRequest,
  UpdateMemberRequest,
  MemberListParams,
  MemberListResponse,
} from './member';

// 门店
export type {
  Store,
  CreateStoreRequest,
  UpdateStoreRequest,
  StoreListParams,
  StoreListResponse,
} from './store';

// 员工
export type {
  Employee,
  CreateEmployeeRequest,
  UpdateEmployeeRequest,
  EmployeeListParams,
  EmployeeListResponse,
} from './employee';

// 食材
export type {
  IngredientMaster,
  Ingredient,
  IngredientTransaction,
  CreateIngredientMasterRequest,
  CreateIngredientRequest,
  UpdateIngredientRequest,
  CreateIngredientTransactionRequest,
  IngredientListParams,
  IngredientTransactionListParams,
  IngredientMasterListResponse,
  IngredientListResponse,
  IngredientTransactionListResponse,
} from './ingredient';
