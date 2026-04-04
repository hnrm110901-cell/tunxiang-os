/**
 * pages/community-detail/index.tsx — 帖子详情页
 *
 * Route params: id (string)
 *
 * Sections:
 *   1. Post header: author avatar + name + follow button
 *   2. Post title (32rpx, bold)
 *   3. Cover image (if any) + content body text
 *   4. Tags row
 *   5. Stats: like count / comment count / share
 *   6. Comment list
 *   7. Fixed bottom bar: like button (brand color) + comment input + send
 *
 * API: GET /api/v1/growth/community/posts/{id} — falls back to mock on error
 * API: GET /api/v1/growth/community/posts/{id}/comments
 * API: POST /api/v1/growth/community/posts/{id}/comments
 * API: POST/DELETE /api/v1/growth/community/posts/{id}/like
 */

import React, { useState, useEffect, useCallback, useRef } from 'react'
import Taro, { useRouter } from '@tarojs/taro'
import { View, Text, Image, ScrollView, Input } from '@tarojs/components'
import { txRequest } from '../../utils/request'

// ─── Types ────────────────────────────────────────────────────────────────────

interface PostDetail {
  id: string
  title: string
  content: string
  cover_url: string
  images: string[]
  tags: string[]
  author_name: string
  author_avatar: string
  like_count: number
  comment_count: number
  liked: boolean
  created_at: string
}

interface Comment {
  id: string
  content: string
  author_name: string
  author_avatar: string
  created_at: string
  like_count: number
}

// ─── Brand tokens ─────────────────────────────────────────────────────────────

const C = {
  primary:    '#FF6B2C',
  primaryDim: 'rgba(255,107,44,0.15)',
  bg:         '#0B1A20',
  card:       '#132029',
  cardHover:  '#1A2E38',
  border:     '#1E3040',
  text1:      '#E8F4F8',
  text2:      '#9EB5C0',
  text3:      '#5A7A88',
  white:      '#fff',
} as const

// ─── Mock data ────────────────────────────────────────────────────────────────

function makeMockPost(id: string): PostDetail {
  return {
    id,
    title: '探店丨徐记海鲜的椒盐虾绝了！朋友推荐果然没让我失望',
    content: `上周末朋友带我去了徐记海鲜，点了他们的招牌椒盐虾和清蒸鲈鱼。\n\n椒盐虾外壳酥脆，椒盐撒得均匀，每一只都是那种咬下去"咔哧"一声的满足感。鲜虾本身的甜味和椒盐的香完全融合，停不下来。\n\n清蒸鲈鱼火候刚好，鱼肉嫩滑不柴，浇上热油的那一刻香气扑鼻。服务员说今天的鱼是早上刚到的，这个鲜度确实能感受到。\n\n整体来说性价比非常高，环境也不错，下次还会来。`,
    cover_url: '',
    images: [],
    tags: ['探店', '海鲜', '长沙美食'],
    author_name: '美食家小王',
    author_avatar: '',
    like_count: 128,
    comment_count: 23,
    liked: false,
    created_at: '2026-04-01T12:00:00Z',
  }
}

const MOCK_COMMENTS: Comment[] = [
  { id: 'c1', content: '这家我去过！椒盐虾是真的好吃，下次要去点它家的海鲜煲', author_name: '吃货老张', author_avatar: '', created_at: '2026-04-01T14:00:00Z', like_count: 12 },
  { id: 'c2', content: '请问人多的话需要提前预约吗？周末去的话会不会等很久', author_name: '周末美食家', author_avatar: '', created_at: '2026-04-01T15:30:00Z', like_count: 3 },
  { id: 'c3', content: '清蒸鲈鱼的做法太美了，在家也可以复刻吗？', author_name: '家庭厨娘', author_avatar: '', created_at: '2026-04-01T16:00:00Z', like_count: 7 },
]

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    const now = new Date()
    const diffMs = now.getTime() - d.getTime()
    const diffMin = Math.floor(diffMs / 60000)
    if (diffMin < 1) return '刚刚'
    if (diffMin < 60) return `${diffMin}分钟前`
    const diffH = Math.floor(diffMin / 60)
    if (diffH < 24) return `${diffH}小时前`
    const diffD = Math.floor(diffH / 24)
    if (diffD < 7) return `${diffD}天前`
    return iso.slice(0, 10)
  } catch {
    return iso.slice(0, 10)
  }
}

// ─── CommentItem ──────────────────────────────────────────────────────────────

function CommentItem({ comment }: { comment: Comment }) {
  return (
    <View
      style={{
        display: 'flex',
        flexDirection: 'row',
        gap: '20rpx',
        padding: '24rpx 0',
        borderBottom: `1rpx solid ${C.border}`,
      }}
    >
      {/* Avatar */}
      <View
        style={{
          width: '64rpx',
          height: '64rpx',
          borderRadius: '50%',
          background: C.cardHover,
          flexShrink: 0,
          overflow: 'hidden',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {comment.author_avatar
          ? <Image src={comment.author_avatar} style={{ width: '64rpx', height: '64rpx' }} mode="aspectFill" />
          : <Text style={{ fontSize: '28rpx', lineHeight: '1' }}>👤</Text>
        }
      </View>

      {/* Body */}
      <View style={{ flex: 1 }}>
        <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
          <Text style={{ color: C.text2, fontSize: '26rpx', fontWeight: '600' }}>
            {comment.author_name}
          </Text>
          <Text style={{ color: C.text3, fontSize: '22rpx' }}>{formatTime(comment.created_at)}</Text>
        </View>
        <Text style={{ color: C.text1, fontSize: '28rpx', lineHeight: '1.6', marginTop: '8rpx', display: 'block' }}>
          {comment.content}
        </Text>
        <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '8rpx', marginTop: '12rpx' }}>
          <Text style={{ color: C.text3, fontSize: '22rpx' }}>♡ {comment.like_count}</Text>
        </View>
      </View>
    </View>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function CommunityDetailPage() {
  const router = useRouter()
  const postId = router.params?.id ?? 'demo'

  const [post, setPost] = useState<PostDetail | null>(null)
  const [comments, setComments] = useState<Comment[]>([])
  const [loading, setLoading] = useState(true)
  const [commentText, setCommentText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [liked, setLiked] = useState(false)
  const [likeCount, setLikeCount] = useState(0)

  // Load post detail
  useEffect(() => {
    setLoading(true)
    Promise.all([
      txRequest<PostDetail>(`/api/v1/growth/community/posts/${postId}`),
      txRequest<{ items: Comment[] }>(`/api/v1/growth/community/posts/${postId}/comments?page=1&size=20`),
    ])
      .then(([postData, commentData]) => {
        setPost(postData)
        setLiked(postData.liked)
        setLikeCount(postData.like_count)
        setComments(commentData.items ?? [])
      })
      .catch(() => {
        const mock = makeMockPost(postId)
        setPost(mock)
        setLiked(mock.liked)
        setLikeCount(mock.like_count)
        setComments(MOCK_COMMENTS)
      })
      .finally(() => setLoading(false))
  }, [postId])

  const handleLike = useCallback(async () => {
    // Optimistic
    const wasLiked = liked
    setLiked(!wasLiked)
    setLikeCount((c) => c + (wasLiked ? -1 : 1))

    try {
      await txRequest(
        `/api/v1/growth/community/posts/${postId}/like`,
        wasLiked ? 'DELETE' : 'POST',
      )
    } catch {
      // Revert on failure
      setLiked(wasLiked)
      setLikeCount((c) => c + (wasLiked ? 1 : -1))
    }
  }, [liked, postId])

  const handleSubmitComment = useCallback(async () => {
    const text = commentText.trim()
    if (!text || submitting) return

    setSubmitting(true)
    try {
      await txRequest(
        `/api/v1/growth/community/posts/${postId}/comments`,
        'POST',
        { content: text },
      )
      // Prepend optimistic comment
      const optimistic: Comment = {
        id: `opt_${Date.now()}`,
        content: text,
        author_name: '我',
        author_avatar: '',
        created_at: new Date().toISOString(),
        like_count: 0,
      }
      setComments((prev) => [optimistic, ...prev])
      setCommentText('')
      Taro.showToast({ title: '评论成功', icon: 'success', duration: 1200 })
    } catch (err: any) {
      Taro.showToast({ title: err?.message ?? '评论失败', icon: 'none', duration: 2000 })
    } finally {
      setSubmitting(false)
    }
  }, [commentText, submitting, postId])

  // ── Skeleton ─────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <View style={{ minHeight: '100vh', background: C.bg, padding: '40rpx 32rpx' }}>
        {[240, 40, 200, 160, 80].map((h, i) => (
          <View
            key={i}
            style={{
              height: `${h}rpx`,
              background: C.card,
              borderRadius: '16rpx',
              marginBottom: '24rpx',
              opacity: 0.5,
            }}
          />
        ))}
      </View>
    )
  }

  if (!post) return null

  return (
    <View style={{ minHeight: '100vh', background: C.bg, display: 'flex', flexDirection: 'column' }}>
      <ScrollView scrollY style={{ flex: 1 }}>
        <View style={{ padding: '32rpx 32rpx 0' }}>

          {/* Author header */}
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              gap: '20rpx',
              marginBottom: '28rpx',
            }}
          >
            <View
              style={{
                width: '80rpx',
                height: '80rpx',
                borderRadius: '50%',
                background: C.cardHover,
                overflow: 'hidden',
                flexShrink: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {post.author_avatar
                ? <Image src={post.author_avatar} style={{ width: '80rpx', height: '80rpx' }} mode="aspectFill" />
                : <Text style={{ fontSize: '36rpx', lineHeight: '1' }}>👤</Text>
              }
            </View>

            <View style={{ flex: 1 }}>
              <Text style={{ color: C.text1, fontSize: '28rpx', fontWeight: '600', display: 'block' }}>
                {post.author_name}
              </Text>
              <Text style={{ color: C.text3, fontSize: '22rpx', marginTop: '4rpx', display: 'block' }}>
                {formatTime(post.created_at)}
              </Text>
            </View>

            <View
              style={{
                background: C.primaryDim,
                borderRadius: '40rpx',
                padding: '12rpx 28rpx',
                border: `1rpx solid rgba(255,107,44,0.3)`,
              }}
            >
              <Text style={{ color: C.primary, fontSize: '24rpx', fontWeight: '600' }}>+ 关注</Text>
            </View>
          </View>

          {/* Title */}
          <Text
            style={{
              color: C.text1,
              fontSize: '34rpx',
              fontWeight: '700',
              lineHeight: '1.5',
              display: 'block',
              marginBottom: '24rpx',
            }}
          >
            {post.title}
          </Text>

          {/* Cover image */}
          {post.cover_url ? (
            <View style={{ borderRadius: '20rpx', overflow: 'hidden', marginBottom: '28rpx' }}>
              <Image
                src={post.cover_url}
                style={{ width: '100%', height: '400rpx', display: 'block' }}
                mode="aspectFill"
                lazyLoad
              />
            </View>
          ) : (
            <View
              style={{
                borderRadius: '20rpx',
                background: C.card,
                height: '320rpx',
                marginBottom: '28rpx',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                border: `1rpx solid ${C.border}`,
              }}
            >
              <Text style={{ fontSize: '72rpx', lineHeight: '1' }}>🍜</Text>
            </View>
          )}

          {/* Content body */}
          <Text
            style={{
              color: C.text2,
              fontSize: '30rpx',
              lineHeight: '1.8',
              display: 'block',
              marginBottom: '28rpx',
              whiteSpace: 'pre-wrap',
            }}
          >
            {post.content}
          </Text>

          {/* Tags */}
          {post.tags.length > 0 && (
            <View
              style={{
                display: 'flex',
                flexDirection: 'row',
                flexWrap: 'wrap',
                gap: '12rpx',
                marginBottom: '32rpx',
              }}
            >
              {post.tags.map((tag) => (
                <View
                  key={tag}
                  style={{
                    background: C.primaryDim,
                    borderRadius: '8rpx',
                    padding: '8rpx 20rpx',
                  }}
                >
                  <Text style={{ color: C.primary, fontSize: '24rpx' }}>#{tag}</Text>
                </View>
              ))}
            </View>
          )}

          {/* Stats bar */}
          <View
            style={{
              display: 'flex',
              flexDirection: 'row',
              gap: '32rpx',
              padding: '24rpx 0',
              borderTop: `1rpx solid ${C.border}`,
              borderBottom: `1rpx solid ${C.border}`,
              marginBottom: '8rpx',
            }}
          >
            <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '8rpx' }}>
              <Text style={{ color: liked ? C.primary : C.text3, fontSize: '28rpx' }}>
                {liked ? '♥' : '♡'}
              </Text>
              <Text style={{ color: C.text3, fontSize: '24rpx' }}>{likeCount}</Text>
            </View>
            <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '8rpx' }}>
              <Text style={{ color: C.text3, fontSize: '28rpx' }}>💬</Text>
              <Text style={{ color: C.text3, fontSize: '24rpx' }}>{comments.length}</Text>
            </View>
            <View style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '8rpx' }}>
              <Text style={{ color: C.text3, fontSize: '28rpx' }}>↗</Text>
              <Text style={{ color: C.text3, fontSize: '24rpx' }}>分享</Text>
            </View>
          </View>

          {/* Comments section header */}
          <Text
            style={{
              color: C.text2,
              fontSize: '26rpx',
              fontWeight: '700',
              letterSpacing: '1rpx',
              display: 'block',
              padding: '24rpx 0 8rpx',
            }}
          >
            评论 {comments.length > 0 ? `(${comments.length})` : ''}
          </Text>

          {/* Comment list */}
          {comments.length === 0 ? (
            <View
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                padding: '48rpx 0 32rpx',
                gap: '16rpx',
              }}
            >
              <Text style={{ fontSize: '56rpx', lineHeight: '1' }}>💬</Text>
              <Text style={{ color: C.text3, fontSize: '26rpx' }}>暂无评论，来说第一句话吧</Text>
            </View>
          ) : (
            comments.map((comment) => (
              <CommentItem key={comment.id} comment={comment} />
            ))
          )}
        </View>

        {/* Bottom padding for fixed bar */}
        <View style={{ height: '160rpx' }} />
      </ScrollView>

      {/* Fixed bottom: like + comment input */}
      <View
        style={{
          position: 'fixed',
          bottom: 0,
          left: 0,
          right: 0,
          background: C.card,
          borderTop: `1rpx solid ${C.border}`,
          padding: '20rpx 24rpx',
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          gap: '16rpx',
          zIndex: 50,
        }}
      >
        {/* Like button */}
        <View
          style={{
            width: '88rpx',
            height: '88rpx',
            borderRadius: '50%',
            background: liked ? C.primary : C.cardHover,
            border: `2rpx solid ${liked ? C.primary : C.border}`,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
            gap: '2rpx',
          }}
          onClick={handleLike}
        >
          <Text style={{ color: liked ? C.white : C.text3, fontSize: '32rpx', lineHeight: '1' }}>
            {liked ? '♥' : '♡'}
          </Text>
          <Text style={{ color: liked ? C.white : C.text3, fontSize: '18rpx' }}>
            {likeCount}
          </Text>
        </View>

        {/* Comment input */}
        <View
          style={{
            flex: 1,
            background: C.cardHover,
            borderRadius: '44rpx',
            padding: '0 24rpx',
            height: '80rpx',
            display: 'flex',
            alignItems: 'center',
            border: `1rpx solid ${C.border}`,
          }}
        >
          <Input
            style={{ flex: 1, color: C.text1, fontSize: '28rpx', height: '80rpx' }}
            placeholderStyle={`color: ${C.text3}`}
            placeholder="说点什么…"
            value={commentText}
            onInput={(e) => setCommentText(e.detail.value)}
            confirmType="send"
            onConfirm={handleSubmitComment}
          />
        </View>

        {/* Send button */}
        <View
          style={{
            background: commentText.trim() ? C.primary : C.cardHover,
            borderRadius: '44rpx',
            padding: '0 28rpx',
            height: '80rpx',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
            opacity: submitting ? 0.6 : 1,
          }}
          onClick={handleSubmitComment}
        >
          <Text
            style={{
              color: commentText.trim() ? C.white : C.text3,
              fontSize: '28rpx',
              fontWeight: '700',
            }}
          >
            {submitting ? '…' : '发送'}
          </Text>
        </View>
      </View>
    </View>
  )
}
