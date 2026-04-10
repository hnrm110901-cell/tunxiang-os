import { create } from 'zustand'

// ─── Types ──────────────────────────────────────────────────────────────────

export type ScanMode = 'dine-in' | 'takeaway' | 'self-order'

export interface BrandInfo {
  id: string
  name: string
  logo_url: string
  theme_color: string
}

interface StoreInfoState {
  // 集团多品牌
  brandId: string
  brandName: string
  brands: BrandInfo[]
  // 门店
  storeId: string
  storeName: string
  tableId: string
  tableNo: string
  scanMode: ScanMode
  isOpen: boolean
  announcements: string[]
}

interface StoreInfoActions {
  setBrand: (brandId: string, brandName: string) => void
  setBrands: (brands: BrandInfo[]) => void
  setStore: (storeId: string, name: string) => void
  setTable: (tableId: string, tableNo: string) => void
  setScanMode: (mode: ScanMode) => void
  setIsOpen: (open: boolean) => void
  setAnnouncements: (announcements: string[]) => void
  loadFromQRCode: (qrData: string) => void
}

type StoreInfoStore = StoreInfoState & StoreInfoActions

// ─── QR Code parser ──────────────────────────────────────────────────────────

/**
 * Parse store_id and table_id from a QR code URL.
 *
 * Supported formats:
 *   1. Full URL with query params:
 *        https://example.com/order?store_id=S01&table_id=T03
 *   2. Miniapp scene string (key=value pairs joined by '&'):
 *        store_id=S01&table_id=T03
 */
function parseQRCode(qrData: string): {
  storeId: string
  tableId: string
  scanMode: ScanMode | null
} {
  let searchString = qrData.trim()

  // If it looks like a URL, extract the query string portion
  try {
    const url = new URL(qrData)
    searchString = url.search.replace(/^\?/, '')
  } catch (_e) {
    // Not a full URL — treat the whole string as a query string
  }

  const params = new URLSearchParams(searchString)

  const storeId = params.get('store_id') ?? ''
  const tableId = params.get('table_id') ?? ''
  const rawMode = params.get('mode') as ScanMode | null

  const validModes: ScanMode[] = ['dine-in', 'takeaway', 'self-order']
  const scanMode =
    rawMode !== null && validModes.includes(rawMode) ? rawMode : null

  return { storeId, tableId, scanMode }
}

// ─── Store ───────────────────────────────────────────────────────────────────

export const useStoreInfo = create<StoreInfoStore>((set) => ({
  // state
  brandId: '',
  brandName: '',
  brands: [],
  storeId: '',
  storeName: '',
  tableId: '',
  tableNo: '',
  scanMode: 'dine-in',
  isOpen: false,
  announcements: [],

  // actions
  setBrand(brandId, brandName) {
    set({ brandId, brandName })
  },
  setBrands(brands) {
    set({ brands })
  },
  setStore(storeId, name) {
    set({ storeId, storeName: name })
  },

  setTable(tableId, tableNo) {
    set({ tableId, tableNo })
  },

  setScanMode(mode) {
    set({ scanMode: mode })
  },

  setIsOpen(open) {
    set({ isOpen: open })
  },

  setAnnouncements(announcements) {
    set({ announcements })
  },

  loadFromQRCode(qrData) {
    const { storeId, tableId, scanMode } = parseQRCode(qrData)

    set((state) => ({
      ...(storeId ? { storeId } : {}),
      ...(tableId ? { tableId } : {}),
      ...(scanMode ? { scanMode } : { scanMode: state.scanMode }),
    }))
  },
}))
