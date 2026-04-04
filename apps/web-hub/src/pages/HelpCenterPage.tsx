/**
 * 帮助中心 — FAQ + 使用文档 + 在线客服 + 视频教程 + 意见反馈
 * 静态页面，无后端 API 依赖
 */
import { useState } from 'react';

/* ---------- 类型定义 ---------- */

type FaqItem = {
  question: string;
  answer: string;
};

type DocLink = {
  module: string;
  title: string;
  url: string;
};

type VideoItem = {
  id: string;
  title: string;
  duration: string;
  thumbnail: string;
};

/* ---------- 数据 ---------- */

const FAQ_LIST: FaqItem[] = [
  { question: '如何添加新门店？', answer: '进入"门店管理"页面，点击右上角"新增门店"按钮，填写门店名称、地址、联系人等基础信息后提交即可。系统会自动为新门店配置默认菜单模板和收银方案。' },
  { question: '如何修改菜品价格？', answer: '进入"菜品管理"，选择需要修改的菜品，点击"编辑"按钮，在价格栏输入新价格后保存。支持批量调价：勾选多个菜品后点击"批量改价"。价格修改会实时同步到所有关联门店的 POS 终端。' },
  { question: '会员等级是如何计算的？', answer: '会员等级基于 RFM 模型自动计算：R（最近消费时间）、F（消费频次）、M（消费金额）。系统每日凌晨自动更新等级，品牌方可在"会员中心 > 等级规则"中自定义升降级阈值。' },
  { question: '如何查看门店实时经营数据？', answer: '在"品牌概览"首页可查看汇总数据。如需查看单店明细，进入"门店管理"选择具体门店，可查看实时营收、客流、出餐效率等指标。数据每5分钟刷新一次。' },
  { question: '如何设置营销活动？', answer: '进入"营销工具"，选择活动类型（满减/折扣/赠品/储值等），设置活动规则、适用门店范围、有效时间后发布。活动上线前系统会自动检查毛利底线，确保不会低于设定的毛利阈值。' },
  { question: '员工权限如何配置？', answer: '进入"系统设置 > 角色权限"，可创建自定义角色并分配功能权限。系统预置了"店长""收银员""服务员""厨师长"四个角色模板，品牌方可在此基础上调整。' },
  { question: '如何处理客户投诉？', answer: '收到客诉后，系统会自动创建工单并分配给对应门店店长。在"品牌概览 > 待办事项"中可查看待处理客诉数量，点击进入工单中心处理。建议48小时内完成处理。' },
  { question: 'POS 终端断网了怎么办？', answer: '屯象OS 支持离线收银。门店 Mac mini 会缓存本地数据，POS 可继续完成收银、打印小票等操作。网络恢复后，数据会自动同步至云端，通常在5分钟内完成。' },
  { question: '如何导出财务报表？', answer: '进入"财务报表"页面，选择报表类型（日报/周报/月报/自定义时段），点击"导出"按钮，支持 Excel 和 PDF 两种格式。导出的报表包含营收、成本、毛利、各支付方式明细等。' },
  { question: '供应链订货如何操作？', answer: '进入"门店管理 > 供应链"，系统会根据历史用量和库存预警自动生成建议订货单。确认后一键发送给供应商。支持设置自动订货规则，达到安全库存线时自动下单。' },
  { question: '如何查看 Agent 智能决策记录？', answer: '进入"系统设置 > 决策日志"，可查看所有 AI Agent 的决策记录，包括折扣守护、智能排菜、库存预警等。每条记录包含输入上下文、推理过程、输出动作和置信度。' },
  { question: '多品牌管理如何切换？', answer: '如果您管理多个品牌，点击左上角品牌Logo旁的下拉箭头即可切换品牌。每个品牌的数据完全隔离，切换后将加载对应品牌的经营数据和配置。' },
];

const DOC_LINKS: DocLink[] = [
  { module: '收银', title: '收银操作手册', url: '/docs/pos-guide' },
  { module: '收银', title: '退款与撤单流程', url: '/docs/pos-refund' },
  { module: '菜品', title: '菜品管理指南', url: '/docs/menu-guide' },
  { module: '菜品', title: 'BOM配方管理', url: '/docs/menu-bom' },
  { module: '会员', title: '会员体系配置', url: '/docs/member-guide' },
  { module: '会员', title: '储值卡使用说明', url: '/docs/member-stored-value' },
  { module: '财务', title: '日结对账操作', url: '/docs/finance-daily' },
  { module: '财务', title: '多门店报表合并', url: '/docs/finance-multi-store' },
  { module: '营销', title: '优惠券创建教程', url: '/docs/marketing-coupon' },
  { module: '供应链', title: '供应商管理', url: '/docs/supply-vendor' },
  { module: '系统', title: '权限配置说明', url: '/docs/system-permission' },
  { module: '系统', title: '数据备份与恢复', url: '/docs/system-backup' },
];

const VIDEO_LIST: VideoItem[] = [
  { id: 'v1', title: '快速上手：首次登录与品牌配置', duration: '05:30', thumbnail: '' },
  { id: 'v2', title: 'POS 收银全流程演示', duration: '08:15', thumbnail: '' },
  { id: 'v3', title: '菜品管理：从建档到上架', duration: '06:45', thumbnail: '' },
  { id: 'v4', title: '会员体系搭建实战', duration: '10:20', thumbnail: '' },
  { id: 'v5', title: '营销活动策划与执行', duration: '07:50', thumbnail: '' },
  { id: 'v6', title: '月度财务对账操作指南', duration: '09:10', thumbnail: '' },
];

/* ---------- 样式 ---------- */

const s = {
  page: { color: '#E0E0E0' } as React.CSSProperties,
  title: { fontSize: 22, fontWeight: 700, color: '#FFFFFF', marginBottom: 24 } as React.CSSProperties,
  sectionTitle: { fontSize: 16, fontWeight: 600, color: '#FFFFFF', marginBottom: 14 } as React.CSSProperties,
  section: { marginBottom: 32 } as React.CSSProperties,

  /* FAQ */
  faqList: {
    background: '#0D2129', borderRadius: 10, border: '1px solid #1A3540', overflow: 'hidden',
  } as React.CSSProperties,
  faqItem: (isLast: boolean) => ({
    borderBottom: isLast ? 'none' : '1px solid #112A33',
  }) as React.CSSProperties,
  faqQuestion: (isOpen: boolean) => ({
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '14px 20px', cursor: 'pointer', fontSize: 14, fontWeight: 500,
    color: isOpen ? '#FF6B2C' : '#E0E0E0', transition: 'color 0.2s',
    background: 'transparent', border: 'none', width: '100%', textAlign: 'left' as const,
  }) as React.CSSProperties,
  faqArrow: (isOpen: boolean) => ({
    fontSize: 12, color: '#6B8A97', transition: 'transform 0.2s',
    transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
  }) as React.CSSProperties,
  faqAnswer: {
    padding: '0 20px 14px', fontSize: 13, color: '#8BA5B2', lineHeight: 1.7,
  } as React.CSSProperties,

  /* 使用文档 */
  docGrid: {
    display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 12,
  } as React.CSSProperties,
  docCard: {
    background: '#0D2129', borderRadius: 8, padding: '14px 18px',
    border: '1px solid #1A3540', cursor: 'pointer', transition: 'border-color 0.2s',
    textDecoration: 'none', display: 'block',
  } as React.CSSProperties,
  docModule: {
    display: 'inline-block', padding: '1px 8px', borderRadius: 4,
    fontSize: 11, fontWeight: 600, background: '#FF6B2C22', color: '#FF6B2C', marginBottom: 6,
  } as React.CSSProperties,
  docTitle: { fontSize: 13, color: '#E0E0E0', fontWeight: 500 } as React.CSSProperties,

  /* 在线客服 + 意见反馈 */
  actionRow: { display: 'flex', gap: 16, marginBottom: 32, flexWrap: 'wrap' as const } as React.CSSProperties,
  btn: {
    background: '#FF6B2C', color: '#FFF', border: 'none', borderRadius: 8,
    padding: '12px 28px', fontSize: 14, fontWeight: 600, cursor: 'pointer',
  } as React.CSSProperties,
  btnOutline: {
    background: 'transparent', color: '#FF6B2C', border: '1px solid #FF6B2C', borderRadius: 8,
    padding: '12px 28px', fontSize: 14, fontWeight: 600, cursor: 'pointer',
  } as React.CSSProperties,

  /* 视频教程 */
  videoGrid: {
    display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 16,
  } as React.CSSProperties,
  videoCard: {
    background: '#0D2129', borderRadius: 10, border: '1px solid #1A3540',
    overflow: 'hidden', cursor: 'pointer', transition: 'border-color 0.2s',
  } as React.CSSProperties,
  videoThumb: {
    width: '100%', height: 135, background: '#162D38',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: 36, color: '#FF6B2C', position: 'relative' as const,
  } as React.CSSProperties,
  videoDuration: {
    position: 'absolute' as const, bottom: 8, right: 8,
    background: 'rgba(0,0,0,0.7)', color: '#FFF', fontSize: 11,
    padding: '2px 6px', borderRadius: 4,
  } as React.CSSProperties,
  videoInfo: { padding: '12px 14px' } as React.CSSProperties,
  videoTitle: { fontSize: 13, color: '#E0E0E0', fontWeight: 500 } as React.CSSProperties,

  /* 播放弹窗 */
  overlay: {
    position: 'fixed' as const, inset: 0, background: 'rgba(0,0,0,0.75)',
    display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
  } as React.CSSProperties,
  modal: {
    background: '#0D2129', borderRadius: 12, padding: 24,
    border: '1px solid #1A3540', width: '90%', maxWidth: 560, textAlign: 'center' as const,
  } as React.CSSProperties,
  modalTitle: { fontSize: 16, fontWeight: 600, color: '#FFFFFF', marginBottom: 16 } as React.CSSProperties,
  modalPlayer: {
    width: '100%', height: 280, background: '#162D38', borderRadius: 8,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: 48, color: '#FF6B2C', marginBottom: 16,
  } as React.CSSProperties,
  modalClose: {
    background: 'transparent', border: '1px solid #6B8A97', borderRadius: 6,
    color: '#6B8A97', padding: '8px 24px', fontSize: 13, cursor: 'pointer',
  } as React.CSSProperties,
};

/* ---------- 组件 ---------- */

export function HelpCenterPage() {
  const [openFaq, setOpenFaq] = useState<number | null>(null);
  const [playingVideo, setPlayingVideo] = useState<VideoItem | null>(null);

  const toggleFaq = (idx: number) => {
    setOpenFaq(openFaq === idx ? null : idx);
  };

  return (
    <div style={s.page}>
      <div style={s.title}>帮助中心</div>

      {/* FAQ 折叠列表 */}
      <div style={s.section}>
        <div style={s.sectionTitle}>常见问题</div>
        <div style={s.faqList}>
          {FAQ_LIST.map((faq, idx) => {
            const isOpen = openFaq === idx;
            const isLast = idx === FAQ_LIST.length - 1;
            return (
              <div key={faq.question} style={s.faqItem(isLast)}>
                <button
                  type="button"
                  style={s.faqQuestion(isOpen)}
                  onClick={() => toggleFaq(idx)}
                >
                  <span>{faq.question}</span>
                  <span style={s.faqArrow(isOpen)}>&#9660;</span>
                </button>
                {isOpen && <div style={s.faqAnswer}>{faq.answer}</div>}
              </div>
            );
          })}
        </div>
      </div>

      {/* 使用文档 */}
      <div style={s.section}>
        <div style={s.sectionTitle}>使用文档</div>
        <div style={s.docGrid}>
          {DOC_LINKS.map((doc) => (
            <a
              key={doc.url}
              href={doc.url}
              style={s.docCard}
              target="_blank"
              rel="noopener noreferrer"
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLAnchorElement).style.borderColor = '#FF6B2C';
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLAnchorElement).style.borderColor = '#1A3540';
              }}
            >
              <div style={s.docModule}>{doc.module}</div>
              <div style={s.docTitle}>{doc.title}</div>
            </a>
          ))}
        </div>
      </div>

      {/* 在线客服 + 意见反馈 */}
      <div style={s.actionRow}>
        <button type="button" style={s.btn} onClick={() => window.alert('客服系统正在接入中，请稍后…')}>
          在线客服
        </button>
        <button type="button" style={s.btnOutline} onClick={() => window.alert('感谢您的反馈，我们会尽快处理！')}>
          意见反馈
        </button>
      </div>

      {/* 视频教程 */}
      <div style={s.section}>
        <div style={s.sectionTitle}>视频教程</div>
        <div style={s.videoGrid}>
          {VIDEO_LIST.map((video) => (
            <div
              key={video.id}
              style={s.videoCard}
              onClick={() => setPlayingVideo(video)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') setPlayingVideo(video);
              }}
              role="button"
              tabIndex={0}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLDivElement).style.borderColor = '#FF6B2C';
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLDivElement).style.borderColor = '#1A3540';
              }}
            >
              <div style={s.videoThumb}>
                <span>&#9654;</span>
                <span style={s.videoDuration}>{video.duration}</span>
              </div>
              <div style={s.videoInfo}>
                <div style={s.videoTitle}>{video.title}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 视频播放弹窗（模拟） */}
      {playingVideo && (
        <div
          style={s.overlay}
          onClick={() => setPlayingVideo(null)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setPlayingVideo(null);
          }}
          role="button"
          tabIndex={0}
        >
          <div
            style={s.modal}
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
            role="dialog"
            aria-label={playingVideo.title}
          >
            <div style={s.modalTitle}>{playingVideo.title}</div>
            <div style={s.modalPlayer}>
              <span>&#9654;</span>
            </div>
            <div style={{ fontSize: 13, color: '#6B8A97', marginBottom: 16 }}>
              视频播放功能开发中，敬请期待…（时长 {playingVideo.duration}）
            </div>
            <button type="button" style={s.modalClose} onClick={() => setPlayingVideo(null)}>
              关闭
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
