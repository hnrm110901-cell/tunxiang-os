/**
 * useLocation — LBS store switching
 *
 * Provides:
 *   - getLocation()         → request device GPS coords
 *   - fetchNearbyStores()   → load stores near given coords from backend
 *   - nearbyStores          → list of Store objects
 *   - currentCity           → resolved city name (from coords or manual selection)
 *
 * On permission denied: calls onPermissionDenied (default: show city picker modal)
 * so the user can select a city manually.
 */

import { useState, useCallback } from 'react'
import Taro from '@tarojs/taro'
import { txRequest, TxRequestError } from '../utils/request'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface LatLng {
  lat: number
  lng: number
}

export interface Store {
  storeId: string
  name: string
  address: string
  city: string
  distanceM?: number
  lat: number
  lng: number
  isOpen: boolean
  phone?: string
}

interface NearbyStoresResponse {
  items: Store[]
  city: string
}

interface UseLocationOptions {
  /**
   * Called when the user has denied location permission.
   * Default: show a modal guiding the user to select a city manually.
   */
  onPermissionDenied?: () => void
}

// ─── Constants ────────────────────────────────────────────────────────────────

const NEARBY_RADIUS_M = 10_000 // 10 km default search radius

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useLocation(options: UseLocationOptions = {}) {
  const [nearbyStores, setNearbyStores] = useState<Store[]>([])
  const [currentCity, setCurrentCity] = useState<string>('')
  const [isLocating, setIsLocating] = useState<boolean>(false)
  const [isFetchingStores, setIsFetchingStores] = useState<boolean>(false)
  const [locationError, setLocationError] = useState<string | null>(null)

  const handlePermissionDenied = useCallback((): void => {
    if (options.onPermissionDenied) {
      options.onPermissionDenied()
      return
    }

    // Default: show a modal that lets user pick city manually
    Taro.showModal({
      title: 'Location permission denied',
      content: 'Please allow location access, or select your city manually.',
      confirmText: 'Select city',
      cancelText: 'Cancel',
      success: ({ confirm }) => {
        if (confirm) {
          // Navigate to city-picker page; page may not exist yet during early dev
          Taro.navigateTo({ url: '/pages/city-picker/index' }).catch(() => {
            Taro.showToast({
              title: 'Please enable location in settings',
              icon: 'none',
              duration: 2000,
            }).catch(() => {
              // ignore toast errors
            })
          })
        }
      },
    }).catch(() => {
      // ignore modal errors
    })
  }, [options])

  /**
   * Request device GPS coordinates.
   * Returns { lat, lng } on success.
   * Calls onPermissionDenied and throws on permission refusal.
   */
  const getLocation = useCallback(async (): Promise<LatLng> => {
    setIsLocating(true)
    setLocationError(null)

    try {
      const res = await Taro.getLocation({ type: 'gcj02' })
      return { lat: res.latitude, lng: res.longitude }
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : 'Location unavailable'

      // WeChat encodes permission denial as "getLocation:fail auth deny"
      const isPermDenied =
        msg.toLowerCase().includes('auth') ||
        msg.toLowerCase().includes('deny') ||
        msg.toLowerCase().includes('permission')

      setLocationError(msg)

      if (isPermDenied) {
        handlePermissionDenied()
      } else {
        Taro.showToast({ title: 'Unable to get location', icon: 'none', duration: 2000 }).catch(
          () => {
            // ignore toast errors
          },
        )
      }

      throw new Error(msg)
    } finally {
      setIsLocating(false)
    }
  }, [handlePermissionDenied])

  /**
   * Fetch stores near the given coordinates and update nearbyStores state.
   * Also updates currentCity from the response.
   */
  const fetchNearbyStores = useCallback(
    async (lat: number, lng: number): Promise<void> => {
      setIsFetchingStores(true)

      try {
        const res = await txRequest<NearbyStoresResponse>(
          '/api/v1/stores/nearby',
          'GET',
          {
            lat: String(lat),
            lng: String(lng),
            radius_m: String(NEARBY_RADIUS_M),
          },
        )

        setNearbyStores(res.items)
        if (res.city) {
          setCurrentCity(res.city)
        }
      } catch (err: unknown) {
        const msg =
          err instanceof TxRequestError
            ? err.message
            : err instanceof Error
            ? err.message
            : 'Failed to fetch nearby stores'

        Taro.showToast({ title: msg, icon: 'none', duration: 2000 }).catch(() => {
          // ignore toast errors
        })

        // Re-throw so callers can handle
        throw err
      } finally {
        setIsFetchingStores(false)
      }
    },
    [],
  )

  /**
   * Convenience: get location then immediately fetch nearby stores.
   * Swallows permission-denied — handlePermissionDenied takes over UI.
   */
  const locateAndFetch = useCallback(async (): Promise<void> => {
    let coords: LatLng
    try {
      coords = await getLocation()
    } catch (_e) {
      // handlePermissionDenied already ran inside getLocation
      return
    }
    await fetchNearbyStores(coords.lat, coords.lng)
  }, [getLocation, fetchNearbyStores])

  /**
   * Allow pages to manually override the current city (e.g. after city picker).
   */
  const setCity = useCallback((city: string): void => {
    setCurrentCity(city)
  }, [])

  return {
    getLocation,
    fetchNearbyStores,
    locateAndFetch,
    setCity,
    nearbyStores,
    currentCity,
    isLocating,
    isFetchingStores,
    locationError,
  }
}
