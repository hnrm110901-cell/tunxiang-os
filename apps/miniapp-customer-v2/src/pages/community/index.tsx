/**
 * pages/community/index.tsx — 社区页
 *
 * Sections:
 *   1. Tab bar: 推荐 / 关注 / 附近
 *   2. Banner carousel (3 slides, auto-scroll 3s)
 *   3. 2-column masonry feed (pull-up to load more)
 *   4. FAB publish button
 *
 * Tech: Taro 3 + React 18 + TypeScript
 * Style: inline styles, dark theme (#0B1A20 bg, #132029 card, #FF6B35 primary)
 */

import React, { useState, useEffect, useCallback, useRef } from 'react'
import Taro from '@tarojs/taro'
import { View, Text, Image, ScrollView, Swiper, SwiperItem } from '@tarojs/components'
import { txRequest } from '../../utils/request'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Post {
  id: string
  title: string
  cover_url: string
  tags: string[]
  author_name: string
  author_avatar: string
  like_count: number
  liked: boolean
}

// ─── Brand tokens ─────────────────────────────────────────────────────────────

const C = {
  primary:    '#FF6B35',
  primaryDim: 'rgba(255,107,53,0.15)',
  bg:         '#0B1A20',
  card:       '#132029',
  cardHover:  '#1A2E38',
  border:     '#1E3040',
  text1:      '#E8F4F8',
  text2:      '#9EB5C0',
  text3:      '#5A7A88',
  white:      '#fff',
  heartOn:    '#FF6B35',
  heartOff:   '#5A7A88',
} as const

// ─── Mock / static data ───────────────────────────────────────────────────────

const MOCK_POSTS: Post[] = [
  { id: '1', title: '探店丨徐记海鲜的椒盐虾绝了！',      cover_url: '', tags: ['探店', '海鲜'],    author_name: '美食家小王',    author_avatar: '', like_count: 128, liked: false },
  { id: '2', title: '在家复刻网红菜｜超简单夫妻肺片',     cover_url: '', tags: ['自制', '川菜'],    author_name: '厨房小白',      author_avatar: '', like_count: 89,  liked: true  },
  { id: '3', title: '长沙必吃榜，这10家不能错过',         cover_url: '', tags: ['长沙', '必吃'],    author_name: '长沙吃货联盟',  author_avatar: '', like_count: 356, liked: false },
  { id: '4', title: '私藏！三文鱼的6种吃法',             cover_url: '', tags: ['三文鱼', '日料'],  author_name: 'Foodie同学',   author_avatar: '', like_count: 201, liked: false },
  { id: '5', title: '老长沙人推荐，猪脚饭我吃了10年',    cover_url: '', tags: ['长沙', '猪脚饭'],  author_name: '本地老饕',      author_avatar: '', like_count: 445, liked: true  },
  { id: '6', title: '网红卤鹅翅做法公开',                cover_url: '', tags: ['家常', '卤味'],    author_name: '家常厨娘',      author_avatar: '', like_count: 167, liked: false },
]

const TABS = ['推荐', '关注', '附近'] as const
type TabName = typeof TABS[number]

const BANNERS = [
  { id: '1', title: '新春特惠·首单5折', subtitle: '限时活动', bg: 'linear-gradient(135deg, #1A2E38 0%, #1E3040 100%)' },
  { id: '2', title: '邀请好友享双重奖励', subtitle: '邀一得一', bg: 'linear-gradient(135deg, #1E2A38 0%, #2A1A38 100%)' },
  { id: '3', title: '会员专属·月卡折扣', subtitle: '现在加入', bg: 'linear-gradient(135deg, #1A1E38 0%, #1E2E20 100%)' },
]

// ─── PostCard ─────────────────────────────────────────────────────────────────

interface PostCardProps {
  post: Post
  onTap: () => void
  onLike: (e: React.MouseEvent) => void
}

function PostCard({ post, onTap, onLike }: PostCardProps) {
  return (
    <View
      style={{
        background: C.card,
        borderRadius: '20rpx',
        overflow: 'hidden',
        border: `1rpx solid ${C.border}`,
        marginBottom: '20rpx',
      }}
      onClick={onTap}
    >
      {/* Cover image / placeholder */}
      {post.cover_url ? (
        <Image
          src={post.cover_url}
          style={{ width: '100%', height: '240rpx', display: 'block' }}
          mode="aspectFill"
          lazyLoad
        />
      ) : (
        <View
          style={{
            width: '100%',
            height: '240rpx',
            background: C.cardHover,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Text style={{ fontSize: '52rpx', lineHeight: '1' }}>🍜</Text>
        </View>
      )}

      {/* Content */}
      <View style={{ padding: '16rpx 18rpx 18rpx' }}>
        <Text
          style={{
            color: C.text1,
            fontSize: '26rpx',
            fontWeight: '600',
            lineHeight: '1.45',
            display: 'block',
          }}
          numberOfLines={2}
        >
          {post.title}
        </Text>

        {/* Tags */}
        {post.tags.length > 0 && (
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              flexWrap: 'wrap',
              gap: '8rpx',
              marginTop: '12rpx',
            }}
          >
            {post.tags.slice(0, 2).map((tag) => (
              <View
                key={tag}
                style={{
                  background: C.primaryDim,
                  borderRadius: '6rpx',
                  padding: '4rpx 12rpx',
                }}
              >
                <Text style={{ color: C.primary, fontSize: '20rpx' }}>#{tag}</Text>
              </View>
            ))}
          </View>
        )}

        {/* Author row */}
        <View
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'center',
            marginTop: '16rpx',
            gap: '10rpx',
          }}
        >
          {/* Avatar */}
          <View
            style={{
              width: '40rpx',
              height: '40rpx',
              borderRadius: '50%',
              background: C.cardHover,
              overflow: 'hidden',
              flexShrink: 0,
            }}
          >
            {post.author_avatar ? (
              <Image src={post.author_avatar} style={{ width: '40rpx', height: '40rpx' }} mode="aspectFill" />
            ) : null}
          </View>

          <Text style={{ color: C.text3, fontSize: '22rpx', flex: 1 }} numberOfLines={1}>
            {post.author_name}
          </Text>

          {/* Like button */}
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              gap: '6rpx',
              padding: '6rpx 8rpx',
            }}
            onClick={onLike as any}
          >
            <Text
              style={{
                fontSize: '28rpx',
                color: post.liked ? C.heartOn : C.heartOff,
                lineHeight: '1',
              }}
            >
              {post.liked ? '♥' : '♡'}
            </Text>
            <Text
              style={{
                color: post.liked ? C.primary : C.text3,
                fontSize: '22rpx',
                fontWeight: post.liked ? '700' : '400',
              }}
            >
              {post.like_count}
            </Text>
          </View>
        </View>
      </View>
    </View>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function CommunityPage() {
  const [activeTab, setActiveTab] = useState<number>(0)
  const [posts, setPosts] = useState<Post[]>([])
  const [loading, setLoading] = useState(false)
  const [noMore, setNoMore] = useState(false)
  const pageRef = useRef(1)
  const loadingRef = useRef(false)

  const loadPosts = useCallback(async (reset = false) => {
    if (loadingRef.current || (!reset && noMore)) return
    loadingRef.current = true
    setLoading(true)

    const currentPage = reset ? 1 : pageRef.current

    try {
      const res = await txRequest<{ items: Post[] }>(
        `/api/v1/growth/community/posts?tab=${TABS[activeTab].toLowerCase()}&page=${currentPage}&size=10`,
      )
      const newPosts: Post[] = res.items ?? MOCK_POSTS
      setPosts((prev) => reset ? newPosts : [...prev, ...newPosts])
      pageRef.current = currentPage + 1
      setNoMore(newPosts.length < 10)
    } catch {
      if (reset) setPosts(MOCK_POSTS)
      setNoMore(true)
    } finally {
      loadingRef.current = false
      setLoading(false)
    }
  }, [activeTab, noMore])

  // Reload when tab changes
  useEffect(() => {
    pageRef.current = 1
    setNoMore(false)
    loadPosts(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab])

  const toggleLike = useCallback(async (post: Post, globalIdx: number, e: React.MouseEvent) => {
    e.stopPropagation()
    // Optimistic update
    setPosts((prev) => {
      const next = [...prev]
      const target = next[globalIdx]
      if (!target) return prev
      next[globalIdx] = {
        ...target,
        liked: !target.liked,
        like_count: target.like_count + (target.liked ? -1 : 1),
      }
      return next
    })

    try {
      await txRequest(
        `/api/v1/growth/community/posts/${post.id}/like`,
        post.liked ? 'DELETE' : 'POST',
      )
    } catch {
      // Silent failure — optimistic update stays
    }
  }, [])

  // Split into 2 columns for masonry layout
  const leftPosts  = posts.filter((_, i) => i % 2 === 0)
  const rightPosts = posts.filter((_, i) => i % 2 === 1)

  return (
    <View style={{ minHeight: '100vh', background: C.bg, display: 'flex', flexDirection: 'column' }}>

      {/* Tab bar */}
      <View
        style={{
          display: 'flex',
          flexDirection: 'row',
          background: C.card,
          borderBottom: `1rpx solid ${C.border}`,
          position: 'sticky',
          top: 0,
          zIndex: 20,
        }}
      >
        {TABS.map((tab, i) => {
          const isActive = activeTab === i
          return (
            <View
              key={tab}
              style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                padding: '28rpx 0 20rpx',
                gap: '8rpx',
                position: 'relative',
              }}
              onClick={() => setActiveTab(i)}
            >
              <Text
                style={{
                  color: isActive ? C.primary : C.text3,
                  fontSize: '28rpx',
                  fontWeight: isActive ? '700' : '400',
                }}
              >
                {tab}
              </Text>
              {isActive && (
                <View
                  style={{
                    position: 'absolute',
                    bottom: 0,
                    width: '40rpx',
                    height: '4rpx',
                    borderRadius: '2rpx',
                    background: C.primary,
                  }}
                />
              )}
            </View>
          )
        })}
      </View>

      {/* Banner carousel */}
      <Swiper
        style={{ height: '240rpx', flexShrink: 0 }}
        autoplay
        interval={3000}
        circular
        indicatorDots
        indicatorColor="rgba(255,255,255,0.25)"
        indicatorActiveColor={C.primary}
      >
        {BANNERS.map((b) => (
          <SwiperItem key={b.id}>
            <View
              style={{
                height: '240rpx',
                background: b.bg,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '12rpx',
              }}
            >
              <Text style={{ color: C.text1, fontSize: '36rpx', fontWeight: '700' }}>
                {b.title}
              </Text>
              <View
                style={{
                  background: C.primaryDim,
                  borderRadius: '20rpx',
                  padding: '6rpx 24rpx',
                  border: `1rpx solid rgba(255,107,53,0.3)`,
                }}
              >
                <Text style={{ color: C.primary, fontSize: '24rpx', fontWeight: '600' }}>
                  {b.subtitle}
                </Text>
              </View>
            </View>
          </SwiperItem>
        ))}
      </Swiper>

      {/* Section label */}
      <View style={{ padding: '28rpx 28rpx 16rpx', display: 'flex', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
        <Text style={{ color: C.text1, fontSize: '30rpx', fontWeight: '700' }}>
          {TABS[activeTab]}
        </Text>
        <Text style={{ color: C.text3, fontSize: '24rpx' }}>
          {posts.length > 0 ? `${posts.length} 篇` : ''}
        </Text>
      </View>

      {/* 2-column masonry feed */}
      <ScrollView
        scrollY
        style={{ flex: 1 }}
        onScrollToLower={() => loadPosts(false)}
        lowerThreshold={200}
      >
        <View style={{ display: 'flex', flexDirection: 'row', padding: '0 20rpx', gap: '16rpx', alignItems: 'flex-start' }}>
          {/* Left column */}
          <View style={{ flex: 1 }}>
            {leftPosts.map((post) => {
              const globalIdx = posts.indexOf(post)
              return (
                <PostCard
                  key={post.id}
                  post={post}
                  onTap={() => Taro.navigateTo({ url: `/pages/community-detail/index?id=${post.id}` })}
                  onLike={(e) => toggleLike(post, globalIdx, e)}
                />
              )
            })}
          </View>

          {/* Right column */}
          <View style={{ flex: 1 }}>
            {rightPosts.map((post) => {
              const globalIdx = posts.indexOf(post)
              return (
                <PostCard
                  key={post.id}
                  post={post}
                  onTap={() => Taro.navigateTo({ url: `/pages/community-detail/index?id=${post.id}` })}
                  onLike={(e) => toggleLike(post, globalIdx, e)}
                />
              )
            })}
          </View>
        </View>

        {/* Loading / no-more indicators */}
        {loading && (
          <View style={{ display: 'flex', justifyContent: 'center', padding: '32rpx' }}>
            <Text style={{ color: C.text3, fontSize: '26rpx' }}>加载中…</Text>
          </View>
        )}
        {noMore && !loading && posts.length > 0 && (
          <View style={{ display: 'flex', justifyContent: 'center', padding: '32rpx' }}>
            <Text style={{ color: C.text3, fontSize: '24rpx' }}>— 已经到底啦 —</Text>
          </View>
        )}

        {/* Empty state */}
        {!loading && posts.length === 0 && (
          <View
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              padding: '80rpx 40rpx',
              gap: '24rpx',
            }}
          >
            <Text style={{ fontSize: '72rpx', lineHeight: '1' }}>🍽</Text>
            <Text style={{ color: C.text1, fontSize: '30rpx', fontWeight: '600' }}>暂无内容</Text>
            <Text style={{ color: C.text3, fontSize: '26rpx', textAlign: 'center' }}>
              {activeTab === 1 ? '关注美食达人后，这里会显示他们的动态' : '暂无推荐内容，稍后再试'}
            </Text>
          </View>
        )}

        {/* Bottom safe area above FAB */}
        <View style={{ height: '160rpx' }} />
      </ScrollView>

      {/* FAB publish button */}
      <View
        style={{
          position: 'fixed',
          right: '40rpx',
          bottom: '60rpx',
          width: '104rpx',
          height: '104rpx',
          borderRadius: '50%',
          background: C.primary,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: '0 8rpx 24rpx rgba(255,107,53,0.45)',
          zIndex: 100,
        }}
        onClick={() => Taro.navigateTo({ url: '/pages/community-publish/index' }).catch(() =>
          Taro.showToast({ title: '发布功能开发中', icon: 'none' })
        )}
      >
        <Text style={{ color: C.white, fontSize: '52rpx', lineHeight: '1', fontWeight: '300', marginTop: '-4rpx' }}>
          +
        </Text>
      </View>
    </View>
  )
}
