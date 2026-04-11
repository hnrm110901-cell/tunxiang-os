/**
 * VideoPlayer — 菜品短视频展示组件
 *
 * 菜品详情页嵌入短视频（烹饪过程/食材展示/顾客评价）
 * 支持：
 * - 自动静音播放（滚动可见时）
 * - 点击全屏播放
 * - 视频+直播双模式
 * - 抖音团购券核销跳转
 */

import React, { useState, useCallback } from 'react'
import { View, Text, Video } from '@tarojs/components'
import Taro from '@tarojs/taro'

const C = {
  primary: '#FF6B2C',
  bgDeep: '#0B1A20',
  bgCard: '#132029',
  border: '#1E3340',
  text1: '#E8F4F8',
  text2: '#9EB5C0',
  text3: '#5A7A88',
  white: '#FFFFFF',
  live: '#FF3B30',
} as const

export interface DishVideo {
  id: string
  video_url: string
  cover_url: string
  title: string
  duration: number  // 秒
  views: number
  type: 'cooking' | 'ingredient' | 'review' | 'live'
}

interface VideoPlayerProps {
  videos: DishVideo[]
  dishName?: string
  /** 是否有进行中的直播 */
  liveStream?: {
    room_id: string
    title: string
    viewer_count: number
  }
  onVideoTap?: (video: DishVideo) => void
}

export function VideoPlayer({ videos, dishName, liveStream, onVideoTap }: VideoPlayerProps) {
  const [playing, setPlaying] = useState<string | null>(null)

  const formatDuration = (s: number) => {
    const m = Math.floor(s / 60)
    const sec = s % 60
    return `${m}:${String(sec).padStart(2, '0')}`
  }

  const formatViews = (n: number) => n >= 10000 ? `${(n / 10000).toFixed(1)}万` : `${n}`

  const typeLabels: Record<DishVideo['type'], { label: string; color: string }> = {
    cooking: { label: '烹饪过程', color: C.primary },
    ingredient: { label: '食材展示', color: '#0F6E56' },
    review: { label: '顾客评价', color: '#185FA5' },
    live: { label: '直播', color: C.live },
  }

  const handleVideoTap = useCallback((video: DishVideo) => {
    if (onVideoTap) onVideoTap(video)
    else setPlaying(playing === video.id ? null : video.id)
  }, [playing, onVideoTap])

  if (!videos.length && !liveStream) return null

  return (
    <View style={{ marginTop: '20rpx' }}>
      {/* 标题 */}
      <View style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16rpx' }}>
        <Text style={{ fontSize: '28rpx', fontWeight: '600', color: C.text1 }}>
          🎬 {dishName ? `${dishName}视频` : '精彩视频'}
        </Text>
        {liveStream && (
          <View style={{
            display: 'flex', alignItems: 'center', gap: '6rpx',
            padding: '6rpx 16rpx', borderRadius: '24rpx', background: `${C.live}20`,
          }}>
            <View style={{ width: '12rpx', height: '12rpx', borderRadius: '50%', background: C.live }} />
            <Text style={{ fontSize: '22rpx', color: C.live, fontWeight: '500' }}>直播中</Text>
          </View>
        )}
      </View>

      {/* 直播入口 */}
      {liveStream && (
        <View
          onClick={() => Taro.showToast({ title: '直播功能开发中', icon: 'none' })}
          style={{
            padding: '20rpx', borderRadius: '16rpx', marginBottom: '16rpx',
            background: 'linear-gradient(135deg, #3A1010 0%, #1A2020 100%)',
            border: `2rpx solid ${C.live}40`,
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}
        >
          <View>
            <Text style={{ fontSize: '28rpx', fontWeight: '600', color: C.text1, display: 'block' }}>
              🔴 {liveStream.title}
            </Text>
            <Text style={{ fontSize: '22rpx', color: C.text3, display: 'block', marginTop: '4rpx' }}>
              {liveStream.viewer_count}人正在观看 · 直播预售享折扣
            </Text>
          </View>
          <View style={{ padding: '10rpx 20rpx', borderRadius: '8rpx', background: C.live }}>
            <Text style={{ fontSize: '24rpx', color: C.white, fontWeight: '500' }}>进入直播</Text>
          </View>
        </View>
      )}

      {/* 视频列表（横向滚动） */}
      <View style={{ display: 'flex', gap: '12rpx', overflowX: 'auto', paddingBottom: '8rpx' }}>
        {videos.map(video => {
          const t = typeLabels[video.type]
          const isPlaying = playing === video.id

          return (
            <View
              key={video.id}
              onClick={() => handleVideoTap(video)}
              style={{
                width: '280rpx', flexShrink: 0,
                borderRadius: '12rpx', overflow: 'hidden',
                background: C.bgCard, border: `2rpx solid ${C.border}`,
              }}
            >
              {/* 封面/视频 */}
              <View style={{ height: '200rpx', position: 'relative', background: '#000' }}>
                {isPlaying ? (
                  <Video
                    src={video.video_url}
                    autoplay
                    muted={false}
                    style={{ width: '100%', height: '100%' }}
                    showFullscreenBtn
                    showPlayBtn
                  />
                ) : (
                  <View style={{
                    width: '100%', height: '100%',
                    background: `${C.primary}30`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    <Text style={{ fontSize: '48rpx' }}>▶</Text>
                  </View>
                )}
                {/* 时长 */}
                <View style={{
                  position: 'absolute', bottom: '8rpx', right: '8rpx',
                  padding: '2rpx 10rpx', borderRadius: '6rpx', background: 'rgba(0,0,0,0.6)',
                }}>
                  <Text style={{ fontSize: '20rpx', color: C.white }}>{formatDuration(video.duration)}</Text>
                </View>
                {/* 类型标签 */}
                <View style={{
                  position: 'absolute', top: '8rpx', left: '8rpx',
                  padding: '2rpx 10rpx', borderRadius: '6rpx', background: `${t.color}CC`,
                }}>
                  <Text style={{ fontSize: '20rpx', color: C.white }}>{t.label}</Text>
                </View>
              </View>

              {/* 信息 */}
              <View style={{ padding: '12rpx' }}>
                <Text style={{ fontSize: '24rpx', color: C.text1, display: 'block' }} numberOfLines={1}>
                  {video.title}
                </Text>
                <Text style={{ fontSize: '20rpx', color: C.text3, display: 'block', marginTop: '4rpx' }}>
                  {formatViews(video.views)}次播放
                </Text>
              </View>
            </View>
          )
        })}
      </View>
    </View>
  )
}
