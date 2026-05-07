/**
 * CampaignPage — Cool Path 单个活动详情/创建（V4 sprint D5b 2026-05-07）
 *
 * D1 sign-off C2 (cool path)：营销活动详情。
 * 路由：/campaigns/:id  (id = "new" 时为创建模式)
 *
 * 此屏由 MarketingPage 列表点击进入。骨架版仅展示活动元数据 + 规则编辑表单结构，
 * 业务逻辑（保存 / 模板 / Agent 推荐）留待后续 sprint 实装。
 */
import { useState } from 'react';
import { useParams } from 'react-router-dom';

interface CampaignDraft {
  name: string;
  channel: 'dine_in' | 'takeaway' | 'all';
  discountType: 'percent' | 'amount' | 'voucher';
  discountValue: number;
  startDate: string;
  endDate: string;
  rule: string;
}

const emptyDraft: CampaignDraft = {
  name: '',
  channel: 'all',
  discountType: 'percent',
  discountValue: 0,
  startDate: '',
  endDate: '',
  rule: '',
};

export function CampaignPage(): JSX.Element {
  const { id } = useParams<{ id: string }>();
  const isNew = id === 'new' || !id;
  const [draft, setDraft] = useState<CampaignDraft>(emptyDraft);

  const update = <K extends keyof CampaignDraft>(k: K, v: CampaignDraft[K]) => {
    setDraft((prev) => ({ ...prev, [k]: v }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // TODO(post-V4): POST mac-station / tx-growth campaigns API
    alert(`(D5b 骨架) ${isNew ? '创建' : '保存'}活动：${draft.name}`);
  };

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <header className="mb-6">
        <a href="/marketing" className="text-blue-600 hover:underline text-sm">← 返回营销列表</a>
        <h1 className="text-2xl font-bold text-gray-900 mt-2">
          {isNew ? '新建活动' : `活动 #${id}`}
        </h1>
        <p className="text-sm text-gray-500 mt-1">Cool Path · D5b 骨架</p>
      </header>

      <form onSubmit={handleSubmit} className="bg-white rounded-lg shadow-sm p-6 max-w-2xl">
        <div className="space-y-4">
          <Field label="活动名称">
            <input
              type="text"
              required
              value={draft.name}
              onChange={(e) => update('name', e.target.value)}
              className="w-full border rounded-md px-3 py-2"
              placeholder="例：春节家宴 8 折"
            />
          </Field>

          <Field label="适用渠道">
            <select
              value={draft.channel}
              onChange={(e) => update('channel', e.target.value as CampaignDraft['channel'])}
              className="w-full border rounded-md px-3 py-2"
            >
              <option value="all">全部</option>
              <option value="dine_in">堂食</option>
              <option value="takeaway">外卖</option>
            </select>
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field label="优惠类型">
              <select
                value={draft.discountType}
                onChange={(e) => update('discountType', e.target.value as CampaignDraft['discountType'])}
                className="w-full border rounded-md px-3 py-2"
              >
                <option value="percent">折扣 %</option>
                <option value="amount">满减（元）</option>
                <option value="voucher">代金券</option>
              </select>
            </Field>
            <Field label="优惠值">
              <input
                type="number"
                min={0}
                value={draft.discountValue}
                onChange={(e) => update('discountValue', Number(e.target.value))}
                className="w-full border rounded-md px-3 py-2"
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Field label="开始日期">
              <input
                type="date"
                required
                value={draft.startDate}
                onChange={(e) => update('startDate', e.target.value)}
                className="w-full border rounded-md px-3 py-2"
              />
            </Field>
            <Field label="结束日期">
              <input
                type="date"
                required
                value={draft.endDate}
                onChange={(e) => update('endDate', e.target.value)}
                className="w-full border rounded-md px-3 py-2"
              />
            </Field>
          </div>

          <Field label="规则说明（顾客侧展示）">
            <textarea
              rows={3}
              value={draft.rule}
              onChange={(e) => update('rule', e.target.value)}
              className="w-full border rounded-md px-3 py-2"
              placeholder="例：春节期间堂食消费满 200 元立减 50 元，每桌每日限用 1 次"
            />
          </Field>
        </div>

        <div className="flex gap-3 mt-6">
          <button
            type="submit"
            className="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2 rounded-md font-medium"
          >
            {isNew ? '创建活动' : '保存修改'}
          </button>
          <a
            href="/marketing"
            className="bg-white border text-gray-700 px-5 py-2 rounded-md font-medium hover:bg-gray-50"
          >
            取消
          </a>
        </div>

        {/* TODO(post-V4): Agent 决策推荐（cool path C3）— 自动建议活动文案 / 折扣值 / 时段
            通过 mac-station WebSocket 推送 to cool path WebViewScreen */}
      </form>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
  return (
    <label className="block">
      <span className="block text-sm font-medium text-gray-700 mb-1">{label}</span>
      {children}
    </label>
  );
}
