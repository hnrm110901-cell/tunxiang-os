/**
 * LazyImage — viewport-aware lazy-loading image component for Taro
 *
 * Shows a solid-color placeholder until the element scrolls into view,
 * then renders the actual <Image> with a 300 ms opacity fade-in.
 * On load error, falls back to a grey placeholder with a camera icon.
 */

import React, { useRef, useState, useEffect } from 'react'
import { View, Image, Text } from '@tarojs/components'
import Taro from '@tarojs/taro'

// ─── Props ────────────────────────────────────────────────────────────────────

export interface LazyImageProps {
  src: string
  /** Width in rpx */
  width: number
  /** Height in rpx */
  height: number
  borderRadius?: number
  /** Background color shown before load; defaults to the app card-bg (#132029) */
  placeholder?: string
  /** Taro Image mode; defaults to 'aspectFill' */
  mode?: string
}

// ─── Component ────────────────────────────────────────────────────────────────

const LazyImage: React.FC<LazyImageProps> = ({
  src,
  width,
  height,
  borderRadius = 0,
  placeholder = '#132029',
  mode = 'aspectFill',
}) => {
  const [inView, setInView]   = useState(false)
  const [loaded, setLoaded]   = useState(false)
  const [errored, setErrored] = useState(false)

  // A stable id so we can look up the node for the intersection observer
  const idRef = useRef(`lazy-img-${Math.random().toString(36).slice(2, 10)}`)

  useEffect(() => {
    // Taro.createIntersectionObserver is only available in mini-program envs.
    // On H5 it may not exist; fall back to showing the image immediately.
    if (typeof Taro.createIntersectionObserver !== 'function') {
      setInView(true)
      return
    }

    let disconnected = false

    // pageContext = undefined means we observe relative to the viewport
    const observer = Taro.createIntersectionObserver(undefined as unknown as Taro.General.IAnyObject, {
      thresholds: [0],
      // start observing 50px before the element enters the viewport
      observeAll: false,
    })

    observer.relativeToViewport({ bottom: 50 }).observe(`#${idRef.current}`, (res) => {
      if (disconnected) return
      if (res.intersectionRatio > 0) {
        setInView(true)
        observer.disconnect()
      }
    })

    return () => {
      disconnected = true
      observer.disconnect()
    }
  }, [])

  const containerStyle: React.CSSProperties = {
    width:        `${width}rpx`,
    height:       `${height}rpx`,
    borderRadius: borderRadius ? `${borderRadius}rpx` : undefined,
    overflow:     'hidden',
    position:     'relative',
    flexShrink:   0,
    background:   placeholder,
  }

  const imageStyle: React.CSSProperties = {
    width:      `${width}rpx`,
    height:     `${height}rpx`,
    display:    'block',
    opacity:    loaded ? 1 : 0,
    transition: 'opacity 300ms ease',
  }

  const errorStyle: React.CSSProperties = {
    width:           `${width}rpx`,
    height:          `${height}rpx`,
    display:         'flex',
    alignItems:      'center',
    justifyContent:  'center',
    background:      '#2A3A42',
    position:        'absolute',
    top:             0,
    left:            0,
  }

  return (
    <View id={idRef.current} style={containerStyle}>
      {/* Actual image — only mounted once in viewport */}
      {inView && !errored && (
        <Image
          src={src}
          mode={mode as Parameters<typeof Image>[0]['mode']}
          style={imageStyle}
          lazyLoad={false}  // we handle laziness ourselves
          onLoad={() => setLoaded(true)}
          onError={() => setErrored(true)}
        />
      )}

      {/* Error fallback */}
      {errored && (
        <View style={errorStyle}>
          <Text style={{ fontSize: '40rpx' }}>📷</Text>
        </View>
      )}
    </View>
  )
}

export default LazyImage
